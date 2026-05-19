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
    双击图片   关闭窗口
    拖动工具栏 移动窗口
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
from PIL import ImageDraw

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
            text="拖动鼠标选择截图区域    右键点击取消",
            fill="#ff3b30",
            font=("微软雅黑", 16, "bold")
        )

        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.win.bind("<Button-3>", lambda e: self.cancel())

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


class ToastNotification:
    """ 自动消失的提示框 """

    def __init__(self, parent, message, duration=2000, bg_color="#2ecc71"):
        self.parent = parent
        self.message = message
        self.duration = duration
        self.bg_color = bg_color

        # 创建提示窗口
        self.toast = tk.Toplevel(parent)
        self.toast.overrideredirect(True)
        self.toast.attributes("-topmost", True)

        # 设置样式
        frame = tk.Frame(
            self.toast,
            bg=self.bg_color,
            bd=0,
            highlightthickness=0
        )
        frame.pack(fill=tk.BOTH, expand=True)

        label = tk.Label(
            frame,
            text=self.message,
            bg=self.bg_color,
            fg="white",
            font=("微软雅黑", 12, "bold"),
            padx=20,
            pady=10
        )
        label.pack()

        # 计算位置：在父窗口中央显示
        self.toast.update_idletasks()

        parent_x = parent.winfo_rootx()
        parent_y = parent.winfo_rooty()
        parent_width = parent.winfo_width()
        parent_height = parent.winfo_height()

        toast_width = self.toast.winfo_width()
        toast_height = self.toast.winfo_height()

        x = parent_x + (parent_width - toast_width) // 2
        y = parent_y + (parent_height - toast_height) // 2

        self.toast.geometry(f"+{x}+{y}")

        # 淡入效果
        self.toast.attributes("-alpha", 0.0)
        self.fade_in()

        # 定时自动关闭
        self.toast.after(self.duration, self.fade_out)

    def fade_in(self, alpha=0.0):
        """淡入动画"""
        if alpha < 1.0:
            alpha += 0.1
            self.toast.attributes("-alpha", alpha)
            self.toast.after(20, lambda: self.fade_in(alpha))
        else:
            self.toast.attributes("-alpha", 1.0)

    def fade_out(self, alpha=1.0):
        """淡出动画"""
        if alpha > 0.0:
            alpha -= 0.1
            self.toast.attributes("-alpha", alpha)
            self.toast.after(20, lambda: self.fade_out(alpha))
        else:
            self.toast.destroy()


