import tkinter as tk
from tkinter import messagebox, scrolledtext
import subprocess
import os
import datetime
import threading
import queue


# ============================================================
# 配置
# ============================================================

REPO_PATH = r"D:\文档\github\Hello_World"
FILE_NAME = "脚本工具/传送工具/msg.txt"  # 使用正斜杠避免 Git 路径解析问题

# Windows 隐藏子进程窗口标识
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


# ============================================================
# 配色 —— Typora / 现代编辑器风格
# ============================================================

BG = "#f7f7f5"             # 页面背景
PANEL = "#ffffff"          # 编辑区
BORDER = "#e5e5e2"         # 细边框
TEXT = "#2f3437"           # 主文字
TEXT_SECONDARY = "#8a8f93" # 次要文字
TEXT_LIGHT = "#a7abad"     # 更淡文字

ACCENT = "#4f7cff"         # 主色
ACCENT_HOVER = "#3f6ff0"
ACCENT_PRESS = "#355fd8"

GREEN = "#35a66f"
RED = "#d95c5c"
YELLOW = "#d89b28"

LOG_BG = "#fafafa"

# ------------------------------------------------------------
# 字体调大配置
# ------------------------------------------------------------
FONT_UI = ("微软雅黑", 20)
FONT_SMALL = ("微软雅黑", 18)
FONT_TITLE = ("微软雅黑", 26, "bold")
FONT_EDITOR = ("微软雅黑", 20)
FONT_LOG = ("Consolas", 18)

PLACEHOLDER = "在这里输入要传送的内容…"


# ============================================================
# 全局状态
# ============================================================

ui_queue = queue.Queue()
is_placeholder = True  # 标记当前是否处于占位符状态


# ============================================================
# 工具函数
# ============================================================

def enqueue_ui(func, *args, **kwargs):
    """将 UI 操作放入主线程队列。"""
    ui_queue.put((func, args, kwargs))


def process_ui_queue():
    """主线程定时处理 UI 更新。"""
    try:
        while True:
            func, args, kwargs = ui_queue.get_nowait()
            func(*args, **kwargs)
    except queue.Empty:
        pass

    root.after(50, process_ui_queue)


def log(message, color=None):
    """向日志区域添加日志。"""
    log_box.config(state="normal")

    tag = None
    if color:
        tag = f"color_{color.replace('#', '')}"
        if tag not in log_box.tag_names():
            log_box.tag_config(tag, foreground=color)

    log_box.insert(tk.END, message + "\n", tag)
    log_box.see(tk.END)
    log_box.config(state="disabled")


def set_status(text, color=TEXT_SECONDARY):
    status_label.config(text=text, fg=color)
    status_dot.config(fg=color)


def update_char_count(event=None):
    if is_placeholder:
        char_count_label.config(text="0 字")
        return

    content = text_box.get("1.0", "end-1c")
    count = len(content)

    if count == 0:
        char_count_label.config(text="0 字")
    else:
        char_count_label.config(text=f"{count:,} 字")


def run_git(args):
    """执行 Git 命令并实时读取输出。"""
    command_text = "$ git " + " ".join(args)
    enqueue_ui(log, command_text, TEXT_LIGHT)

    proc = subprocess.Popen(
        ["git"] + args,
        cwd=REPO_PATH,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=CREATE_NO_WINDOW
    )

    if proc.stdout:
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                enqueue_ui(log, "  " + line, TEXT)

    proc.wait()

    if proc.returncode != 0:
        raise subprocess.CalledProcessError(
            proc.returncode,
            ["git"] + args
        )


# ============================================================
# 占位符管理
# ============================================================

def add_placeholder():
    global is_placeholder
    text_box.delete("1.0", tk.END)
    text_box.insert("1.0", PLACEHOLDER)
    text_box.config(fg=TEXT_LIGHT)
    is_placeholder = True
    update_char_count()


def remove_placeholder(event=None):
    global is_placeholder
    if is_placeholder:
        text_box.delete("1.0", tk.END)
        text_box.config(fg=TEXT)
        is_placeholder = False
        update_char_count()


def restore_placeholder(event=None):
    global is_placeholder
    content = text_box.get("1.0", "end-1c").strip()
    if not content:
        add_placeholder()


# ============================================================
# Git 发送线程
# ============================================================

