#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Win11 截图标注工具 (2026 UI 美化修正版)

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

TOOL_ARROW = "arrow"
TOOL_RECT = "rect"
TOOL_CIRCLE = "circle"
TOOL_BRUSH = "brush"

# 2026 现代莫兰迪/流体色系：高级低饱和度
COLORS = [
    "#FF5E5B",  # 珊瑚红
    "#2E86AB",  # 静态蓝
    "#20BF55",  # 薄荷绿
    "#F6AE2D",  # 柔和金
    "#A14DA0",  # 丁香紫
    "#2B2D42"  # 深空灰
]

# 现代极简风格主题配置
THEME = {
    "bg_main": "#F8F9FA",  # 浅色画布背景
    "bg_toolbar": "#FFFFFF",  # 纯白悬浮工具栏
    "text_main": "#2B2D42",  # 主文字颜色
    "accent": "#4A90E2",  # 激活态蓝色
    "accent_hover": "#357ABD",  # 悬停态蓝色
    "border": "#E5E5E5",  # 细腻边框色
    "font": ("Segoe UI", 10),
    "font_bold": ("Segoe UI", 10, "bold")
}


def capture_screen():
    with mss.MSS() as sct:
        monitor = sct.monitors[0]
        shot = sct.grab(monitor)
        return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")


def get_primary_monitor():
    """返回主显示器 (left, top, width, height)"""
    with mss.MSS() as sct:
        m = sct.monitors[1]
        return m["left"], m["top"], m["width"], m["height"]


