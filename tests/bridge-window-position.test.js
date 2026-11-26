'use strict';

/**
 * 回归：「把微信窗口挪到可见区域外」这条能力要真的接上。
 *
 * 现场：后台通道点会话行/点发送按钮靠的是发给窗口的合成鼠标消息，微信最小化时
 * 任何写操作都不生效，所以通道每次发送都要把窗口恢复出来 —— 用户屏幕上就冒
 * 3~4 秒。窗口一直摆在可见区域外就没有动静（窗口仍 visible，通道照样能点）。
 *
 * 这里盯三处接线：内核认这个配置项、桥接按它摆窗口、启动器有个能点的开关。
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..');
const src = require('./helpers/bridge-source');

const schema = fs.readFileSync(path.join(root, 'src', 'infra', 'configSchema.js'), 'utf8');
const config = fs.readFileSync(path.join(root, 'src', 'infra', 'config.js'), 'utf8');
const windowMixin = fs.readFileSync(path.join(root, 'bridge', 'window_mixin.py'), 'utf8');
const senderMixin = fs.readFileSync(path.join(root, 'bridge', 'sender_mixin.py'), 'utf8');
const bgSender = fs.readFileSync(path.join(root, 'bridge', 'bg_sender.py'), 'utf8');
const bridgeXaml = fs.readFileSync(path.join(root, 'launcher', 'Views', 'BridgePage.xaml'), 'utf8');
const bridgeCode = fs.readFileSync(path.join(root, 'launcher', 'Views', 'BridgePage.xaml.cs'), 'utf8');

test('内核配置 schema 认识 windowPosition（只认 normal/offscreen）', () => {
  assert.match(schema, /'wechat\.bgSend\.windowPosition'\s*:\s*\{\s*type:\s*'enum',\s*values:\s*\['normal',\s*'offscreen'\]\s*\}/,
    'configSchema 里没有这个枚举，配置补丁会被当成未知字段丢掉');
  assert.match(config, /windowPosition:\s*'normal'/, '默认值必须是 normal（默认不改变用户现状）');
});

test('桥接把 windowPosition 读进 BG_SEND', () => {
  assert.match(src, /windowPosition/, '桥接根本没读这个配置项');
  assert.match(src, /"windowPosition"\s*:\s*\("offscreen"/, 'parse_bg_send 没有解析 windowPosition');
});

test('摆窗口用 SetWindowPlacement + SWP_NOACTIVATE，不能抢前台', () => {
  assert.match(windowMixin, /def apply_window_position/, '没有 apply_window_position');
  const mover = windowMixin.slice(windowMixin.indexOf('def _move_window'));
  assert.match(mover, /SetWindowPlacement/, '最小化的窗口要用 SetWindowPlacement 挪恢复位置');
  assert.match(mover, /SWP_NOACTIVATE/, '挪窗口不能激活它（否则就是抢前台）');
  assert.doesNotMatch(mover.slice(0, mover.indexOf('def foreground_is_moments')),
    /SetForegroundWindow|keybd_event|SendInput/,
    '摆窗口的过程中不允许调 SetForegroundWindow / 模拟按键');
});

test('后台发送前先按配置摆窗口', () => {
  const bg = senderMixin.slice(senderMixin.indexOf('def bg_send'));
  assert.match(bg, /apply_window_position/, '发送前没有摆窗口，窗口会照旧冒到屏幕上');
});

test('点击点校验不能要求「点在某块屏幕上」——窗口挪到屏幕外就发不出去了', () => {
  const guard = bgSender.slice(bgSender.indexOf('def _click_point_on_window'));
  const end = guard.indexOf('\nclass ');
  const body = end > 0 ? guard.slice(0, end) : guard;
  assert.match(body, /SM_CXVIRTUALSCREEN/, '窗口和屏幕有交集时才算「点在屏上」');
  assert.doesNotMatch(body, /return \(left <= x < right and top <= y < bottom\s*\n?\s*and bool\(win32api\.MonitorFromPoint/,
    '还是老写法：窗口一挪出屏幕就点不动了');
});

test('启动器微信桥接页有「挪到屏幕外 / 拉回屏幕」的按钮', () => {
  assert.match(bridgeXaml, /x:Name="BtnWindowPos"/, '桥接页没有这个按钮');
  assert.match(bridgeXaml, /Click="OnToggleWindowPos"/, '按钮没接点击事件');
  assert.match(bridgeCode, /private async void OnToggleWindowPos/, '没有 OnToggleWindowPos');
  assert.match(bridgeCode, /\["windowPosition"\]\s*=\s*next/, '点击没有写回配置');
  assert.match(bridgeCode, /UpdateWindowPosButton/, '按钮文案没有随状态切换');
});

test('按钮文案要能看出当前状态（点了是拉回，还是挪出去）', () => {
  assert.match(bridgeCode, /把微信窗口挪到屏幕外/, '没写「挪到屏幕外」的文案');
  assert.match(bridgeCode, /把微信窗口拉回屏幕/, '没写「拉回屏幕」的文案');
});

test('激活微信窗口时前台锁拒绝后要有兜底（否则表情包/语音永远发不出去）', () => {
  const act = fs.readFileSync(path.join(root, 'bridge', 'window_activation.py'), 'utf8');
  assert.match(act, /SwitchToThisWindow/, 'SetForegroundWindow 被前台锁拒绝时没有兜底，激活会失败');
  assert.doesNotMatch(act, /keybd_event/, '兜底不该用 ALT 解锁，那会往用户正在用的程序里塞真实按键');
});

test('打字通道可以走 WM_CHAR（不抢前台）', () => {
  const bg = fs.readFileSync(path.join(root, 'bridge', 'bg_sender.py'), 'utf8');
  assert.match(bg, /prefer_wmchar/, '没有「WM_CHAR 优先」的开关');
  assert.match(bg, /typing_mode/, 'send() 没有把打字通道开关透传下去');
  const schema = fs.readFileSync(path.join(root, 'src', 'infra', 'configSchema.js'), 'utf8');
  assert.match(schema, /'wechat\.bgSend\.typingMode'\s*:\s*\{\s*type:\s*'enum',\s*values:\s*\['auto',\s*'wmchar'\]\s*}/,
    'configSchema 里没有这个枚举，配置补丁会被当成未知字段丢掉');
});
