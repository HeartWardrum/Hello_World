# -*- coding: utf-8 -*-
"""Win11 任务栏常驻序号：在任务栏应用图标上显示 1-9、0。"""

import ctypes
import sys
import threading
import time

# 必须在创建窗口 / 读屏幕尺寸之前启用，否则高 DPI 下坐标会对不上
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)
if sys.platform == "win32":
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(
            DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
        )
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

try:
    import uiautomation as auto
    import win32api
    import win32con
    import win32gui
except ImportError:
    print("缺少依赖，请先运行: pip install uiautomation pywin32")
    input("按 Enter 退出...")
    sys.exit(1)

user32 = ctypes.windll.user32

WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
WS_POPUP = 0x80000000
LWA_COLORKEY = 0x00000001
HWND_TOPMOST = -1
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
GW_HWNDPREV = 3

CLASS_NAME = "Win11TaskbarNumbersOverlay"
# 色键透明：纯品红，任务栏上几乎不会出现
COLORKEY = 0xFF00FF
TEXT_COLOR = 0x00E0FF  # 亮黄（BGR）

hwnd_overlay = None


def virtual_screen_rect():
    """虚拟桌面矩形（含多显示器），物理像素。"""
    left = user32.GetSystemMetrics(76)   # SM_XVIRTUALSCREEN
    top = user32.GetSystemMetrics(77)    # SM_YVIRTUALSCREEN
    width = user32.GetSystemMetrics(78)  # SM_CXVIRTUALSCREEN
    height = user32.GetSystemMetrics(79)  # SM_CYVIRTUALSCREEN
    return left, top, width, height


def find_taskbar_app_buttons():
    """只取 Win11 任务栏上的应用按钮（不含开始/托盘）。"""
    rects = []
    try:
        taskbar = auto.PaneControl(ClassName="Shell_TrayWnd")
        if not taskbar.Exists(0, 0):
            return rects

        def walk(ctrl, depth=0):
            if depth > 12 or len(rects) >= 10:
                return
            try:
                children = ctrl.GetChildren()
            except Exception:
                return
            for child in children:
                if len(rects) >= 10:
                    return
                try:
                    cls = child.ClassName or ""
                    if cls == "Taskbar.TaskListButtonAutomationPeer":
                        r = child.BoundingRectangle
                        w = r.right - r.left
                        h = r.bottom - r.top
                        if w > 10 and h > 10:
                            rects.append((r.left, r.top, r.right, r.bottom))
                    else:
                        walk(child, depth + 1)
                except Exception:
                    continue

        walk(taskbar)
        # 从左到右（垂直任务栏则从上到下）
        rects.sort(key=lambda r: (r[0], r[1]))
        return rects[:10]
    except Exception as e:
        print("查找任务栏失败:", e)
        return []


def keep_above_taskbar(hwnd):
    """尽量把 overlay 顶到任务栏之上（同为 TOPMOST 时靠 z-order）。"""
    try:
        taskbar = win32gui.FindWindow("Shell_TrayWnd", None)
        if taskbar:
            # 插到「任务栏上方那个窗口」之下 = 紧贴任务栏之上
            above = win32gui.GetWindow(taskbar, GW_HWNDPREV)
            if above and above != hwnd:
                win32gui.SetWindowPos(
                    hwnd,
                    above,
                    0, 0, 0, 0,
                    SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW,
                )
                return
    except Exception:
        pass
    win32gui.SetWindowPos(
        hwnd, HWND_TOPMOST, 0, 0, 0, 0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW,
    )