def send_worker(content):
    file_path = os.path.join(REPO_PATH, FILE_NAME.replace("/", os.sep))
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)

        enqueue_ui(log, f"已写入  {file_path}", TEXT_SECONDARY)

        run_git(["add", FILE_NAME])

        # 检查暂存区是否有需要提交的变化
        check_proc = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=REPO_PATH,
            creationflags=CREATE_NO_WINDOW
        )

        # 返回码 0 代表无变更，返回码 1 代表有变更
        if check_proc.returncode == 0:
            enqueue_ui(log, "ℹ 内容与上一次提交一致，无需重复提交", YELLOW)
            enqueue_ui(set_status, "内容未变更", YELLOW)
            return

        run_git(["commit", "-m", f"auto send {now}"])
        run_git(["push"])

        enqueue_ui(log, f"✓ 传送完成  {now}", GREEN)
        enqueue_ui(set_status, "传送完成", GREEN)

    except subprocess.CalledProcessError as e:
        enqueue_ui(log, f"✕ Git 执行失败，返回码：{e.returncode}", RED)
        enqueue_ui(set_status, "Git 执行失败", RED)

    except Exception as e:
        enqueue_ui(log, f"✕ 出错：{e}", RED)
        enqueue_ui(set_status, "传送失败", RED)

    finally:
        enqueue_ui(send_btn.config, state="normal", text="传送", bg=ACCENT)


# ============================================================
# 发送 / 清空
# ============================================================

def send():
    if is_placeholder:
        messagebox.showwarning("提示", "请输入需要传送的内容。")
        text_box.focus_set()
        return

    content = text_box.get("1.0", "end-1c").strip()

    if not content:
        messagebox.showwarning("提示", "请输入需要传送的内容。")
        text_box.focus_set()
        return

    # 禁用按钮
    send_btn.config(state="disabled", text="传送中…", bg="#b8c3df")
    set_status("正在传送…", YELLOW)

    # 日志分隔
    log("", None)
    log("────────────────────────────────────────", BORDER)

    # 启动后台线程
    thread = threading.Thread(
        target=send_worker,
        args=(content,),
        daemon=True
    )
    thread.start()


def clear_text():
    if is_placeholder or not text_box.get("1.0", "end-1c").strip():
        return

    result = messagebox.askyesno("清空内容", "确定要清空当前内容吗？")
    if result:
        add_placeholder()
        text_box.focus_set()


def on_ctrl_enter(event=None):
    send()
    return "break"

def center_window(window, width, height):
    window.update_idletasks()  # 先让窗口完成布局，拿到真实尺寸
    screen_w = window.winfo_screenwidth()
    screen_h = window.winfo_screenheight()
    x = (screen_w - width) // 2
    y = (screen_h - height) // 2
    window.geometry(f"{width}x{height}+{x}+{y}")


# ============================================================
# 主窗口
# ============================================================

root = tk.Tk()
root.title("传送工具")
root.minsize(700, 600)
root.configure(bg=BG)

center_window(root, 900, 720)

try:
    root.tk.call("tk", "scaling", 1.0)
except Exception:
    pass


# ============================================================
# 顶部 UI
# ============================================================

header = tk.Frame(root, bg=BG)
header.pack(fill="x", padx=36, pady=(24, 10))

title_frame = tk.Frame(header, bg=BG)
title_frame.pack(side="left")

tk.Label(title_frame, text="传送工具", bg=BG, fg=TEXT, font=FONT_TITLE).pack(anchor="w")
tk.Label(title_frame, text="将内容提交到 GitHub", bg=BG, fg=TEXT_SECONDARY, font=FONT_SMALL).pack(anchor="w", pady=(3, 0))

shortcut_label = tk.Label(header, text="Ctrl + Enter 传送", bg=BG, fg=TEXT_LIGHT, font=FONT_SMALL)
shortcut_label.pack(side="right", pady=(9, 0))


# ============================================================
# 编辑区域（缩减高度，不占满全屏）
# ============================================================

editor_wrapper = tk.Frame(root, bg=PANEL, highlightthickness=1, highlightbackground=BORDER)
editor_wrapper.pack(fill="x", expand=False, padx=36, pady=(8, 12))  # expand=False 避免过度占据垂直空间

editor_toolbar = tk.Frame(editor_wrapper, bg=PANEL, height=38)
editor_toolbar.pack(fill="x")
editor_toolbar.pack_propagate(False)

tk.Label(editor_toolbar, text="内容", bg=PANEL, fg=TEXT_SECONDARY, font=FONT_SMALL).pack(side="left", padx=14)

