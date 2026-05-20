#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Win11 截图标注工具

快捷键:
    Ctrl + Shift + Alt + X   截图

功能:
    Ctrl+C     复制图片
    Ctrl+S     保存桌面
    Ctrl+Z     撤销一步
    ESC        关闭窗口
    滚轮       调整粗细
    双击图片   关闭窗口
    拖动工具栏 移动窗口
    左键拖图片 拖动窗口（未选工具时）/ 画图（选工具后）
    再次点击工具按钮  取消选中，回到拖窗模式
"""

import io
import os
import threading
from datetime import datetime

import mss
import tkinter as tk

from PIL import Image
from PIL import ImageTk
from PIL import ImageDraw

from pynput import keyboard

import win32clipboard

HOTKEY = "<ctrl>+<shift>+<alt>+x"

TOOL_ARROW  = "arrow"
TOOL_RECT   = "rect"
TOOL_CIRCLE = "circle"
TOOL_BRUSH  = "brush"

COLORS = [
    "#e74c3c",
    "#3498db",
    "#2ecc71",
    "#f1c40f",
    "#9b59b6",
    "#000000"
]


def capture_screen():
    with mss.MSS() as sct:
        monitor = sct.monitors[0]
        shot = sct.grab(monitor)
        return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")


def get_primary_monitor():
    """返回主显示器 (left, top, width, height)"""
    with mss.MSS() as sct:
        m = sct.monitors[1]   # monitors[0] 是所有屏合并区域，[1] 是主屏
        return m["left"], m["top"], m["width"], m["height"]


class RegionSelector:
    """全屏暗化并让用户框选截图区域"""

    def __init__(self, root, image, on_done):
        self.root   = root
        self.image  = image
        self.on_done = on_done
        self.start_x = self.start_y = self.rect = None

        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.geometry(f"{image.width}x{image.height}+0+0")

        self.canvas = tk.Canvas(
            self.win, width=image.width, height=image.height,
            cursor="cross", highlightthickness=0
        )
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.photo = ImageTk.PhotoImage(image)
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.photo)
        self.canvas.create_text(
            image.width // 2, 35,
            text="拖动鼠标选择截图区域    右键点击取消",
            fill="#ff3b30", font=("微软雅黑", 16, "bold")
        )

        self.canvas.bind("<ButtonPress-1>",   self.on_press)
        self.canvas.bind("<B1-Motion>",       self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.win.bind("<Button-3>", lambda e: self.cancel())

    def on_press(self, event):
        self.start_x, self.start_y = event.x, event.y
        self.rect = self.canvas.create_rectangle(
            event.x, event.y, event.x, event.y,
            outline="red", width=2
        )

    def on_drag(self, event):
        if self.rect:
            self.canvas.coords(self.rect, self.start_x, self.start_y, event.x, event.y)

    def on_release(self, event):
        x1 = min(self.start_x, event.x)
        y1 = min(self.start_y, event.y)
        x2 = max(self.start_x, event.x)
        y2 = max(self.start_y, event.y)
        self.win.destroy()
        if x2 - x1 > 5 and y2 - y1 > 5:
            self.on_done(self.image.crop((x1, y1, x2, y2)))
        else:
            self.on_done(None)

    def cancel(self):
        self.win.destroy()
        self.on_done(None)


class ToastNotification:
    """自动消失的提示框"""

    def __init__(self, parent, message, duration=2000, bg_color="#2ecc71"):
        self.toast = tk.Toplevel(parent)
        self.toast.overrideredirect(True)
        self.toast.attributes("-topmost", True)

        frame = tk.Frame(self.toast, bg=bg_color, bd=0, highlightthickness=0)
        frame.pack(fill=tk.BOTH, expand=True)
        tk.Label(
            frame, text=message, bg=bg_color, fg="white",
            font=("微软雅黑", 12, "bold"), padx=20, pady=10
        ).pack()

        self.toast.update_idletasks()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        tw, th = self.toast.winfo_width(), self.toast.winfo_height()
        self.toast.geometry(f"+{px + (pw - tw)//2}+{py + (ph - th)//2}")

        self.toast.attributes("-alpha", 0.0)
        self._fade_in()
        self.toast.after(duration, self._fade_out)

    def _fade_in(self, alpha=0.0):
        if alpha < 1.0:
            self.toast.attributes("-alpha", min(alpha + 0.1, 1.0))
            self.toast.after(20, lambda: self._fade_in(alpha + 0.1))

    def _fade_out(self, alpha=1.0):
        if alpha > 0.0:
            self.toast.attributes("-alpha", max(alpha - 0.1, 0.0))
            self.toast.after(20, lambda: self._fade_out(alpha - 0.1))
        else:
            self.toast.destroy()


class AnnotationWindow:
    """展示裁剪后的图片并提供标注工具"""

    def __init__(self, root, image):
        self.root           = root
        self.original_image = image
        self.image          = image.copy()

        # 默认不选任何工具 → 左键拖窗
        self.tool       = None
        self.color      = COLORS[0]
        self.draw_size  = 4
        self.topmost    = True

        self.start_x = self.start_y = None
        self.last_x  = self.last_y  = None
        self.current_item        = None
        self.current_brush_items = []
        self.undo_stack          = []
        self.annotations         = []

        # 拖窗用（工具栏 & 画布共用逻辑）
        self._drag_ox = self._drag_oy = 0   # 按下时窗口左上角屏幕坐标
        self._press_rx = self._press_ry = 0  # 按下时鼠标在屏幕上的坐标

        # ====================
        # 窗口
        # ====================
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.configure(bg="#2c3e50")

        # ====================
        # 工具栏
        # ====================
        toolbar = tk.Frame(root, bg="#2c3e50", height=42)
        toolbar.pack(side=tk.TOP, fill=tk.X)
        toolbar.pack_propagate(False)

        # 工具栏也可拖窗
        toolbar.bind("<ButtonPress-1>",   self._tb_press)
        toolbar.bind("<B1-Motion>",       self._tb_drag)

        tk.Label(toolbar, text=" 颜色", bg="#2c3e50", fg="white",
                 font=("微软雅黑", 10)).pack(side=tk.LEFT, padx=(6, 4))

        for c in COLORS:
            box = tk.Frame(toolbar, bg=c, width=22, height=22,
                           highlightbackground="#666", highlightthickness=1)
            box.pack(side=tk.LEFT, padx=2)
            box.pack_propagate(False)
            box.bind("<Button-1>", lambda e, col=c: self.set_color(col))

        self.tool_buttons = {}
        for name, label in [(TOOL_ARROW, "箭头"), (TOOL_RECT, "矩形"),
                             (TOOL_CIRCLE, "圆形"), (TOOL_BRUSH, "画笔")]:
            btn = tk.Button(
                toolbar, text=label, bg="#34495e", fg="white",
                relief=tk.FLAT, padx=8, pady=3,
                command=lambda t=name: self.toggle_tool(t)
            )
            btn.pack(side=tk.LEFT, padx=2)
            self.tool_buttons[name] = btn

        tk.Label(toolbar, text="粗细", bg="#2c3e50", fg="white").pack(side=tk.LEFT, padx=(12, 4))
        self.size_label = tk.Label(toolbar, text=str(self.draw_size),
                                   bg="#34495e", fg="white", width=3)
        self.size_label.pack(side=tk.LEFT)

        tk.Button(toolbar, text="撤销", bg="#d35400", fg="white",
                  relief=tk.FLAT, command=self.undo).pack(side=tk.LEFT, padx=(12, 2))
        tk.Button(toolbar, text="清除", bg="#c0392b", fg="white",
                  relief=tk.FLAT, command=self.clear).pack(side=tk.LEFT, padx=2)

        self.top_btn = tk.Button(toolbar, text="取消置顶", bg="#8e44ad", fg="white",
                                 relief=tk.FLAT, command=self.toggle_topmost)
        self.top_btn.pack(side=tk.LEFT, padx=2)

        # ====================
        # 画布
        # ====================
        self.photo = ImageTk.PhotoImage(self.image)
        canvas_frame = tk.Frame(root, bg="#222")
        canvas_frame.pack(fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(
            canvas_frame, width=self.image.width, height=self.image.height,
            bd=0, highlightthickness=0, bg="#111"
        )
        self.canvas.pack(padx=1, pady=1)
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.photo)

        # ====================
        # 居中到主屏
        # ====================
        min_w = 900
        win_w = max(min_w, self.image.width + 2)
        win_h = self.image.height + 44
        ml, mt, mw, mh = get_primary_monitor()
        sx = ml + (mw - win_w) // 2
        sy = mt + (mh - win_h) // 2
        root.geometry(f"{win_w}x{win_h}+{sx}+{sy}")

        # ====================
        # 事件绑定
        # ====================
        self.canvas.bind("<ButtonPress-1>",   self.on_press)
        self.canvas.bind("<B1-Motion>",       self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<Double-Button-1>", lambda e: root.destroy())

        root.bind("<MouseWheel>",  self.on_scroll)
        root.bind("<Control-z>",   lambda e: self.undo())
        root.bind("<Control-c>",   lambda e: self.copy())
        root.bind("<Control-s>",   lambda e: self.save())
        root.bind("<Escape>",      lambda e: root.destroy())

        root.lift()
        root.focus_force()
        self.canvas.focus_set()

    # ──────────────────────────────────────────
    # 工具栏拖窗
    # ──────────────────────────────────────────
    def _tb_press(self, event):
        self._drag_ox  = self.root.winfo_x()
        self._drag_oy  = self.root.winfo_y()
        self._press_rx = event.x_root
        self._press_ry = event.y_root

    def _tb_drag(self, event):
        x = self._drag_ox + (event.x_root - self._press_rx)
        y = self._drag_oy + (event.y_root - self._press_ry)
        self.root.geometry(f"+{x}+{y}")

    # ──────────────────────────────────────────
    # 画布左键：无工具=拖窗，有工具=画图
    # ──────────────────────────────────────────
    def on_press(self, event):
        # 记录按下时窗口位置和鼠标屏幕位置（拖窗备用）
        self._drag_ox  = self.root.winfo_x()
        self._drag_oy  = self.root.winfo_y()
        self._press_rx = event.x_root
        self._press_ry = event.y_root

        if self.tool is None:
            return  # 拖窗模式，什么都不初始化

        # 画图模式
        self.start_x, self.start_y = event.x, event.y
        if self.tool == TOOL_BRUSH:
            self.current_brush_items = []
            self.last_x, self.last_y = event.x, event.y
        else:
            self.current_item = self._create_shape(event.x, event.y)

    def on_drag(self, event):
        if self.tool is None:
            # 拖窗
            x = self._drag_ox + (event.x_root - self._press_rx)
            y = self._drag_oy + (event.y_root - self._press_ry)
            self.root.geometry(f"+{x}+{y}")
            return

        # 画图
        if self.tool == TOOL_BRUSH:
            item = self.canvas.create_line(
                self.last_x, self.last_y, event.x, event.y,
                fill=self.color, width=self.draw_size,
                capstyle=tk.ROUND, joinstyle=tk.ROUND
            )
            self.current_brush_items.append(item)
            self.last_x, self.last_y = event.x, event.y
        else:
            if self.current_item:
                self.canvas.coords(
                    self.current_item,
                    self.start_x, self.start_y, event.x, event.y
                )

    def on_release(self, event):
        if self.tool is None:
            return

        if self.tool == TOOL_BRUSH:
            if self.current_brush_items:
                self.undo_stack.append(self.current_brush_items)
                self.annotations.append({
                    'type': 'brush',
                    'items': self.current_brush_items,
                    'color': self.color,
                    'width': self.draw_size
                })
        else:
            if self.current_item:
                self.undo_stack.append([self.current_item])
                self.annotations.append({
                    'type': self.tool,
                    'coords': self.canvas.coords(self.current_item),
                    'color': self.color,
                    'width': self.draw_size
                })
                self.current_item = None

    # ──────────────────────────────────────────
    # 工具切换（再次点击取消选中）
    # ──────────────────────────────────────────
    def toggle_tool(self, tool):
        if self.tool == tool:
            self.tool = None          # 取消选中 → 回到拖窗模式
        else:
            self.tool = tool
        self._refresh_tool_buttons()

    def _refresh_tool_buttons(self):
        for name, btn in self.tool_buttons.items():
            btn.configure(bg="#1abc9c" if name == self.tool else "#34495e")

    # ──────────────────────────────────────────
    # 辅助
    # ──────────────────────────────────────────
    def _create_shape(self, x, y):
        if self.tool == TOOL_ARROW:
            return self.canvas.create_line(
                x, y, x, y, fill=self.color, width=self.draw_size,
                arrow=tk.LAST, arrowshape=(12, 14, 6)
            )
        if self.tool == TOOL_RECT:
            return self.canvas.create_rectangle(
                x, y, x, y, outline=self.color, width=self.draw_size
            )
        if self.tool == TOOL_CIRCLE:
            return self.canvas.create_oval(
                x, y, x, y, outline=self.color, width=self.draw_size
            )

    def set_color(self, color):
        self.color = color

    def on_scroll(self, event):
        self.draw_size = max(1, min(30, self.draw_size + (1 if event.delta > 0 else -1)))
        self.size_label.config(text=str(self.draw_size))

    def undo(self):
        if not self.undo_stack:
            return
        for item in self.undo_stack.pop():
            self.canvas.delete(item)
        if self.annotations:
            self.annotations.pop()

    def clear(self):
        while self.undo_stack:
            for item in self.undo_stack.pop():
                self.canvas.delete(item)
        self.annotations.clear()

    def toggle_topmost(self):
        self.topmost = not self.topmost
        self.root.attributes("-topmost", self.topmost)
        self.top_btn.config(text="取消置顶" if self.topmost else "窗口置顶")

    def get_image(self):
        result = self.original_image.copy()
        draw   = ImageDraw.Draw(result)

        for ann in self.annotations:
            if ann['type'] == 'brush':
                for item_id in ann['items']:
                    try:
                        c = self.canvas.coords(item_id)
                        if len(c) == 4:
                            draw.line([(c[0], c[1]), (c[2], c[3])],
                                      fill=ann['color'], width=ann['width'])
                    except Exception:
                        pass
            elif ann['type'] == 'rect':
                draw.rectangle(ann['coords'], outline=ann['color'], width=ann['width'])
            elif ann['type'] == 'circle':
                draw.ellipse(ann['coords'], outline=ann['color'], width=ann['width'])
            elif ann['type'] == 'arrow':
                c = ann['coords']
                draw.line([(c[0], c[1]), (c[2], c[3])],
                          fill=ann['color'], width=ann['width'])
                self._draw_arrow_head(draw, (c[0], c[1]), (c[2], c[3]),
                                      ann['color'], ann['width'])
        return result

    def _draw_arrow_head(self, draw, start, end, color, width):
        import math
        dx, dy = end[0] - start[0], end[1] - start[1]
        length = math.hypot(dx, dy)
        if length == 0:
            return
        arrow_len   = min(12, length / 2)
        angle       = math.atan2(dy, dx)
        spread      = math.radians(30)
        pts = [end]
        for a in (angle + math.pi - spread, angle + math.pi + spread):
            pts.append((end[0] + arrow_len * math.cos(a),
                        end[1] + arrow_len * math.sin(a)))
        draw.polygon(pts, fill=color)

    def show_toast(self, message, success=True):
        ToastNotification(self.root, message, duration=1500,
                          bg_color="#2ecc71" if success else "#e74c3c")

    def copy(self):
        try:
            output = io.BytesIO()
            self.get_image().convert("RGB").save(output, "BMP")
            data = output.getvalue()[14:]
            output.close()
            win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(win32clipboard.CF_DIB, data)
            finally:
                win32clipboard.CloseClipboard()
            self.show_toast("✓ 已复制到剪贴板")
        except Exception as e:
            self.show_toast(f"✗ 复制失败: {e}", success=False)

    def save(self):
        try:
            desktop = os.path.join(os.path.expanduser("~"), "Desktop")
            name    = datetime.now().strftime("截图_%Y-%m-%d_%H-%M-%S.png")
            self.get_image().save(os.path.join(desktop, name))
            self.show_toast(f"✓ 已保存: {name}")
        except Exception as e:
            self.show_toast(f"✗ 保存失败: {e}", success=False)


# ──────────────────────────────────────────────────
def open_annotation(root, img):
    win = tk.Toplevel(root)
    AnnotationWindow(win, img)


def start_capture(root):
    try:
        full_img = capture_screen()
        RegionSelector(root, full_img,
                       lambda cropped: cropped and open_annotation(root, cropped))
    except Exception as e:
        print("截图失败:", e)


def main():
    root = tk.Tk()
    root.withdraw()

    print("Win11截图工具已启动")
    print("快捷键: Ctrl+Shift+Alt+X")

    def hotkey_thread():
        with keyboard.GlobalHotKeys({
            HOTKEY: lambda: root.after(0, lambda: start_capture(root))
        }):
            import time
            while True:
                time.sleep(1)

    threading.Thread(target=hotkey_thread, daemon=True).start()
    root.mainloop()


if __name__ == "__main__":
    main()
