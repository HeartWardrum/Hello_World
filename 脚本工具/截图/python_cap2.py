#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Win11 截图标注工具 (2026 UI 美化修正版 v5)

快捷键:
    Ctrl + Shift + Alt + X   截图

功能:
    Ctrl+C     复制图片
    Ctrl+S     保存桌面
    Ctrl+Z     撤销一步
    ESC        关闭窗口
    滚轮       调整粗细/字号
    双击图片   关闭窗口
    拖动工具栏 移动窗口
    左键拖图片 拖动窗口（未选工具时）/ 画图（选工具后）
    再次点击工具按钮  取消选中，回到拖窗模式
    文字工具   单击画布放置输入框，Enter 确认，Esc 取消（输入框大号显示，滚轮调最终字号）
    系统托盘   右键可立即截图或退出程序

    优化:
    1. 工具栏独立弹出，自动吸附在图片右下角，不参与图片缩放
    2. 边缘/角落缩放感应区扩大至 16px，更容易点中
    3. 热键先弹出暗色遮罩框选，松手后按区域后台截取，降低内存峰值与主线程阻塞
"""

import gc
import io
import os
import sys
import threading
import math
from datetime import datetime

import mss
import tkinter as tk
import pystray

from PIL import Image
from PIL import ImageTk
from PIL import ImageDraw
from PIL import ImageFont

from pynput import keyboard
import win32clipboard

HOTKEY = "<ctrl>+<shift>+<alt>+x"

TOOL_ARROW = "arrow"
TOOL_RECT = "rect"
TOOL_CIRCLE = "circle"
TOOL_BRUSH = "brush"
TOOL_TEXT = "text"

TEXT_FONT_FAMILY = "Microsoft YaHei"
TEXT_FONT_PATH = os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts", "msyh.ttc")

# 2026 现代莫兰迪/流体色系：高级低饱和度
COLORS = [
    "#FF5E5B",  # 珊瑚红
    "#2E86AB",  # 静态蓝
    "#20BF55",  # 薄荷绿
    "#F6AE2D",  # 柔和金
    "#A14DA0",  # 丁香紫
    "#2B2D42"  # 深空灰
]

MY_FONT = ("Microsoft YaHei", 12)
MY_FONT_BOLD = ("Microsoft YaHei", 12, "bold")

# 现代极简风格主题配置
THEME = {
    "bg_main": "#F8F9FA",
    "bg_toolbar": "#FFFFFF",
    "text_main": "#2B2D42",
    "accent": "#4A90E2",
    "accent_hover": "#357ABD",
    "border": "#E5E5E5",
    "font": MY_FONT,
    "font_bold": MY_FONT_BOLD
}

TOOLBAR_HEIGHT = 52
TOOLBAR_MIN_WIDTH = 480
TEXT_INPUT_MIN_FONT = 16
TEXT_INPUT_WIDTH = 24

# 【修改】大幅增大边缘感应区域（从 8 像素提升至 16 像素），让鼠标极易点中
RESIZE_MARGIN = 16

_mss = None
_virtual_bounds = None
_primary_monitor = None
_capturing = False
_selecting = False
_tray_icon = None


def get_mss():
    global _mss
    if _mss is None:
        _mss = mss.mss()
    return _mss


def _refresh_monitor_cache():
    global _virtual_bounds, _primary_monitor
    sct = get_mss()
    v = sct.monitors[0]
    _virtual_bounds = (v["left"], v["top"], v["width"], v["height"])
    p = sct.monitors[1]
    _primary_monitor = (p["left"], p["top"], p["width"], p["height"])


def get_virtual_screen_bounds():
    if _virtual_bounds is None:
        _refresh_monitor_cache()
    return _virtual_bounds


def get_primary_monitor():
    if _primary_monitor is None:
        _refresh_monitor_cache()
    return _primary_monitor


def capture_screen():
    """整屏截取（备用/调试，热键路径不再使用）"""
    v = get_mss().monitors[0]
    shot = get_mss().grab(v)
    return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")


def capture_region(left, top, width, height):
    shot = get_mss().grab({"left": left, "top": top, "width": width, "height": height})
    return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")


class RegionSelector:
    """全屏暗色遮罩框选，松手后再按区域截取（不预加载整屏图）"""

    def __init__(self, root, screen_bounds, on_done):
        self.root = root
        self.screen_left, self.screen_top, self.screen_w, self.screen_h = screen_bounds
        self.on_done = on_done
        self.start_x = self.start_y = self.rect = None

        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.attributes("-alpha", 0.35)
        self.win.configure(bg="#000000")
        self.win.geometry(
            f"{self.screen_w}x{self.screen_h}+{self.screen_left}+{self.screen_top}"
        )

        self.canvas = tk.Canvas(
            self.win, width=self.screen_w, height=self.screen_h,
            cursor="cross", highlightthickness=0, bg="#000000"
        )
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.canvas.create_text(
            self.screen_w // 2, 40,
            text="✦ 拖动鼠标选择区域  ·  右键取消 ✦",
            fill="#FFFFFF", font=(THEME["font_bold"][0], 14, "bold")
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
        if self.rect and self.start_x is not None and self.start_y is not None:
            self.canvas.coords(self.rect, self.start_x, self.start_y, event.x, event.y)

    def on_release(self, event):
        if self.start_x is None or self.start_y is None or event.x is None or event.y is None:
            self.cancel()
            return

        x1 = min(self.start_x, event.x)
        y1 = min(self.start_y, event.y)
        x2 = max(self.start_x, event.x)
        y2 = max(self.start_y, event.y)

        self.win.destroy()

        w, h = x2 - x1, y2 - y1
        if w > 5 and h > 5:
            abs_left = self.screen_left + x1
            abs_top = self.screen_top + y1
            self.on_done((abs_left, abs_top, w, h))
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
            font=THEME["font_bold"], padx=18, pady=8
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
    """展示裁剪后的图片并提供独立悬浮工具栏"""

    _resize_edge = None
    _resizing = False
    _resize_start_x = _resize_start_y = 0
    _resize_win_x = _resize_win_y = 0
    _resize_win_w = _resize_win_h = 0

    def __init__(self, root, image):
        self.root = root
        self.original_image = image  # 始终保留最原始的分辨率参考
        self.image = image.copy()

        self.tool = None
        self.color = COLORS[0]
        self.draw_size = 4
        self.topmost = True

        self.start_x = self.start_y = None
        self.last_x = self.last_y = None
        self.current_item = None
        self.current_brush_items = []

        # 核心改动：撤销栈与历史坐标完全绑定
        self.undo_stack = []
        self.annotations = []

        self._drag_ox = self._drag_oy = 0
        self._press_rx = self._press_ry = 0

        self._text_entry_win = None
        self._text_entry = None
        self._text_canvas_pos = None
        self._text_orig_pos = None
        self._pil_font_cache = {}

        # ====================
        # 主窗口样式（仅包含图片画布）
        # ====================
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.configure(bg=THEME["bg_main"])

        # ====================
        # 画布区域
        # ====================
        self.photo = ImageTk.PhotoImage(self.image)
        self.canvas = tk.Canvas(
            root, width=self.image.width, height=self.image.height,
            bd=0, highlightthickness=0, bg=THEME["bg_main"]
        )
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.photo)

        # 设置主窗口初始大小与几何位置
        win_w = self.image.width
        win_h = self.image.height
        ml, mt, mw, mh = get_primary_monitor()
        sx = ml + (mw - win_w) // 2
        sy = mt + (mh - win_h) // 2
        root.geometry(f"{win_w}x{win_h}+{sx}+{sy}")

        # ====================
        # 【修改】创建独立的工具栏 Toplevel 窗口
        # ====================
        self.tb_win = tk.Toplevel(root)
        self.tb_win.overrideredirect(True)
        self.tb_win.attributes("-topmost", True)
        self.tb_win.configure(bg=THEME["bg_toolbar"])

        self.toolbar = tk.Frame(self.tb_win, bg=THEME["bg_toolbar"], height=TOOLBAR_HEIGHT,
                           bd=0, highlightthickness=1, highlightbackground=THEME["border"])
        self.toolbar.pack(fill=tk.BOTH, expand=True)
        self.toolbar.pack_propagate(False)

        # 拖拽把手
        drag_handle = tk.Label(self.toolbar, text=" ☰ ", bg=THEME["bg_toolbar"], fg="#A0A0A0", font=THEME["font"])
        drag_handle.pack(side=tk.LEFT, padx=(8, 2))
        drag_handle.bind("<ButtonPress-1>", self._tb_press)
        drag_handle.bind("<B1-Motion>", self._tb_drag)
        self.toolbar.bind("<ButtonPress-1>", self._tb_press)
        self.toolbar.bind("<B1-Motion>", self._tb_drag)

        # 颜色盘
        self.color_boxes = {}
        for c in COLORS:
            box_container = tk.Frame(self.toolbar, bg=THEME["bg_toolbar"], width=26, height=26)
            box_container.pack(side=tk.LEFT, padx=3)
            box_container.pack_propagate(False)

            box = tk.Frame(box_container, bg=c, bd=0, cursor="hand2")
            box.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
            self.color_boxes[c] = box_container
            box.bind("<Button-1>", lambda e, col=c: self.set_color(col))

        self.create_sep(self.toolbar)

        # 工具按钮
        self.tool_buttons = {}
        tool_configs = [
            (TOOL_BRUSH, " ✎ 画笔 "),
            (TOOL_ARROW, " ↗ 箭头 "),
            (TOOL_RECT, " ▱ 矩形 "),
            (TOOL_CIRCLE, " ◯ 圆形 "),
            (TOOL_TEXT, " T 文字 "),
        ]

        for name, label in tool_configs:
            btn = tk.Button(
                self.toolbar, text=label, bg=THEME["bg_toolbar"], fg=THEME["text_main"],
                font=THEME["font_bold"], relief=tk.FLAT, bd=0, cursor="hand2",
                padx=10, pady=6,
                activebackground=THEME["border"], activeforeground=THEME["text_main"]
            )
            btn.pack(side=tk.LEFT, padx=2)
            btn.configure(command=lambda t=name: self.toggle_tool(t))
            btn.bind("<Enter>", lambda e, b=btn, n=name: self._on_btn_hover(b, n, True))
            btn.bind("<Leave>", lambda e, b=btn, n=name: self._on_btn_hover(b, n, False))
            self.tool_buttons[name] = btn

        self.create_sep(self.toolbar)

        self.size_title_label = tk.Label(
            self.toolbar, text="粗细", bg=THEME["bg_toolbar"], fg="#777777", font=THEME["font"]
        )
        self.size_title_label.pack(side=tk.LEFT, padx=(4, 4))
        self.size_label = tk.Label(self.toolbar, text=str(self.draw_size), bg=THEME["bg_main"], fg=THEME["text_main"],
                                   font=THEME["font_bold"], width=3, height=1, bd=0)
        self.size_label.pack(side=tk.LEFT, padx=2)

        self.top_btn = tk.Button(self.toolbar, text=" 固 定 ", bg=THEME["bg_toolbar"], fg="#8E44AD",
                                 font=THEME["font_bold"], relief=tk.FLAT, bd=0, cursor="hand2", padx=10, pady=6)
        self.top_btn.pack(side=tk.RIGHT, padx=4)
        self.top_btn.configure(command=self.toggle_topmost)

        btn_clear = tk.Button(self.toolbar, text=" 清空 ", bg=THEME["bg_toolbar"], fg="#E74C3C",
                              font=THEME["font_bold"], relief=tk.FLAT, bd=0, cursor="hand2", padx=10, pady=6)
        btn_clear.pack(side=tk.RIGHT, padx=2)
        btn_clear.configure(command=self.clear)

        btn_undo = tk.Button(self.toolbar, text=" 撤销 ", bg=THEME["bg_toolbar"], fg="#D35400",
                             font=THEME["font_bold"], relief=tk.FLAT, bd=0, cursor="hand2", padx=10, pady=6)
        btn_undo.pack(side=tk.RIGHT, padx=2)
        btn_undo.configure(command=self.undo)

        self.refresh_color_selector()

        root.update_idletasks()
        self.reposition_toolbar()  # 首次定位右下角

        # ====================
        # 事件绑定与联动
        # ====================
        self.canvas.bind("<Motion>", self._on_canvas_motion)
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<Double-Button-1>", lambda e: self.destroy_all())

        # 主窗口移动或缩放时，联动调整工具栏位置
        root.bind("<Configure>", lambda e: self.reposition_toolbar())

        root.bind("<MouseWheel>", self.on_scroll)
        root.bind("<Control-z>", lambda e: self.undo())
        root.bind("<Control-c>", lambda e: self.copy())
        root.bind("<Control-s>", lambda e: self.save())
        root.bind("<Escape>", lambda e: self.destroy_all())

        root.lift()
        root.focus_force()
        self.canvas.focus_set()

    def destroy_all(self):
        """同时关闭主窗口和悬浮工具栏，并释放图像内存"""
        self._cancel_text_input()
        self.original_image = None
        self.image = None
        self.photo = None
        self.annotations.clear()
        self.undo_stack.clear()
        try:
            self.tb_win.destroy()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass
        gc.collect()

    def _measure_toolbar_size(self):
        self.toolbar.pack_propagate(True)
        self.toolbar.update_idletasks()
        w = max(self.toolbar.winfo_reqwidth() + 16, TOOLBAR_MIN_WIDTH)
        h = TOOLBAR_HEIGHT
        self.toolbar.pack_propagate(False)
        self.toolbar.configure(width=w, height=h)
        return w, h

    def reposition_toolbar(self):
        """动态计算并将工具栏摆放在主窗口的右下角（外部挂靠）"""
        if not self.root.winfo_exists() or not self.tb_win.winfo_exists():
            return
        rx = self.root.winfo_x()
        ry = self.root.winfo_y()
        rw = self.root.winfo_width()
        rh = self.root.winfo_height()

        tw, th = self._measure_toolbar_size()
        tbx = rx + max(0, rw - tw)
        tby = ry + rh + 4

        self.tb_win.geometry(f"{tw}x{th}+{tbx}+{tby}")

    # ──────────────────────────────────────────────
    #  resize 工具方法
    # ──────────────────────────────────────────────

    def _get_edge(self, cx, cy):
        """根据鼠标在 canvas 上的坐标，返回感应到的边名称（支持超大感应区）"""
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        m = RESIZE_MARGIN

        on_left = cx < m
        on_right = cx > w - m
        on_top = cy < m
        on_bottom = cy > h - m

        if on_top and on_left:     return "nw"
        if on_top and on_right:    return "ne"
        if on_bottom and on_left:  return "sw"
        if on_bottom and on_right: return "se"
        if on_top:                 return "n"
        if on_bottom:              return "s"
        if on_left:                return "w"
        if on_right:               return "e"
        return None

    _EDGE_CURSOR = {
        "n": "top_side", "s": "bottom_side",
        "e": "right_side", "w": "left_side",
        "ne": "top_right_corner", "nw": "top_left_corner",
        "se": "bottom_right_corner", "sw": "bottom_left_corner",
    }

    def _on_canvas_motion(self, event):
        if self._resizing:
            return
        edge = self._get_edge(event.x, event.y)
        if edge:
            self.canvas.configure(cursor=self._EDGE_CURSOR[edge])
        elif self.tool == TOOL_TEXT:
            self.canvas.configure(cursor="xterm")
        else:
            self.canvas.configure(cursor="fleur" if self.tool is None else "tcross")
        self._resize_edge = edge

    def _start_resize(self, event):
        self._resizing = True
        self._resize_start_x = event.x_root
        self._resize_start_y = event.y_root
        self._resize_win_x = self.root.winfo_x()
        self._resize_win_y = self.root.winfo_y()
        self._resize_win_w = self.root.winfo_width()
        self._resize_win_h = self.root.winfo_height()

    def _do_resize(self, event):
        dx = event.x_root - self._resize_start_x
        dy = event.y_root - self._resize_start_y

        x, y, w, h = self._resize_win_x, self._resize_win_y, self._resize_win_w, self._resize_win_h
        edge = self._resize_edge

        min_w, min_h = 150, 150  # 移除工具栏驻留限制，图片窗口可以无限缩小

        if "e" in edge: w = max(min_w, self._resize_win_w + dx)
        if "s" in edge: h = max(min_h, self._resize_win_h + dy)
        if "w" in edge:
            new_w = max(min_w, self._resize_win_w - dx)
            x = x + (self._resize_win_w - new_w)
            w = new_w
        if "n" in edge:
            new_h = max(min_h, self._resize_win_h - dy)
            y = y + (self._resize_win_h - new_h)
            h = new_h

        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self._redraw_canvas(w, h)

    def _redraw_canvas(self, new_w, new_h):
        if new_w < 1 or new_h < 1:
            return
        # 【修正控制】始终使用纯净的初始裁剪图作为原件缩放，防止画质劣化
        resized = self.original_image.resize((new_w, new_h), Image.LANCZOS)
        self.photo = ImageTk.PhotoImage(resized)
        self.canvas.config(width=new_w, height=new_h)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.photo)

        self._redraw_annotations(new_w, new_h)

    def _redraw_annotations(self, cw, ch):
        """完美重绘：基于画布历史坐标字典和最原始图像比例映射，解决坐标漂移问题"""
        orig_w, orig_h = self.original_image.width, self.original_image.height
        sx, sy = cw / orig_w, ch / orig_h

        new_undo_map = {}

        for ann in self.annotations:
            if ann['type'] == 'brush':
                new_items = []
                for old_id, orig_c in ann['orig_coords_map'].items():
                    if len(orig_c) == 4:
                        nid = self.canvas.create_line(
                            orig_c[0] * sx, orig_c[1] * sy, orig_c[2] * sx, orig_c[3] * sy,
                            fill=ann['color'], width=max(1, int(ann['width'] * min(sx, sy))),
                            capstyle=tk.ROUND, joinstyle=tk.ROUND
                        )
                        new_undo_map[old_id] = nid
                        new_items.append(nid)
                ann['items'] = new_items
            elif ann['type'] == 'text':
                ox, oy = ann['orig_coords']
                fs = max(8, int(ann['size'] * min(sx, sy)))
                nid = self.canvas.create_text(
                    ox * sx, oy * sy, text=ann['text'], fill=ann['color'],
                    font=(TEXT_FONT_FAMILY, fs), anchor=tk.NW
                )
                old_id = ann.get('_canvas_id')
                if old_id:
                    new_undo_map[old_id] = nid
                ann['_canvas_id'] = nid
            else:
                orig_c = ann['orig_coords']
                if len(orig_c) == 4:
                    nc = [orig_c[0] * sx, orig_c[1] * sy, orig_c[2] * sx, orig_c[3] * sy]
                    lw = max(1, int(ann['width'] * min(sx, sy)))
                    if ann['type'] == 'rect':
                        nid = self.canvas.create_rectangle(*nc, outline=ann['color'], width=lw)
                    elif ann['type'] == 'circle':
                        nid = self.canvas.create_oval(*nc, outline=ann['color'], width=lw)
                    elif ann['type'] == 'arrow':
                        nid = self.canvas.create_line(*nc, fill=ann['color'], width=lw,
                                                      arrow=tk.LAST, arrowshape=(12, 14, 6))
                    else:
                        continue

                    old_id = ann.get('_canvas_id')
                    if old_id:
                        new_undo_map[old_id] = nid
                    ann['_canvas_id'] = nid

        self.undo_stack = [
            [new_undo_map.get(i, i) for i in group]
            for group in self.undo_stack
        ]

    # ──────────────────────────────────────────────
    #  鼠标动作整合
    # ──────────────────────────────────────────────

    def on_press(self, event):
        if self._resize_edge:
            self._start_resize(event)
            return

        self._drag_ox = self.root.winfo_x()
        self._drag_oy = self.root.winfo_y()
        self._press_rx = event.x_root
        self._press_ry = event.y_root

        if self.tool is None:
            return

        if self.tool == TOOL_TEXT:
            return

        self.start_x, self.start_y = event.x, event.y
        if self.tool == TOOL_BRUSH:
            self.current_brush_items = []
            self.last_x, self.last_y = event.x, event.y
            self._current_brush_orig = {}
        else:
            self.current_item = self._create_shape(event.x, event.y)

    def on_drag(self, event):
        if self._resizing:
            self._do_resize(event)
            return

        if self.tool is None:
            x = self._drag_ox + (event.x_root - self._press_rx)
            y = self._drag_oy + (event.y_root - self._press_ry)
            self.root.geometry(f"+{x}+{y}")
            return

        if self.tool == TOOL_TEXT:
            return

        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        orig_w, orig_h = self.original_image.width, self.original_image.height
        sx, sy = orig_w / cw, orig_h / ch

        if self.tool == TOOL_BRUSH:
            item = self.canvas.create_line(
                self.last_x, self.last_y, event.x, event.y,
                fill=self.color, width=self.draw_size,
                capstyle=tk.ROUND, joinstyle=tk.ROUND
            )
            self.current_brush_items.append(item)

            # 离线实时将当前线段映射并存储为原始分辨率坐标，防止漂移
            self._current_brush_orig[item] = (self.last_x * sx, self.last_y * sy, event.x * sx, event.y * sy)
            self.last_x, self.last_y = event.x, event.y
        else:
            if self.current_item:
                self.canvas.coords(self.current_item, self.start_x, self.start_y, event.x, event.y)

    def on_release(self, event):
        if self._resizing:
            self._resizing = False
            return

        if self.tool is None:
            return

        if self.tool == TOOL_TEXT:
            self._start_text_input(event.x, event.y)
            return

        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        orig_w, orig_h = self.original_image.width, self.original_image.height
        sx, sy = orig_w / cw, orig_h / ch

        if self.tool == TOOL_BRUSH:
            if self.current_brush_items:
                self.undo_stack.append(self.current_brush_items)
                self.annotations.append({
                    'type': 'brush',
                    'items': self.current_brush_items,
                    'color': self.color,
                    'width': self.draw_size,
                    'orig_coords_map': self._current_brush_orig
                })
        else:
            if self.current_item:
                c = self.canvas.coords(self.current_item)
                self.undo_stack.append([self.current_item])
                self.annotations.append({
                    'type': self.tool,
                    'orig_coords': [c[0] * sx, c[1] * sy, c[2] * sx, c[3] * sy],  # 保存最真实的分辨率坐标
                    'color': self.color,
                    'width': self.draw_size,
                    '_canvas_id': self.current_item
                })
                self.current_item = None

    # ──────────────────────────────────────────────
    #  工具栏动作与辅助
    # ──────────────────────────────────────────────

    def create_sep(self, parent):
        sep = tk.Frame(parent, bg=THEME["border"], width=1, height=24)
        sep.pack(side=tk.LEFT, padx=8)

    def _on_btn_hover(self, btn, name, is_enter):
        if self.tool == name: return
        btn.configure(bg=THEME["border"] if is_enter else THEME["bg_toolbar"])

    def _tb_press(self, event):
        self._drag_ox_tb = self.tb_win.winfo_x()
        self._drag_oy_tb = self.tb_win.winfo_y()
        self._press_rx_tb = event.x_root
        self._press_ry_tb = event.y_root

    def _tb_drag(self, event):
        """支持手动拖拽工具栏独立移动"""
        x = self._drag_ox_tb + (event.x_root - self._press_rx_tb)
        y = self._drag_oy_tb + (event.y_root - self._press_ry_tb)
        self.tb_win.geometry(f"+{x}+{y}")

    def toggle_tool(self, tool):
        if self.tool == TOOL_TEXT and self._text_entry_win:
            if self._text_entry and self._text_entry.get().strip():
                self._commit_text_input()
            else:
                self._cancel_text_input()
        self.tool = None if self.tool == tool else tool
        if self.tool == TOOL_TEXT and self.draw_size < 12:
            self.draw_size = 12
            self.size_label.config(text=str(self.draw_size))
        self._refresh_tool_buttons()

    def _refresh_tool_buttons(self):
        for name, btn in self.tool_buttons.items():
            if name == self.tool:
                btn.configure(bg=THEME["accent"], fg="white")
            else:
                btn.configure(bg=THEME["bg_toolbar"], fg=THEME["text_main"])
        self.size_title_label.config(text="字号" if self.tool == TOOL_TEXT else "粗细")

    def _start_text_input(self, x, y):
        if self._text_entry_win:
            self._commit_text_input()

        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        orig_w, orig_h = self.original_image.width, self.original_image.height
        sx, sy = orig_w / cw, orig_h / ch
        self._text_canvas_pos = (x, y)
        self._text_orig_pos = (x * sx, y * sy)

        self._text_entry_win = tk.Toplevel(self.root)
        self._text_entry_win.overrideredirect(True)
        self._text_entry_win.attributes("-topmost", True)
        self._text_entry_win.configure(bg=THEME["bg_main"])

        rx = self.root.winfo_rootx() + x
        ry = self.root.winfo_rooty() + y
        self._text_entry_win.geometry(f"+{rx}+{ry}")

        entry_font_size = max(TEXT_INPUT_MIN_FONT, self.draw_size)
        self._text_entry = tk.Entry(
            self._text_entry_win,
            fg=self.color,
            bg="#FFFFFF",
            font=(TEXT_FONT_FAMILY, entry_font_size),
            width=TEXT_INPUT_WIDTH,
            insertwidth=2,
            bd=1,
            relief=tk.SOLID,
            highlightthickness=1,
            highlightcolor=THEME["accent"],
            highlightbackground=THEME["border"],
        )
        self._text_entry.pack(ipady=6, ipadx=4, padx=1, pady=1)
        self._text_entry.bind("<Return>", self._commit_text_input)
        self._text_entry.bind("<Escape>", self._cancel_text_input)
        self._text_entry.bind("<FocusOut>", self._on_text_focus_out)
        self._text_entry.focus_set()

    def _on_text_focus_out(self, event=None):
        self.root.after_idle(self._handle_text_focus_out)

    def _handle_text_focus_out(self):
        if not self._text_entry or not self._text_entry_win:
            return
        try:
            if not self._text_entry_win.winfo_exists():
                return
        except tk.TclError:
            return
        focused = self.root.focus_get()
        if focused == self._text_entry:
            return
        content = self._text_entry.get().strip()
        if content:
            self._commit_text_input()
        else:
            self._cancel_text_input()

    def _commit_text_input(self, event=None):
        if not self._text_entry:
            return

        content = self._text_entry.get().strip()
        x, y = self._text_canvas_pos
        orig_x, orig_y = self._text_orig_pos
        color = self.color
        size = self.draw_size
        self._cancel_text_input()

        if not content:
            return

        item = self.canvas.create_text(
            x, y, text=content, fill=color,
            font=(TEXT_FONT_FAMILY, size), anchor=tk.NW
        )
        self.undo_stack.append([item])
        self.annotations.append({
            'type': 'text',
            'text': content,
            'orig_coords': [orig_x, orig_y],
            'color': color,
            'size': size,
            '_canvas_id': item,
        })

    def _cancel_text_input(self, event=None):
        self._text_entry = None
        self._text_canvas_pos = None
        self._text_orig_pos = None
        if self._text_entry_win:
            try:
                self._text_entry_win.destroy()
            except Exception:
                pass
            self._text_entry_win = None

    def _create_shape(self, x, y):
        if self.tool == TOOL_ARROW:
            return self.canvas.create_line(x, y, x, y, fill=self.color, width=self.draw_size,
                                           arrow=tk.LAST, arrowshape=(12, 14, 6))
        if self.tool == TOOL_RECT:
            return self.canvas.create_rectangle(x, y, x, y, outline=self.color, width=self.draw_size)
        if self.tool == TOOL_CIRCLE:
            return self.canvas.create_oval(x, y, x, y, outline=self.color, width=self.draw_size)

    def set_color(self, color):
        self.color = color
        self.refresh_color_selector()

    def refresh_color_selector(self):
        for c, box_container in self.color_boxes.items():
            if c == self.color:
                box_container.configure(highlightbackground=THEME["accent"], highlightthickness=2)
            else:
                box_container.configure(highlightbackground=THEME["bg_toolbar"], highlightthickness=0)

    def on_scroll(self, event):
        self.draw_size = max(1, min(30, self.draw_size + (1 if event.delta > 0 else -1)))
        self.size_label.config(text=str(self.draw_size))
        if self._text_entry:
            entry_font_size = max(TEXT_INPUT_MIN_FONT, self.draw_size)
            self._text_entry.configure(font=(TEXT_FONT_FAMILY, entry_font_size))

    def undo(self):
        if not self.undo_stack: return
        for item in self.undo_stack.pop():
            self.canvas.delete(item)
        if self.annotations: self.annotations.pop()

    def clear(self):
        self._cancel_text_input()
        while self.undo_stack:
            for item in self.undo_stack.pop():
                self.canvas.delete(item)
        self.annotations.clear()

    def toggle_topmost(self):
        self.topmost = not self.topmost
        self.root.attributes("-topmost", self.topmost)
        self.tb_win.attributes("-topmost", self.topmost)
        self.top_btn.config(text=" 已固定 " if self.topmost else " 固 定 ",
                            fg="#8E44AD" if self.topmost else "#A0A0A0")

    # ──────────────────────────────────────────────
    #  导出叠加（以原始尺寸高精保存）
    # ──────────────────────────────────────────────

    def get_image(self):
        result = self.original_image.copy()
        draw = ImageDraw.Draw(result)

        for ann in self.annotations:
            if ann['type'] == 'brush':
                for item_id, c in ann['orig_coords_map'].items():
                    if len(c) == 4:
                        draw.line([(c[0], c[1]), (c[2], c[3])], fill=ann['color'], width=int(ann['width']))
            elif ann['type'] == 'rect':
                c = ann['orig_coords']
                draw.rectangle([c[0], c[1], c[2], c[3]], outline=ann['color'], width=int(ann['width']))
            elif ann['type'] == 'circle':
                c = ann['orig_coords']
                draw.ellipse([c[0], c[1], c[2], c[3]], outline=ann['color'], width=int(ann['width']))
            elif ann['type'] == 'arrow':
                c = ann['orig_coords']
                lw = int(ann['width'])
                s, e = (c[0], c[1]), (c[2], c[3])
                draw.line([s, e], fill=ann['color'], width=lw)
                self._draw_arrow_head(draw, s, e, ann['color'], lw)
            elif ann['type'] == 'text':
                x, y = ann['orig_coords']
                draw.text(
                    (x, y), ann['text'], fill=ann['color'],
                    font=self._get_pil_font(int(ann['size']))
                )
        return result

    def _get_pil_font(self, size):
        size = max(8, int(size))
        if size not in self._pil_font_cache:
            try:
                self._pil_font_cache[size] = ImageFont.truetype(TEXT_FONT_PATH, size)
            except OSError:
                self._pil_font_cache[size] = ImageFont.load_default()
        return self._pil_font_cache[size]

    def _draw_arrow_head(self, draw, start, end, color, width):
        dx, dy = end[0] - start[0], end[1] - start[1]
        length = math.hypot(dx, dy)
        if length == 0: return
        arrow_len = min(12, length / 2)
        angle = math.atan2(dy, dx)
        spread = math.radians(30)
        pts = [end]
        for a in (angle + math.pi - spread, angle + math.pi + spread):
            pts.append((end[0] + arrow_len * math.cos(a), end[1] + arrow_len * math.sin(a)))
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


def open_annotation(root, img):
    win = tk.Toplevel(root)
    AnnotationWindow(win, img)


def _set_capturing(value):
    global _capturing
    _capturing = value


def _set_selecting(value):
    global _selecting
    _selecting = value


def _open_annotation_safe(root, img):
    global _capturing
    _capturing = False
    if img is not None:
        open_annotation(root, img)


def _on_region_done(root, bbox):
    global _capturing, _selecting
    _set_selecting(False)

    if not bbox:
        return

    _set_capturing(True)
    left, top, width, height = bbox

    def worker():
        try:
            img = capture_region(left, top, width, height)
            root.after(0, lambda: _open_annotation_safe(root, img))
        except Exception as e:
            root.after(0, lambda: print("截图失败:", e))
            root.after(0, lambda: _set_capturing(False))

    threading.Thread(target=worker, daemon=True).start()


def start_capture(root):
    global _capturing, _selecting
    if _capturing or _selecting:
        return

    try:
        _refresh_monitor_cache()
        bounds = get_virtual_screen_bounds()
        _set_selecting(True)
        RegionSelector(root, bounds, lambda bbox: _on_region_done(root, bbox))
    except Exception as e:
        _set_selecting(False)
        print("截图失败:", e)


def _create_tray_image():
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([4, 4, 60, 60], radius=10, fill="#4A90E2")
    try:
        font = ImageFont.truetype(TEXT_FONT_PATH, 32)
    except OSError:
        font = ImageFont.load_default()
    draw.text((32, 32), "S", fill="white", font=font, anchor="mm")
    return img


def _quit_app(root, icon=None, item=None):
    global _tray_icon
    if icon is not None:
        icon.stop()
    elif _tray_icon is not None:
        _tray_icon.stop()
    try:
        root.quit()
        root.destroy()
    except Exception:
        pass
    sys.exit(0)


def setup_tray(root):
    global _tray_icon

    def on_capture(icon, item):
        root.after(0, lambda: start_capture(root))

    menu = pystray.Menu(
        pystray.MenuItem("立即截图", on_capture, default=True),
        pystray.MenuItem("退出", lambda icon, item: _quit_app(root, icon)),
    )
    _tray_icon = pystray.Icon(
        "screenshot_tool",
        _create_tray_image(),
        "截图工具\nCtrl+Shift+Alt+X 截图",
        menu,
    )
    threading.Thread(target=_tray_icon.run, daemon=True).start()


def main():
    root = tk.Tk()
    root.withdraw()

    _refresh_monitor_cache()

    print("====================================")
    print("  Win11 极简截图工具已完美激活")
    print("  快捷键: Ctrl + Shift + Alt + X")
    print("====================================")

    def hotkey_thread():
        with keyboard.GlobalHotKeys({
            HOTKEY: lambda: root.after(0, lambda: start_capture(root))
        }):
            import time
            while True: time.sleep(1)

    threading.Thread(target=hotkey_thread, daemon=True).start()
    setup_tray(root)
    root.mainloop()


if __name__ == "__main__":
    main()