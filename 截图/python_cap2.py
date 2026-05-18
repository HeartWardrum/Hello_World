#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Win11 截图标注工具

快捷键:
    Shift + Alt + X   截图

功能:
    Ctrl+C     复制图片
    Ctrl+S     保存桌面
    Ctrl+Z     撤销一步
    ESC        关闭窗口
    滚轮       调整粗细
"""

import io
import os
import threading
from datetime import datetime

import mss
import tkinter as tk

from PIL import Image
from PIL import ImageGrab
from PIL import ImageTk

from pynput import keyboard

import win32clipboard

HOTKEY = "<shift>+<alt>+x"

TOOL_ARROW = "arrow"
TOOL_RECT = "rect"
TOOL_CIRCLE = "circle"
TOOL_BRUSH = "brush"

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
        return Image.frombytes(
            "RGB",
            shot.size,
            shot.bgra,
            "raw",
            "BGRX"
        )


class RegionSelector:
    """ 负责全屏暗化并让用户框选截图区域 """

    def __init__(self, root, image, on_done):
        self.root = root
        self.image = image
        self.on_done = on_done

        self.start_x = None
        self.start_y = None
        self.rect = None

        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)

        sw = image.width
        sh = image.height
        self.win.geometry(f"{sw}x{sh}+0+0")

        self.canvas = tk.Canvas(
            self.win,
            width=sw,
            height=sh,
            cursor="cross",
            highlightthickness=0
        )
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.photo = ImageTk.PhotoImage(image)
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.photo)

        self.canvas.create_text(
            sw // 2,
            35,
            text="拖动鼠标选择截图区域    ESC取消",
            fill="#ff3b30",
            font=("微软雅黑", 16, "bold")
        )

        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.win.bind("<Escape>", lambda e: self.cancel())

    def on_press(self, event):
        self.start_x = event.x
        self.start_y = event.y
        self.rect = self.canvas.create_rectangle(
            self.start_x, self.start_y, self.start_x, self.start_y,
            outline="red", width=2
        )

    def on_drag(self, event):
        if self.rect:
            self.canvas.coords(
                self.rect,
                self.start_x, self.start_y,
                event.x, event.y
            )

    def on_release(self, event):
        end_x = event.x
        end_y = event.y

        x1 = min(self.start_x, end_x)
        y1 = min(self.start_y, end_y)
        x2 = max(self.start_x, end_x)
        y2 = max(self.start_y, end_y)

        self.win.destroy()

        if x2 - x1 > 5 and y2 - y1 > 5:
            cropped = self.image.crop((x1, y1, x2, y2))
            self.on_done(cropped)
        else:
            self.on_done(None)

    def cancel(self):
        self.win.destroy()
        self.on_done(None)


class AnnotationWindow:
    """ 负责展示裁剪后的图片并提供标注工具 """

    def __init__(self, root, image):
        self.root = root
        self.image = image

        self.tool = TOOL_BRUSH
        self.color = COLORS[0]
        self.draw_size = 4

        self.start_x = None
        self.start_y = None
        self.last_x = None
        self.last_y = None

        self.current_item = None
        self.current_brush_items = []
        self.undo_stack = []
        self.topmost = True

        root.title("截图标注")
        root.attributes("-topmost", True)
        root.configure(bg="#2c3e50")

        # ====================
        # 工具栏
        # ====================
        toolbar = tk.Frame(root, bg="#2c3e50", height=42)
        toolbar.pack(side=tk.TOP, fill=tk.X)
        toolbar.pack_propagate(False)

        tk.Label(
            toolbar, text="颜色", bg="#2c3e50", fg="white", font=("微软雅黑", 10)
        ).pack(side=tk.LEFT, padx=(6, 4))

        for c in COLORS:
            box = tk.Frame(
                toolbar, bg=c, width=22, height=22,
                highlightbackground="#666", highlightthickness=1
            )
            box.pack(side=tk.LEFT, padx=2)
            box.pack_propagate(False)
            box.bind("<Button-1>", lambda e, col=c: self.set_color(col))

        self.tool_buttons = {}
        tools = [
            (TOOL_ARROW, "箭头"),
            (TOOL_RECT, "矩形"),
            (TOOL_CIRCLE, "圆形"),
            (TOOL_BRUSH, "画笔")
        ]

        for name, label in tools:
            btn = tk.Button(
                toolbar, text=label, bg="#34495e", fg="white",
                relief=tk.FLAT, padx=8, pady=3,
                command=lambda t=name: self.set_tool(t)
            )
            btn.pack(side=tk.LEFT, padx=2)
            self.tool_buttons[name] = btn

        self.refresh_tool_buttons()

        tk.Label(toolbar, text="粗细", bg="#2c3e50", fg="white").pack(side=tk.LEFT, padx=(12, 4))
        self.size_label = tk.Label(toolbar, text=str(self.draw_size), bg="#34495e", fg="white", width=3)
        self.size_label.pack(side=tk.LEFT)

        tk.Button(toolbar, text="撤销", bg="#d35400", fg="white", relief=tk.FLAT, command=self.undo).pack(side=tk.LEFT,
                                                                                                          padx=(12, 2))
        tk.Button(toolbar, text="清除", bg="#c0392b", fg="white", relief=tk.FLAT, command=self.clear).pack(side=tk.LEFT,
                                                                                                           padx=2)

        self.top_btn = tk.Button(toolbar, text="取消置顶", bg="#8e44ad", fg="white", relief=tk.FLAT,
                                 command=self.toggle_topmost)
        self.top_btn.pack(side=tk.LEFT, padx=2)

        # ====================
        # 图片区域
        # ====================
        self.photo = ImageTk.PhotoImage(image)
        canvas_frame = tk.Frame(root, bg="#222")
        canvas_frame.pack(fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(
            canvas_frame, width=image.width, height=image.height,
            bd=0, highlightthickness=0, bg="#111"
        )
        self.canvas.pack(padx=1, pady=1)
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.photo)

        # ====================
        # 自适应窗口大小
        # ====================
        min_w, min_h = 900, 120
        win_w = max(min_w, image.width + 4)
        win_h = max(min_h, image.height + 46)
        root.geometry(f"{win_w}x{win_h}")

        # ====================
        # 事件绑定
        # ====================
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)

        # 修复：将滚轮事件直接绑定在整个窗口上，解决焦点丢失导致失效的问题
        root.bind("<MouseWheel>", self.on_scroll)

        root.bind("<Control-z>", lambda e: self.undo())
        root.bind("<Control-c>", lambda e: self.copy())
        root.bind("<Control-s>", lambda e: self.save())
        root.bind("<Escape>", lambda e: root.destroy())

    def set_color(self, color):
        self.color = color

    def set_tool(self, tool):
        self.tool = tool
        self.refresh_tool_buttons()

    def refresh_tool_buttons(self):
        for name, btn in self.tool_buttons.items():
            if name == self.tool:
                btn.configure(bg="#1abc9c")
            else:
                btn.configure(bg="#34495e")

    def on_scroll(self, event):
        if event.delta > 0:
            self.draw_size += 1
        else:
            self.draw_size -= 1
        self.draw_size = max(1, min(30, self.draw_size))
        self.size_label.config(text=str(self.draw_size))

    def undo(self):
        if not self.undo_stack:
            return
        items = self.undo_stack.pop()
        for item in items:
            self.canvas.delete(item)

    def clear(self):
        while self.undo_stack:
            items = self.undo_stack.pop()
            for item in items:
                self.canvas.delete(item)

    def toggle_topmost(self):
        self.topmost = not self.topmost
        self.root.attributes("-topmost", self.topmost)
        self.top_btn.config(text="取消置顶" if self.topmost else "窗口置顶")

    def on_press(self, event):
        self.start_x = event.x
        self.start_y = event.y

        if self.tool == TOOL_BRUSH:
            self.current_brush_items = []
            self.last_x = event.x
            self.last_y = event.y
        else:
            self.current_item = self.create_shape(event.x, event.y)

    def create_shape(self, x, y):
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

    def on_drag(self, event):
        if self.tool == TOOL_BRUSH:
            item = self.canvas.create_line(
                self.last_x, self.last_y, event.x, event.y,
                fill=self.color, width=self.draw_size,
                capstyle=tk.ROUND, joinstyle=tk.ROUND
            )
            self.current_brush_items.append(item)
            self.last_x = event.x
            self.last_y = event.y
        else:
            if self.current_item:
                self.canvas.coords(
                    self.current_item, self.start_x, self.start_y, event.x, event.y
                )

    def on_release(self, event):
        if self.tool == TOOL_BRUSH:
            if self.current_brush_items:
                self.undo_stack.append(self.current_brush_items)
        else:
            if self.current_item:
                self.undo_stack.append([self.current_item])
                self.current_item = None

    def get_image(self):
        self.root.update()
        x = self.root.winfo_rootx() + self.canvas.winfo_x()
        y = self.root.winfo_rooty() + self.canvas.winfo_y()
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        return ImageGrab.grab(bbox=(x, y, x + w, y + h))

    def copy(self):
        try:
            img = self.get_image()
            output = io.BytesIO()
            img.convert("RGB").save(output, "BMP")
            data = output.getvalue()[14:]
            output.close()

            win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(win32clipboard.CF_DIB, data)
            finally:
                win32clipboard.CloseClipboard()
            self.root.title("已复制到剪切板")
        except Exception as e:
            self.root.title(f"复制失败: {e}")

    def save(self):
        try:
            img = self.get_image()
            desktop = os.path.join(os.path.expanduser("~"), "Desktop")
            name = datetime.now().strftime("截图_%Y-%m-%d_%H-%M-%S.png")
            path = os.path.join(desktop, name)
            img.save(path)
            self.root.title(f"已保存 {name}")
        except Exception as e:
            self.root.title(f"保存失败: {e}")


def open_annotation(root, img):
    win = tk.Toplevel(root)
    AnnotationWindow(win, img)


def start_capture(root):
    try:
        # 修复：删除了这里的 root.deiconify()，让主窗口继续在后台完美隐身
        full_img = capture_screen()

        def on_done(cropped):
            if cropped is not None:
                open_annotation(root, cropped)

        RegionSelector(root, full_img, on_done)
    except Exception as e:
        print("截图失败:", e)


def main():
    root = tk.Tk()
    root.withdraw()

    print("Win11截图工具已启动")
    print("快捷键: Shift+Alt+X")

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