class AnnotationWindow:
    """ 负责展示裁剪后的图片并提供标注工具 """

    def __init__(self, root, image):
        self.root = root
        self.original_image = image  # 保存原始图片
        self.image = image.copy()  # 用于显示的图片副本

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

        # 存储所有标注信息
        self.annotations = []  # 每个元素: (type, coords, color, width)

        # 用于无边框窗口拖动的变量
        self.drag_data = {"x": 0, "y": 0}

        # ====================
        # 窗口属性设置
        # ====================
        root.overrideredirect(True)  # 完全去掉边框和标题栏
        root.attributes("-topmost", True)
        root.configure(bg="#2c3e50")

        # ====================
        # 工具栏
        # ====================
        toolbar = tk.Frame(root, bg="#2c3e50", height=42)
        toolbar.pack(side=tk.TOP, fill=tk.X)
        toolbar.pack_propagate(False)

        # 允许通过拖动工具栏来移动无边框窗口
        toolbar.bind("<ButtonPress-1>", self.start_window_move)
        toolbar.bind("<B1-Motion>", self.drag_window_move)

        tk.Label(
            toolbar, text=" 颜色", bg="#2c3e50", fg="white", font=("微软雅黑", 10)
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
        # 自适应窗口大小与居中显示
        # ====================
        min_w, min_h = 900, 120
        win_w = max(min_w, self.image.width + 2)
        win_h = self.image.height + 44

        screen_width = root.winfo_screenwidth()
        screen_height = root.winfo_screenheight()
        start_x = (screen_width - win_w) // 2
        start_y = (screen_height - win_h) // 2
        root.geometry(f"{win_w}x{win_h}+{start_x}+{start_y}")

        # ====================
        # 事件绑定
        # ====================
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<Double-Button-1>", lambda e: root.destroy())

        root.bind("<MouseWheel>", self.on_scroll)
        root.bind("<Control-z>", lambda e: self.undo())
        root.bind("<Control-c>", lambda e: self.copy())
        root.bind("<Control-s>", lambda e: self.save())
        root.bind("<Escape>", lambda e: root.destroy())

        # ====================
        # 核心修改点：强制夺取键盘焦点
        # ====================
        root.lift()  # 确保窗口提到最上层
        root.focus_force()  # 强制让整个窗口获取输入焦点
        self.canvas.focus_set()  # 顺便让画布锁定焦点

    # ====================
    # 无边框窗口拖动实现
    # ====================
    def start_window_move(self, event):
        self.drag_data["x"] = event.x
        self.drag_data["y"] = event.y

    def drag_window_move(self, event):
        deltax = event.x - self.drag_data["x"]
        deltay = event.y - self.drag_data["y"]
        x = self.root.winfo_x() + deltax
        y = self.root.winfo_y() + deltay
        self.root.geometry(f"+{x}+{y}")

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
        # 同时从annotations中移除
        if self.annotations:
            self.annotations.pop()

    def clear(self):
        while self.undo_stack:
            items = self.undo_stack.pop()
            for item in items:
                self.canvas.delete(item)
        self.annotations.clear()

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
                # 记录画笔标注
                self.annotations.append({
                    'type': 'brush',
                    'items': self.current_brush_items,
                    'color': self.color,
                    'width': self.draw_size
                })
        else:
            if self.current_item:
                self.undo_stack.append([self.current_item])
                # 记录形状标注
                coords = self.canvas.coords(self.current_item)
                self.annotations.append({
                    'type': self.tool,
                    'coords': coords,
                    'color': self.color,
                    'width': self.draw_size
                })
                self.current_item = None

    def get_image(self):
        """
        通过PIL重新绘制图片和标注，避免ImageGrab截图黑屏问题
        """
        # 创建原始图片的副本
        result_image = self.original_image.copy()
        draw = ImageDraw.Draw(result_image)

        # 根据annotations重新绘制所有标注
        for annotation in self.annotations:
            if annotation['type'] == 'brush':
                # 画笔标注需要从canvas获取坐标
                for item_id in annotation['items']:
                    try:
                        coords = self.canvas.coords(item_id)
                        if len(coords) == 4:  # line有4个坐标
                            draw.line(
                                [(coords[0], coords[1]), (coords[2], coords[3])],
                                fill=annotation['color'],
                                width=annotation['width']
                            )
                    except:
                        pass

            elif annotation['type'] == 'rect':
                coords = annotation['coords']
                draw.rectangle(
                    coords,
                    outline=annotation['color'],
                    width=annotation['width']
                )

            elif annotation['type'] == 'circle':
                coords = annotation['coords']
                draw.ellipse(
                    coords,
                    outline=annotation['color'],
                    width=annotation['width']
                )

            elif annotation['type'] == 'arrow':
                coords = annotation['coords']
                # 画箭头线
                draw.line(
                    [(coords[0], coords[1]), (coords[2], coords[3])],
                    fill=annotation['color'],
                    width=annotation['width']
                )
                # 画箭头头部
                self._draw_arrow_head(
                    draw,
                    (coords[0], coords[1]),
                    (coords[2], coords[3]),
                    annotation['color'],
                    annotation['width']
                )

        return result_image

    def _draw_arrow_head(self, draw, start, end, color, width):
        """绘制箭头头部"""
        import math

        dx = end[0] - start[0]
        dy = end[1] - start[1]
        length = math.sqrt(dx ** 2 + dy ** 2)

        if length == 0:
            return

        # 箭头大小
        arrow_length = min(12, length / 2)
        arrow_angle = math.radians(30)

        # 计算箭头方向
        angle = math.atan2(dy, dx)

        # 计算箭头两个端点
        angle1 = angle + math.pi - arrow_angle
        angle2 = angle + math.pi + arrow_angle

        x1 = end[0] + arrow_length * math.cos(angle1)
        y1 = end[1] + arrow_length * math.sin(angle1)
        x2 = end[0] + arrow_length * math.cos(angle2)
        y2 = end[1] + arrow_length * math.sin(angle2)

        # 画箭头头部
        draw.polygon(
            [end, (x1, y1), (x2, y2)],
            fill=color
        )

    def show_toast(self, message, success=True):
        """显示提示信息"""
        bg_color = "#2ecc71" if success else "#e74c3c"
        ToastNotification(self.root, message, duration=1500, bg_color=bg_color)

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

            # 显示成功提示
            self.show_toast("✓ 已复制到剪贴板", success=True)

        except Exception as e:
            # 显示失败提示
            self.show_toast(f"✗ 复制失败: {str(e)}", success=False)
            print(f"复制失败: {e}")

    def save(self):
        try:
            img = self.get_image()
            desktop = os.path.join(os.path.expanduser("~"), "Desktop")
            name = datetime.now().strftime("截图_%Y-%m-%d_%H-%M-%S.png")
            path = os.path.join(desktop, name)
            img.save(path)

            # 显示成功提示
            self.show_toast(f"✓ 已保存: {name}", success=True)

        except Exception as e:
            # 显示失败提示
            self.show_toast(f"✗ 保存失败: {str(e)}", success=False)
            print(f"保存失败: {e}")


def open_annotation(root, img):
    win = tk.Toplevel(root)
    AnnotationWindow(win, img)


def start_capture(root):
    try:
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