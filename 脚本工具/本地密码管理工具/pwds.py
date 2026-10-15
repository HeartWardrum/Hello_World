"""
pwds - 极简本地密码速查本
快捷键：
  全局 Ctrl+Shift+P  唤起/隐藏窗口
  搜索框输入         实时过滤
  Enter              复制密码并隐藏
  Ctrl+Enter         复制账号
  Ctrl+N             新建
  Ctrl+E             编辑
  Ctrl+D             删除
  Ctrl+G             生成随机密码并复制
  Esc                隐藏窗口
"""

import os
import random
import shutil
import sqlite3
import string
import time
import tkinter as tk
from datetime import datetime
from tkinter import ttk, messagebox

import pyperclip
from pynput import keyboard

# ---------------- 配置 ----------------

APP_DIR = os.path.join(os.path.expanduser("~"), ".pwds")
DB_PATH = os.path.join(APP_DIR, "pwds.db")
BACKUP_DIR = os.path.join(APP_DIR, "backup")
CLIPBOARD_CLEAR_MS = 30_000          # 复制后多少毫秒清空剪贴板
HOTKEY_COMBO = {                     # 全局热键：Ctrl+Shift+P
    keyboard.Key.ctrl,
    keyboard.Key.shift,
    keyboard.KeyCode.from_char("p"),
}

# ---------------- 数据库 ----------------

def _ensure_dirs():
    os.makedirs(APP_DIR, exist_ok=True)
    os.makedirs(BACKUP_DIR, exist_ok=True)


def _backup_on_start():
    if not os.path.exists(DB_PATH):
        return
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = os.path.join(BACKUP_DIR, f"pwds_{stamp}.db")
    try:
        shutil.copy2(DB_PATH, dst)
    except Exception:
        return
    files = sorted(
        (f for f in os.listdir(BACKUP_DIR) if f.startswith("pwds_")),
        reverse=True,
    )
    for old in files[7:]:
        try:
            os.remove(os.path.join(BACKUP_DIR, old))
        except Exception:
            pass


def init_db():
    _ensure_dirs()
    _backup_on_start()
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            username TEXT DEFAULT '',
            password TEXT DEFAULT '',
            url TEXT DEFAULT '',
            note TEXT DEFAULT '',
            tags TEXT DEFAULT '',
            use_count INTEGER DEFAULT 0,
            updated_at REAL
        )
        """
    )
    conn.commit()
    conn.close()


def _conn():
    return sqlite3.connect(DB_PATH)


def list_entries(keyword=""):
    conn = _conn()
    cur = conn.cursor()
    if keyword:
        like = f"%{keyword}%"
        cur.execute(
            """
            SELECT id, title, username, password, url, note, tags, use_count
            FROM entries
            WHERE title LIKE ? OR username LIKE ? OR url LIKE ?
               OR tags LIKE ? OR note LIKE ?
            ORDER BY use_count DESC, updated_at DESC
            """,
            (like, like, like, like, like),
        )
    else:
        cur.execute(
            """
            SELECT id, title, username, password, url, note, tags, use_count
            FROM entries
            ORDER BY use_count DESC, updated_at DESC
            LIMIT 200
            """
        )
    rows = cur.fetchall()
    conn.close()
    return rows


def add_entry(title, username, password, url="", note="", tags=""):
    conn = _conn()
    conn.execute(
        """
        INSERT INTO entries (title, username, password, url, note, tags, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (title, username, password, url, note, tags, time.time()),
    )
    conn.commit()
    conn.close()


def update_entry(entry_id, title, username, password, url, note, tags):
    conn = _conn()
    conn.execute(
        """
        UPDATE entries
        SET title=?, username=?, password=?, url=?, note=?, tags=?, updated_at=?
        WHERE id=?
        """,
        (title, username, password, url, note, tags, time.time(), entry_id),
    )
    conn.commit()
    conn.close()


def delete_entry(entry_id):
    conn = _conn()
    conn.execute("DELETE FROM entries WHERE id=?", (entry_id,))
    conn.commit()
    conn.close()


def bump_use(entry_id):
    conn = _conn()
    conn.execute("UPDATE entries SET use_count = use_count + 1 WHERE id=?", (entry_id,))
    conn.commit()
    conn.close()


# ---------------- 工具 ----------------

def gen_password(length=16):
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*()-_=+"
    return "".join(random.choice(alphabet) for _ in range(length))


# ---------------- 全局热键 ----------------