clear_btn = tk.Label(editor_toolbar, text="清空", bg=PANEL, fg=TEXT_LIGHT, font=FONT_SMALL, cursor="hand2")
clear_btn.pack(side="right", padx=14)
clear_btn.bind("<Button-1>", lambda e: clear_text())
clear_btn.bind("<Enter>", lambda e: clear_btn.config(fg=TEXT))
clear_btn.bind("<Leave>", lambda e: clear_btn.config(fg=TEXT_LIGHT))

toolbar_line = tk.Frame(editor_wrapper, bg=BORDER, height=1)
toolbar_line.pack(fill="x")


# ============================================================
# 文本框（设定合理的默认高度 height=9）
# ============================================================

text_box = tk.Text(
    editor_wrapper,
    height=9,  # 控制编辑框显示行数
    wrap="word",
    bg=PANEL,
    fg=TEXT,
    insertbackground=ACCENT,
    selectbackground="#dce6ff",
    selectforeground=TEXT,
    relief="flat",
    bd=0,
    highlightthickness=0,
    font=FONT_EDITOR,
    padx=16,
    pady=12,
    undo=True,
)
text_box.pack(fill="x")

text_box.bind("<FocusIn>", remove_placeholder)
text_box.bind("<FocusOut>", restore_placeholder)
text_box.bind("<KeyRelease>", update_char_count)


# ============================================================
# 编辑区底部
# ============================================================

editor_bottom = tk.Frame(editor_wrapper, bg=PANEL, height=32)
editor_bottom.pack(fill="x")
editor_bottom.pack_propagate(False)

char_count_label = tk.Label(editor_bottom, text="0 字", bg=PANEL, fg=TEXT_LIGHT, font=FONT_SMALL)
char_count_label.pack(side="right", padx=14)


# ============================================================
# 操作区
# ============================================================

action_bar = tk.Frame(root, bg=BG)
action_bar.pack(fill="x", padx=36, pady=(0, 10))

status_frame = tk.Frame(action_bar, bg=BG)
status_frame.pack(side="left", pady=4)

status_dot = tk.Label(status_frame, text="●", bg=BG, fg=TEXT_LIGHT, font=("微软雅黑", 9))
status_dot.pack(side="left")

status_label = tk.Label(status_frame, text="等待传送", bg=BG, fg=TEXT_SECONDARY, font=FONT_SMALL)
status_label.pack(side="left", padx=(6, 0))

send_btn = tk.Button(
    action_bar,
    text="传送",
    command=send,
    bg=ACCENT,
    fg="white",
    activebackground=ACCENT_PRESS,
    activeforeground="white",
    relief="flat",
    bd=0,
    font=("微软雅黑", 11, "bold"),
    cursor="hand2",
    padx=28,
    pady=6
)
send_btn.pack(side="right")
send_btn.bind("<Enter>", lambda e: send_btn.config(bg=ACCENT_HOVER) if send_btn["state"] == "normal" else None)
send_btn.bind("<Leave>", lambda e: send_btn.config(bg=ACCENT) if send_btn["state"] == "normal" else None)


# ============================================================
# 日志区域（设为填充并可随窗口拉伸扩展 expand=True）
# ============================================================

log_header = tk.Frame(root, bg=BG)
log_header.pack(fill="x", padx=36, pady=(4, 6))

tk.Label(log_header, text="执行日志", bg=BG, fg=TEXT_SECONDARY, font=FONT_SMALL).pack(side="left")

log_frame = tk.Frame(root, bg=LOG_BG, highlightthickness=1, highlightbackground=BORDER)
log_frame.pack(fill="both", expand=True, padx=36, pady=(0, 24))  # expand=True 占据余下空间

log_box = scrolledtext.ScrolledText(
    log_frame,
    height=6,  # 增大基础默认行数
    wrap="word",
    state="disabled",
    bg=LOG_BG,
    fg=TEXT_SECONDARY,
    insertbackground=ACCENT,
    relief="flat",
    bd=0,
    highlightthickness=0,
    font=FONT_LOG,
    padx=14,
    pady=10,
)
log_box.pack(fill="both", expand=True)


# ============================================================
# 初始化
# ============================================================

add_placeholder()
text_box.focus_set()

text_box.bind("<Control-Return>", on_ctrl_enter)
root.bind("<Control-Return>", on_ctrl_enter)

root.after(50, process_ui_queue)
root.mainloop()