def paint_overlay(hwnd, hdc):
    rects = find_taskbar_app_buttons()
    vx, vy, _, _ = virtual_screen_rect()
    left, top, right, bottom = win32gui.GetClientRect(hwnd)
    brush = win32gui.CreateSolidBrush(COLORKEY)
    win32gui.FillRect(hdc, (left, top, right, bottom), brush)
    win32gui.DeleteObject(brush)

    if not rects:
        return

    font = win32gui.CreateFont(
        16, 0, 0, 0, 700, 0, 0, 0,
        win32con.DEFAULT_CHARSET,
        win32con.OUT_DEFAULT_PRECIS,
        win32con.CLIP_DEFAULT_PRECIS,
        win32con.CLEARTYPE_QUALITY,
        win32con.DEFAULT_PITCH | win32con.FF_SWISS,
        "Segoe UI",
    )
    old_font = win32gui.SelectObject(hdc, font)
    win32gui.SetBkMode(hdc, win32con.TRANSPARENT)
    win32gui.SetTextColor(hdc, TEXT_COLOR)

    for i, (l, t, r, b) in enumerate(rects):
        label = str((i + 1) % 10)
        # UIA 是屏幕坐标，转成 overlay 客户区坐标
        x = l - vx + 2
        y = t - vy + 2
        pad = 1
        tw = 10
        th = 14
        bg = win32gui.CreateSolidBrush(0x202020)
        win32gui.FillRect(hdc, (x - pad, y - pad, x + tw + pad, y + th + pad), bg)
        win32gui.DeleteObject(bg)
        win32gui.TextOut(hdc, x, y, label)

    win32gui.SelectObject(hdc, old_font)
    win32gui.DeleteObject(font)


def wnd_proc(hwnd, msg, wparam, lparam):
    if msg == win32con.WM_PAINT:
        hdc, ps = win32gui.BeginPaint(hwnd)
        try:
            paint_overlay(hwnd, hdc)
        finally:
            win32gui.EndPaint(hwnd, ps)
        return 0
    if msg == win32con.WM_ERASEBKGND:
        return 1
    if msg == win32con.WM_TIMER:
        vx, vy, vw, vh = virtual_screen_rect()
        win32gui.SetWindowPos(
            hwnd, HWND_TOPMOST, vx, vy, vw, vh, SWP_NOACTIVATE | SWP_SHOWWINDOW
        )
        keep_above_taskbar(hwnd)
        win32gui.InvalidateRect(hwnd, None, True)
        return 0
    if msg == win32con.WM_DESTROY:
        win32gui.KillTimer(hwnd, 1)
        win32gui.PostQuitMessage(0)
        return 0
    return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)


def create_overlay():
    global hwnd_overlay
    wc = win32gui.WNDCLASS()
    hinst = win32api.GetModuleHandle(None)
    wc.hInstance = hinst
    wc.lpszClassName = CLASS_NAME
    wc.lpfnWndProc = wnd_proc
    wc.hCursor = win32gui.LoadCursor(0, win32con.IDC_ARROW)
    try:
        win32gui.RegisterClass(wc)
    except win32gui.error:
        pass

    vx, vy, vw, vh = virtual_screen_rect()
    style_ex = (
        WS_EX_LAYERED
        | WS_EX_TRANSPARENT
        | WS_EX_TOPMOST
        | WS_EX_TOOLWINDOW
        | WS_EX_NOACTIVATE
    )
    hwnd_overlay = win32gui.CreateWindowEx(
        style_ex,
        CLASS_NAME,
        "Win11 Taskbar Numbers",
        WS_POPUP,
        vx, vy, vw, vh,
        0, 0, hinst, None,
    )
    win32gui.SetLayeredWindowAttributes(hwnd_overlay, COLORKEY, 0, LWA_COLORKEY)
    win32gui.SetWindowPos(
        hwnd_overlay, HWND_TOPMOST, vx, vy, vw, vh, SWP_NOACTIVATE | SWP_SHOWWINDOW
    )
    keep_above_taskbar(hwnd_overlay)
    win32gui.SetTimer(hwnd_overlay, 1, 700, None)

    n = len(find_taskbar_app_buttons())
    print(f"屏幕 {vw}x{vh}，已找到 {n} 个任务栏应用图标。")
    if n == 0:
        print("没找到图标，请确认任务栏可见；若仍无效，把本窗口内容发给我。")
    else:
        print("序号应已显示在任务栏图标左上角。按 Enter 退出。")
    return hwnd_overlay


def watch_quit():
    try:
        input()
    except EOFError:
        while True:
            time.sleep(3600)
    if hwnd_overlay:
        win32gui.PostMessage(hwnd_overlay, win32con.WM_CLOSE, 0, 0)


def main():
    if sys.platform != "win32":
        print("仅支持 Windows。")
        sys.exit(1)
    threading.Thread(target=watch_quit, daemon=True).start()
    create_overlay()
    win32gui.PumpMessages()


if __name__ == "__main__":
    main()
