# -*- coding: utf-8 -*-
"""微信窗口「摆在可见区域外」的离线单测（不碰微信）。

为什么需要这个功能
------------------
后台通道点会话行、点发送按钮靠的是**发给窗口的合成鼠标消息**，而微信最小化时
任何写操作都不生效（合成鼠标消息不生效、Invoke 也不生效）。所以通道每次发送
都要把窗口恢复出来 —— 用户屏幕上就会冒 3~4 秒。
把窗口一直摆在可见区域外，通道照样能点（窗口仍 visible 且不 minimized），
但屏幕上完全没动静。

跑法：python -B tests/test_window_position.py
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'bridge'))

from bridge_ast import init, load_function  # noqa: E402


class FakeWin32:
    """够用的 win32 替身：只模拟窗口位置相关的调用。"""

    def __init__(self):
        self.rect = (100, 80, 900, 700)          # left, top, right, bottom
        self.iconic = False
        self.placed = []
        self.moved = []
        self.visible = True

    # --- win32gui ---
    def IsWindow(self, hwnd):
        return bool(hwnd)

    def IsIconic(self, hwnd):
        return self.iconic

    def IsWindowVisible(self, hwnd):
        return self.visible

    def GetWindowRect(self, hwnd):
        return self.rect

    def GetWindowPlacement(self, hwnd):
        # (flags, showCmd, ptMin, ptMax, normalPosition)
        return (0, 0, (-32000, -32000), (-32000, -32000), self.rect)

    def SetWindowPlacement(self, hwnd, placement):
        self.placed.append(tuple(placement[4]))
        self.rect = tuple(placement[4])
        return True

    def SetWindowPos(self, hwnd, after, x, y, cx, cy, flags):
        self.moved.append((x, y, cx, cy, flags))
        self.rect = (x, y, x + cx, y + cy)
        return True

    def GetForegroundWindow(self):
        return 999

    # --- win32api ---
    def GetSystemMetrics(self, index):
        # 虚拟屏幕 0,0 1920x1080；SM_* 索引见 win32con 常量
        return {0: 0, 1: 0, 2: 1920, 3: 1080,
                76: 0, 77: 0, 78: 1920, 79: 1080}.get(index, 0)

    def MonitorFromPoint(self, point, flags):
        return 1


def install_fake_win32(fake):
    """把 fake win32 模块塞进 sys.modules，函数内部 import 就能拿到。"""
    import types
    gui = types.ModuleType('win32gui')
    con = types.ModuleType('win32con')
    api = types.ModuleType('win32api')
    for name in ('IsWindow', 'IsIconic', 'IsWindowVisible', 'GetWindowRect',
                 'GetWindowPlacement', 'SetWindowPlacement', 'SetWindowPos',
                 'GetForegroundWindow'):
        setattr(gui, name, getattr(fake, name))
    for name in ('MonitorFromPoint', 'GetSystemMetrics'):
        setattr(api, name, getattr(fake, name))
    con.SW_MINIMIZE, con.HWND_TOP, con.SWP_NOACTIVATE = 6, 0, 0x0010
    con.SW_SHOWNOACTIVATE = 4
    con.SM_XVIRTUALSCREEN, con.SM_YVIRTUALSCREEN = 76, 77
    con.SM_CXVIRTUALSCREEN, con.SM_CYVIRTUALSCREEN = 78, 79
    sys.modules['win32gui'], sys.modules['win32con'], sys.modules['win32api'] = gui, con, api


def build_env(pref='offscreen', fake=None):
    fake = fake or FakeWin32()
    install_fake_win32(fake)
    env = {
        'BG_SEND': {'windowPosition': pref},
        'ACCOUNT': {'hwnd': 4242},
        'find_weixin_hwnd': lambda: 4242,
        'log': lambda *a: None,
        # 类常量在单函数抽取时不会自动带进来
        'OFFSCREEN_GAP': 120,
    }
    init(env)
    env['window_position_pref'] = load_function('window_position_pref', env)
    env['_window_state_path'] = lambda: os.path.join(tempfile.gettempdir(), 'whale-window-test.json')
    env['_read_window_state'] = load_function('_read_window_state', env)
    env['_write_window_state'] = load_function('_write_window_state', env)
    env['_window_normal_rect'] = load_function('_window_normal_rect', env)
    env['_window_is_offscreen'] = load_function('_window_is_offscreen', env)
    env['_move_window'] = load_function('_move_window', env)
    env['apply_window_position'] = load_function('apply_window_position', env)
    return env, fake


class WindowPositionPref(unittest.TestCase):
    def test_pref_reads_bg_send(self):
        env, _ = build_env(pref='offscreen')
        self.assertEqual(env['window_position_pref'](), 'offscreen')

    def test_unknown_pref_is_normal(self):
        env, _ = build_env(pref='normal')
        self.assertEqual(env['window_position_pref'](), 'normal')


class ApplyWindowPosition(unittest.TestCase):
    def tearDown(self):
        try:
            os.remove(os.path.join(tempfile.gettempdir(), 'whale-window-test.json'))
        except OSError:
            pass

    def test_offscreen_moves_window_out_of_screen_and_keeps_rect(self):
        env, fake = build_env(pref='offscreen')
        # 清理上次留下的状态文件
        try:
            os.remove(os.path.join(tempfile.gettempdir(), 'whale-window-test.json'))
        except OSError:
            pass
        ok = env['apply_window_position'](4242)
        self.assertTrue(ok)
        # 窗口整个挪到可见区域外（右边在虚拟屏幕左边之外）
        left, top, right, bottom = fake.rect
        self.assertLess(right, 0)
        # 原来的位置被记下来，改回 normal 时能还原
        state = env['_read_window_state']()
        self.assertEqual(state.get('position'), 'offscreen')
        self.assertEqual(state.get('restore'), [100, 80, 800, 620])

    def test_normal_moves_window_back_to_saved_rect(self):
        env, fake = build_env(pref='offscreen')
        try:
            os.remove(os.path.join(tempfile.gettempdir(), 'whale-window-test.json'))
        except OSError:
            pass
        env['apply_window_position'](4242)          # 先挪出去
        self.assertLess(fake.rect[2], 0)

        env['BG_SEND'] = {'windowPosition': 'normal'}
        ok = env['apply_window_position'](4242)
        self.assertTrue(ok)
        self.assertEqual(fake.rect, (100, 80, 900, 700))

    def test_normal_leaves_window_alone_when_on_screen(self):
        env, fake = build_env(pref='normal')
        env['apply_window_position'](4242)
        self.assertEqual(fake.rect, (100, 80, 900, 700))
        self.assertEqual(fake.placed, [])

    def test_offscreen_is_idempotent(self):
        env, fake = build_env(pref='offscreen')
        try:
            os.remove(os.path.join(tempfile.gettempdir(), 'whale-window-test.json'))
        except OSError:
            pass
        env['apply_window_position'](4242)
        placed_once = len(fake.placed)
        env['apply_window_position'](4242)
        self.assertEqual(len(fake.placed), placed_once, '已经在屏幕外就别再挪了')


class ShowWindowForForeground(unittest.TestCase):
    """抢前台的路径（录音、表情包）之前必须把窗口挪回屏幕内。

    窗口在屏幕外时它照样能被抢到前台，但用户看不见它 —— 敲的字会掉进
    微信输入框。所以这类操作前要先挪回来，发完再挪回去。
    """

    def tearDown(self):
        try:
            os.remove(os.path.join(tempfile.gettempdir(), 'whale-window-test.json'))
        except OSError:
            pass

    def _offscreen_env(self):
        env, fake = build_env(pref='offscreen')
        try:
            os.remove(os.path.join(tempfile.gettempdir(), 'whale-window-test.json'))
        except OSError:
            pass
        env['apply_window_position'](4242)      # 先挪到屏幕外
        env['show_window_for_foreground'] = load_function('show_window_for_foreground', env)
        return env, fake

    def test_brings_window_back_onscreen(self):
        env, fake = self._offscreen_env()
        self.assertLess(fake.rect[2], 0)
        self.assertTrue(env['show_window_for_foreground'](4242))
        self.assertEqual(fake.rect, (100, 80, 900, 700))

    def test_noop_when_window_is_already_onscreen(self):
        env, fake = build_env(pref='offscreen')
        env['show_window_for_foreground'] = load_function('show_window_for_foreground', env)
        self.assertFalse(env['show_window_for_foreground'](4242))
        self.assertEqual(fake.rect, (100, 80, 900, 700))

    def test_noop_when_pref_is_normal(self):
        env, fake = build_env(pref='normal')
        env['show_window_for_foreground'] = load_function('show_window_for_foreground', env)
        self.assertFalse(env['show_window_for_foreground'](4242))


class BgSendConfig(unittest.TestCase):
    def test_parse_bg_send_reads_window_position(self):
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'bridge'))
        from config_values import parse_bg_send
        self.assertEqual(parse_bg_send({'bgSend': {'windowPosition': 'offscreen'}})['windowPosition'], 'offscreen')
        self.assertEqual(parse_bg_send({'bgSend': {'windowPosition': 'normal'}})['windowPosition'], 'normal')
        # 坏值退回 normal，不能让窗口乱跑
        self.assertEqual(parse_bg_send({'bgSend': {'windowPosition': '???'}})['windowPosition'], 'normal')
        self.assertEqual(parse_bg_send({})['windowPosition'], 'normal')


if __name__ == '__main__':
    unittest.main()