class RegionSelector:
    """全屏暗化并让用户框选截图区域"""

    def __init__(self, root, image, on_done):
        self.root = root
        self.image = image
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
            image.width // 2, 40,
            text="✦ 拖动鼠标选择区域  ·  右键取消 ✦",
            fill="#FFFFFF", font=("Segoe UI", 14, "bold")
        )

        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.win.bind("<Button-3>", lambda e: self.cancel())

    def on_press(self, event):
        self.start_x, self.start_y = event.x, event.y
        self.rect = self.canvas.create_rectangle(
            event.x, event.y, event.x, event.y,
            outline="#007AFF", width=2
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

    def __init__(self, parent, message, duration=1500, bg_color="#2B2D42"):
        self.toast = tk.Toplevel(parent)
        self.toast.overrideredirect(True)
        self.toast.attributes("-topmost", True)

        frame = tk.Frame(self.toast, bg=bg_color, bd=0, highlightthickness=0)
        frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(
            frame, text=message, bg=bg_color, fg="white",
            font=("Segoe UI", 11, "bold"), padx=18, pady=8
        ).pack()

        self.toast.update_idletasks()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        tw, th = self.toast.winfo_width(), self.toast.winfo_height()

        self.toast.geometry(f"+{px + (pw - tw) // 2}+{py + ph - th - 30}")

        self.toast.attributes("-alpha", 0.0)
        self._fade_in()
        self.toast.after(duration, self._fade_out)

    def _fade_in(self, alpha=0.0):
        if alpha < 0.95:
            self.toast.attributes("-alpha", min(alpha + 0.15, 0.95))
            self.toast.after(15, lambda: self._fade_in(alpha + 0.15))

    def _fade_out(self, alpha=0.95):
        if alpha > 0.0:
            self.toast.attributes("-alpha", max(alpha - 0.15, 0.0))
            self.toast.after(15, lambda: self._fade_out(alpha - 0.15))
        else:
            self.toast.destroy()


class AnnotationWindow:
    """展示裁剪后的图片并提供标注工具"""

    def __init__(self, root, image):
        self.root = root
        self.original_image = image
        self.image = image.copy()

        self.tool = None
        self.color = COLORS[0]
        self.draw_size = 4
        self.topmost = True

        self.start_x = self.start_y = None
        self.last_x = self.last_y = None
        self.current_item = None
        self.current_brush_items = []
        self.undo_stack = []
        self.annotations = []

        self._drag_ox = self._drag_oy = 0
        self._press_rx = self._press_ry = 0

        # ====================
        # 窗口样式基础
        # ====================
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.configure(bg=THEME["bg_main"])

        # ====================
        # 工具栏
        # ====================
        toolbar = tk.Frame(root, bg=THEME["bg_toolbar"], height=46,
                           bd=0, highlightthickness=1, highlightbackground=THEME["border"])
        toolbar.pack(side=tk.TOP, fill=tk.X, padx=0, pady=0)
        toolbar.pack_propagate(False)

        drag_handle = tk.Label(toolbar, text=" ☰ ", bg=THEME["bg_toolbar"], fg="#A0A0A0", font=THEME["font"])
        drag_handle.pack(side=tk.LEFT, padx=(8, 2))
        drag_handle.bind("<ButtonPress-1>", self._tb_press)
        drag_handle.bind("<B1-Motion>", self._tb_drag)
        toolbar.bind("<ButtonPress-1>", self._tb_press)
        toolbar.bind("<B1-Motion>", self._tb_drag)

        for c in COLORS:
            box_container = tk.Frame(toolbar, bg=THEME["bg_toolbar"], width=26, height=26)
            box_container.pack(side=tk.LEFT, padx=3)
            box_container.pack_propagate(False)

            box = tk.Frame(box_container, bg=c, bd=0, cursor="hand2")
            box.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

            if not hasattr(self, 'color_boxes'): self.color_boxes = {}
            self.color_boxes[c] = box_container

            box.bind("<Button-1>", lambda e, col=c: self.set_color(col))

        self.create_sep(toolbar)

        self.tool_buttons = {}
        tool_configs = [
            (TOOL_BRUSH, " ✎  画笔 "),
            (TOOL_ARROW, " ↗  箭头 "),
            (TOOL_RECT, " ▱  矩形 "),
            (TOOL_CIRCLE, " ◯  圆形 ")
        ]

        for name, label in tool_configs:
            # 修复：将 -padding 改为原生 tkinter 的 padx 和 pady
            btn = tk.Button(
                toolbar, text=label, bg=THEME["bg_toolbar"], fg=THEME["text_main"],
                font=THEME["font_bold"], relief=tk.FLAT, bd=0, cursor="hand2",
                padx=8, pady=4,
                activebackground=THEME["border"], activeforeground=THEME["text_main"]
            )
            btn.pack(side=tk.LEFT, padx=2)
            btn.configure(command=lambda t=name: self.toggle_tool(t))

            btn.bind("<Enter>", lambda e, b=btn, n=name: self._on_btn_hover(b, n, True))
            btn.bind("<Leave>", lambda e, b=btn, n=name: self._on_btn_hover(b, n, False))

            self.tool_buttons[name] = btn

        self.create_sep(toolbar)

        tk.Label(toolbar, text="粗细", bg=THEME["bg_toolbar"], fg="#777777", font=THEME["font"]).pack(side=tk.LEFT,
                                                                                                      padx=(4, 4))
        self.size_label = tk.Label(toolbar, text=str(self.draw_size), bg=THEME["bg_main"], fg=THEME["text_main"],
                                   font=THEME["font_bold"], width=3, height=1, bd=0)
        self.size_label.pack(side=tk.LEFT, padx=2)

        self.top_btn = tk.Button(toolbar, text=" 固 定 ", bg=THEME["bg_toolbar"], fg="#8E44AD",
                                 font=THEME["font_bold"], relief=tk.FLAT, bd=0, cursor="hand2", padx=6, pady=4)
        self.top_btn.pack(side=tk.RIGHT, padx=4)
        self.top_btn.configure(command=self.toggle_topmost)

        btn_clear = tk.Button(toolbar, text=" 清空 ", bg=THEME["bg_toolbar"], fg="#E74C3C",
                              font=THEME["font_bold"], relief=tk.FLAT, bd=0, cursor="hand2", padx=6, pady=4)
        btn_clear.pack(side=tk.RIGHT, padx=2)
        btn_clear.configure(command=self.clear)

        btn_undo = tk.Button(toolbar, text=" 撤销 ", bg=THEME["bg_toolbar"], fg="#D35400",
                             font=THEME["font_bold"], relief=tk.FLAT, bd=0, cursor="hand2", padx=6, pady=4)
        btn_undo.pack(side=tk.RIGHT, padx=2)
        btn_undo.configure(command=self.undo)

        self.refresh_color_selector()

        # ====================
        # 画布区域
        # ====================
        self.photo = ImageTk.PhotoImage(self.image)
        canvas_frame = tk.Frame(root, bg=THEME["bg_main"])
        canvas_frame.pack(fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(
            canvas_frame, width=self.image.width, height=self.image.height,
            bd=0, highlightthickness=0, bg=THEME["bg_main"]
        )
        self.canvas.pack(padx=0, pady=0)
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.photo)

        # ====================
        # 居中到主屏
        # ====================
        min_w = 720
        win_w = max(min_w, self.image.width)
        win_h = self.image.height + 46
        ml, mt, mw, mh = get_primary_monitor()
        sx = ml + (mw - win_w) // 2
        sy = mt + (mh - win_h) // 2
        root.geometry(f"{win_w}x{win_h}+{sx}+{sy}")

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

        root.lift()
        root.focus_force()
        self.canvas.focus_set()

    def create_sep(self, parent):
        sep = tk.Frame(parent, bg=THEME["border"], width=1, height=20)
        sep.pack(side=tk.LEFT, padx=8)

    def _on_btn_hover(self, btn, name, is_enter):
        if self.tool == name:
            return
        if is_enter:
            btn.configure(bg=THEME["border"])
        else:
            btn.configure(bg=THEME["bg_toolbar"])

    # ──────────────────────────────────────────
    # 工具栏拖窗
    # ──────────────────────────────────────────
    def _tb_press(self, event):
        self._drag_ox = self.root.winfo_x()
        self._drag_oy = self.root.winfo_y()
        self._press_rx = event.x_root
        self._press_ry = event.y_root

    def _tb_drag(self, event):
        x = self._drag_ox + (event.x_root - self._press_rx)
        y = self._drag_oy + (event.y_root - self._press_ry)
        self.root.geometry(f"+{x}+{y}")

    # ──────────────────────────────────────────
    # 画布左键
    # ──────────────────────────────────────────
    def on_press(self, event):
        self._drag_ox = self.root.winfo_x()
        self._drag_oy = self.root.winfo_y()
        self._press_rx = event.x_root
        self._press_ry = event.y_root

        if self.tool is None:
            return

        self.start_x, self.start_y = event.x, event.y
        if self.tool == TOOL_BRUSH:
            self.current_brush_items = []
            self.last_x, self.last_y = event.x, event.y
        else:
            self.current_item = self._create_shape(event.x, event.y)

    def on_drag(self, event):
        if self.tool is None:
            x = self._drag_ox + (event.x_root - self._press_rx)
            y = self._drag_oy + (event.y_root - self._press_ry)
            self.root.geometry(f"+{x}+{y}")
            return

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
    # 工具切换
    # ──────────────────────────────────────────
    def toggle_tool(self, tool):
        if self.tool == tool:
            self.tool = None
        else:
            self.tool = tool
        self._refresh_tool_buttons()

    def _refresh_tool_buttons(self):
        for name, btn in self.tool_buttons.items():
            if name == self.tool:
                btn.configure(bg=THEME["accent"], fg="white")
            else:
                btn.configure(bg=THEME["bg_toolbar"], fg=THEME["text_main"])

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
        self.refresh_color_selector()

    def refresh_color_selector(self):
        for c, box_container in self.color_boxes.items():
            if c == self.color:
                box_container.configure(highlightbackground=THEME["accent"], highlightthickness=1.5)
            else:
                box_container.configure(highlightbackground=THEME["bg_toolbar"], highlightthickness=0)

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
        self.top_btn.config(text=" 已固定 " if self.topmost else " 固 定 ",
                            fg="#8E44AD" if self.topmost else "#A0A0A0")

    def get_image(self):
        result = self.original_image.copy()
        draw = ImageDraw.Draw(result)

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
        arrow_len = min(12, length / 2)
        angle = math.atan2(dy, dx)
        spread = math.radians(30)
        pts = [end]
        for a in (angle + math.pi - spread, angle + math.pi + spread):
            pts.append((end[0] + arrow_len * math.cos(a),
                        end[1] + arrow_len * math.sin(a)))
        draw.polygon(pts, fill=color)

    def show_toast(self, message, success=True):
        bg = "#2B2D42" if success else "#E74C3C"
        ToastNotification(self.root, message, duration=1500, bg_color=bg)

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
            self.show_toast("✦ 已成功复制到剪贴板")
        except Exception as e:
            self.show_toast(f"✕ 复制失败: {e}", success=False)

    def save(self):
        try:
            desktop = os.path.join(os.path.expanduser("~"), "Desktop")
            name = datetime.now().strftime("Screenshot_%Y%m%d_%H%M%S.png")
            self.get_image().save(os.path.join(desktop, name))
            self.show_toast(f"✦ 已保存至桌面: {name}")
        except Exception as e:
            self.show_toast(f"✕ 保存失败: {e}", success=False)


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

    print("====================================")
    print("  Win11 极简截图工具已完美激活")
    print("  快捷键: Ctrl + Shift + Alt + X")
    print("====================================")

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