class GlobalHotkey:
    def __init__(self, callback, combo=None):
        self.callback = callback
        self.combo = combo or HOTKEY_COMBO
        self._pressed = set()
        self._listener = None

    def _normalize(self, key):
        if hasattr(key, "char") and key.char:
            return keyboard.KeyCode.from_char(key.char.lower())
        return key

    def _on_press(self, key):
        self._pressed.add(self._normalize(key))
        if self.combo.issubset(self._pressed):
            self._pressed.clear()
            try:
                self.callback()
            except Exception:
                pass

    def _on_release(self, key):
        self._pressed.discard(self._normalize(key))

    def start(self):
        self._listener = keyboard.Listener(
            on_press=self._on_press, on_release=self._on_release
        )
        self._listener.daemon = True
        self._listener.start()

    def stop(self):
        if self._listener:
            self._listener.stop()


# ---------------- 新建/编辑对话框 ----------------

class EntryDialog(tk.Toplevel):
    def __init__(self, parent, entry=None, on_save=None):
        super().__init__(parent)
        self.title("编辑条目" if entry else "新建条目")
        self.geometry("440x320")
        self.transient(parent)
        self.grab_set()
        self.on_save = on_save
        self.entry = entry

        self.vars = {}
        fields = [
            ("title", "名称"),
            ("username", "账号"),
            ("password", "密码"),
            ("url", "URL"),
            ("tags", "标签"),
            ("note", "备注"),
        ]

        for i, (key, label) in enumerate(fields):
            tk.Label(self, text=label).grid(row=i, column=0, sticky="e", padx=6, pady=4)
            var = tk.StringVar()
            self.vars[key] = var
            ent = tk.Entry(self, textvariable=var, width=36)
            ent.grid(row=i, column=1, sticky="w", padx=6, pady=4)
            if key == "password":
                tk.Button(self, text="生成", command=self._gen).grid(row=i, column=2, padx=4)

        if entry:
            self.vars["title"].set(entry[1] or "")
            self.vars["username"].set(entry[2] or "")
            self.vars["password"].set(entry[3] or "")
            self.vars["url"].set(entry[4] or "")
            self.vars["note"].set(entry[5] or "")
            self.vars["tags"].set(entry[6] or "")

        btns = tk.Frame(self)
        btns.grid(row=len(fields), column=0, columnspan=3, pady=10)
        tk.Button(btns, text="保存", command=self._save, width=10).pack(side="left", padx=6)
        tk.Button(btns, text="取消", command=self.destroy, width=10).pack(side="left")

        self.bind("<Control-s>", lambda e: self._save())
        self.bind("<Escape>", lambda e: self.destroy())

        self.after(50, lambda: self.focus_force())

    def _gen(self):
        self.vars["password"].set(gen_password())

    def _save(self):
        title = self.vars["title"].get().strip()
        if not title:
            messagebox.showwarning("提示", "名称不能为空", parent=self)
            return
        data = (
            title,
            self.vars["username"].get().strip(),
            self.vars["password"].get(),
            self.vars["url"].get().strip(),
            self.vars["note"].get().strip(),
            self.vars["tags"].get().strip(),
        )
        if self.entry:
            self.on_save(data, self.entry[0])
        else:
            self.on_save(data)
        self.destroy()


# ---------------- 主窗口 ----------------

