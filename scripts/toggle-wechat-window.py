#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键切换「微信窗口摆在屏幕外 / 屏幕内」。

启动器里有同名按钮（微信桥接页 → 把微信窗口挪到屏幕外 / 拉回屏幕）。
这个脚本是给「启动器还没重新构建」时用的等价物：改 config.json 里的
`wechat.bgSend.windowPosition`，并顺手把窗口挪到位；桥接每 20 秒也会按配置
纠正一次（微信重启后窗口自己回到屏幕内，也是它拉回去的）。

用法：
    python scripts/toggle-wechat-window.py          # 切换
    python scripts/toggle-wechat-window.py --status  # 只看当前状态
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, 'data', 'config.json')
STATE = os.path.join(ROOT, 'data', 'wechat-window.json')
GAP = 120


def read_config():
    try:
        with open(CONFIG, 'r', encoding='utf-8-sig') as f:
            return json.load(f)
    except Exception:
        return {}


def write_config(cfg):
    tmp = CONFIG + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG)


def current_pref(cfg):
    return str((((cfg.get('wechat') or {}).get('bgSend') or {}).get('windowPosition')) or 'normal').strip().lower()


def set_pref(cfg, value):
    wechat = cfg.setdefault('wechat', {})
    bg = wechat.setdefault('bgSend', {})
    bg['windowPosition'] = value


def find_wechat_window():
    """找微信主窗（按类名/标题；找不到就返回 0）。"""
    try:
        import win32gui
        import win32process
    except Exception:
        return 0
    best = [0, 0]      # [面积, hwnd]；用列表，闭包里能直接改
    def cb(h, _):
        try:
            title = win32gui.GetWindowText(h) or ''
            cls = win32gui.GetClassName(h) or ''
            if title.strip() not in ('微信', 'Weixin', 'WeChat'):
                return True
            if 'mmui' not in cls.lower() and 'qt' not in cls.lower():
                return True
            area = win32gui.GetWindowRect(h)
            size = abs((area[2] - area[0]) * (area[3] - area[1]))
            if size > best[0]:
                best[0], best[1] = size, h
        except Exception:
            pass
        return True
    try:
        win32gui.EnumWindows(cb, None)
    except Exception:
        pass
    return best[1]


def move(hwnd, offscreen):
    """挪窗口（不激活、不抢前台）；返回是否成功。"""
    try:
        import win32api
        import win32con
        import win32gui
    except Exception:
        return False
    try:
        if win32gui.IsIconic(hwnd):
            l, t, r, b = win32gui.GetWindowPlacement(hwnd)[4]
        else:
            l, t, r, b = win32gui.GetWindowRect(hwnd)
        w, h = max(240, r - l), max(240, b - t)
        vx = win32api.GetSystemMetrics(win32con.SM_XVIRTUALSCREEN)
        vy = win32api.GetSystemMetrics(win32con.SM_YVIRTUALSCREEN)
        vw = win32api.GetSystemMetrics(win32con.SM_CXVIRTUALSCREEN)
        vh = win32api.GetSystemMetrics(win32con.SM_CYVIRTUALSCREEN)
        on_screen = (l < vx + vw and r > vx and t < vy + vh and b > vy)
        state = {}
        try:
            with open(STATE, 'r', encoding='utf-8') as f:
                state = json.load(f)
        except Exception:
            state = {}
        if offscreen:
            if not on_screen:
                return True                      # 已经在外面了
            x = -w - GAP
            state['position'] = 'offscreen'
            state['restore'] = [int(l), int(t), int(w), int(h)]
        else:
            if on_screen:
                return True
            restore = state.get('restore') or []
            if len(restore) == 4:
                l, t, w, h = [int(v) for v in restore]
            else:
                l, t, w, h = 60, 60, 1000, 700
            x = l
            state['position'] = 'normal'
        placement = list(win32gui.GetWindowPlacement(hwnd))
        placement[4] = (int(x), int(t), int(x + w), int(t + h))
        win32gui.SetWindowPlacement(hwnd, placement)
        if not win32gui.IsIconic(hwnd):
            win32gui.SetWindowPos(hwnd, win32con.HWND_TOP, int(x), int(t), int(w), int(h),
                                  win32con.SWP_NOACTIVATE)
        try:
            with open(STATE, 'w', encoding='utf-8') as f:
                json.dump(state, f, ensure_ascii=False)
        except Exception:
            pass
        return True
    except Exception:
        return False


def main():
    cfg = read_config()
    pref = current_pref(cfg)
    if '--status' in sys.argv:
        print('当前：%s' % ('屏幕外' if pref == 'offscreen' else '屏幕内'))
        return 0
    nxt = 'normal' if pref == 'offscreen' else 'offscreen'
    set_pref(cfg, nxt)
    write_config(cfg)
    hwnd = find_wechat_window()
    ok = move(hwnd, nxt == 'offscreen') if hwnd else False
    print('已切到：%s%s' % ('屏幕外' if nxt == 'offscreen' else '屏幕内',
                            '' if ok else '（窗口没找到，稍后桥接会按配置纠正）'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