class PasswordApp:
    def __init__(self, root):
        self.root = root
        self.root.title("pwds")
        self.root.geometry("640x420")
        self.root.attributes("-topmost", True)
        self.root.protocol("WM_DELETE_WINDOW", self.hide)

        self._clip_job = None

        self._build_search()
        self._build_list()
        self._build_buttons()
        self._bind_keys()

        self.refresh()

    def _build_search(self):
        frame = tk.Frame(self.root)
        frame.pack(fill="x", padx=10, pady=(10, 4))

        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self.refresh())

        entry = tk.Entry(frame, textvariable=self.search_var, font=("Consolas", 14))
        entry.pack(fill="x")
        self.search_entry = entry

    def _build_list(self):
        frame = tk.Frame(self.root)
        frame.pack(fill="both", expand=True, padx=10, pady=4)

        columns = ("title", "username", "tags")
        self.tree = ttk.Treeview(frame, columns=columns, show="headings", height=12)
        self.tree.heading("title", text="名称")
        self.tree.heading("username", text="账号")
        self.tree.heading("tags", text="标签")
        self.tree.column("title", width=200)
        self.tree.column("username", width=220)
        self.tree.column("tags", width=140)

        vsb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self.tree.bind("<Double-1>", lambda e: self.copy_password())
        self.tree.bind("<Return>", lambda e: self.copy_password())
        self.tree.bind("<Control-Return>", lambda e: self.copy_username())

    def _build_buttons(self):
        frame = tk.Frame(self.root)
        frame.pack(fill="x", padx=10, pady=(4, 10))

        tk.Button(frame, text="新建 (Ctrl+N)", command=self.new_entry).pack(side="left")
        tk.Button(frame, text="编辑 (Ctrl+E)", command=self.edit_entry).pack(side="left", padx=6)
        tk.Button(frame, text="删除 (Ctrl+D)", command=self.delete_entry).pack(side="left")
        tk.Button(frame, text="复制密码 (Enter)", command=self.copy_password).pack(side="right")
        tk.Button(frame, text="复制账号 (Ctrl+Enter)", command=self.copy_username).pack(side="right", padx=6)

    def _bind_keys(self):
        r = self.root
        r.bind("<Escape>", lambda e: self.hide())
        r.bind("<Control-n>", lambda e: self.new_entry())
        r.bind("<Control-e>", lambda e: self.edit_entry())
        r.bind("<Control-d>", lambda e: self.delete_entry())
        r.bind("<Control-Return>", lambda e: self.copy_username())
        r.bind("<Return>", lambda e: self.copy_password())
        r.bind("<Control-g>", lambda e: self.copy_generated())

    # ---------- 数据刷新 ----------

    def refresh(self):
        keyword = self.search_var.get().strip()
        rows = list_entries(keyword)

        self.tree.delete(*self.tree.get_children())
        self._rows = {}
        for row in rows:
            eid, title, username, password, url, note, tags, use_count = row
            iid = str(eid)
            self._rows[iid] = row
            self.tree.insert("", "end", iid=iid, values=(title, username, tags))

        children = self.tree.get_children()
        if children:
            self.tree.selection_set(children[0])
            self.tree.focus(children[0])

    def _selected(self):
        sel = self.tree.selection()
        if not sel:
            return None
        return self._rows.get(sel[0])

    # ---------- 动作 ----------

    def copy_password(self):
        row = self._selected()
        if not row:
            return
        self._copy(row[3], f"密码已复制：{row[1]}")
        bump_use(row[0])
        self.hide()

    def copy_username(self):
        row = self._selected()
        if not row:
            return
        self._copy(row[2], f"账号已复制：{row[1]}")
        self.hide()

    def copy_generated(self):
        pwd = gen_password()
        self._copy(pwd, "已生成并复制随机密码")

    def _copy(self, text, tip):
        pyperclip.copy(text or "")
        self._schedule_clipboard_clear()
        self.root.title(f"pwds — {tip}")
        self.root.after(1500, lambda: self.root.title("pwds"))

    def _schedule_clipboard_clear(self):
        if self._clip_job:
            self.root.after_cancel(self._clip_job)
        self._clip_job = self.root.after(CLIPBOARD_CLEAR_MS, self._clear_clipboard)

    def _clear_clipboard(self):
        try:
            pyperclip.copy("")
        except Exception:
            pass
        self._clip_job = None

    # ---------- 增删改 ----------

    def new_entry(self):
        EntryDialog(self.root, on_save=self._on_new_saved)

    def _on_new_saved(self, data):
        add_entry(*data)
        self.refresh()

    def edit_entry(self):
        row = self._selected()
        if not row:
            return
        EntryDialog(self.root, entry=row, on_save=self._on_edit_saved)

    def _on_edit_saved(self, data, entry_id):
        update_entry(entry_id, *data)
        self.refresh()

    def delete_entry(self):
        row = self._selected()
        if not row:
            return
        if messagebox.askyesno("确认", f"删除「{row[1]}」？"):
            delete_entry(row[0])
            self.refresh()

    # ---------- 显示/隐藏 ----------

    def show(self):
        self.root.deiconify()
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.search_entry.focus_force()
        self.search_var.set("")
        self.refresh()

    def hide(self):
        self.root.withdraw()


# ---------------- 入口 ----------------

def main():
    init_db()

    root = tk.Tk()
    app = PasswordApp(root)
    root.withdraw()

    def trigger():
        root.after(0, app.show)

    hk = GlobalHotkey(trigger)
    hk.start()

    # 隐藏菜单：右键标题栏或按 Alt 可见
    menu = tk.Menu(root, tearoff=0)
    menu.add_command(label="显示", command=app.show)
    menu.add_command(label="退出", command=lambda: (hk.stop(), root.destroy()))
    root.config(menu=menu)

    app.show()

    try:
        root.mainloop()
    finally:
        hk.stop()


if __name__ == "__main__":
    main()