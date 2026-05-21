"""
轻量级剪贴板管理工具 - Clipboard Manager
支持文本和图片，全局快捷键，双区域模式，自动清理
"""

import sys
import os
import json
import sqlite3
import hashlib
import time
import threading
import datetime
from collections import OrderedDict
from io import BytesIO
import ctypes
from ctypes import wintypes
# PyQt5
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QListWidget, QListWidgetItem, QLineEdit, QPushButton, QLabel,
    QSystemTrayIcon, QMenu, QAction, QScrollArea, QFrame, QSizePolicy,
    QMessageBox, QDialog, QCheckBox, QSpinBox, QFormLayout, QTabWidget,
    QAbstractItemView, QSplitter
)
from PyQt5.QtCore import (
    Qt, QThread, pyqtSignal, QTimer, QSize, QPoint, QSettings,QEvent
)
from PyQt5.QtGui import (
    QIcon, QPixmap, QImage, QColor, QPainter, QFont, QCursor,
    QPalette, QKeySequence
)

# Pillow
try:
    from PIL import Image, ImageGrab
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    print("警告: Pillow未安装，图片支持受限")

# pynput
try:
    from pynput import keyboard as pynput_keyboard
    PYNPUT_AVAILABLE = True
except ImportError:
    PYNPUT_AVAILABLE = False
    print("警告: pynput未安装，全局快捷键不可用")

# pyautogui
try:
    import pyautogui
    PYAUTOGUI_AVAILABLE = True
except ImportError:
    PYAUTOGUI_AVAILABLE = False
    print("警告: pyautogui未安装，模拟粘贴功能受限")


# ─────────────────────────── 常量 ───────────────────────────
APP_NAME = "ClipboardManager"
APP_VERSION = "1.0.0"
DATA_DIR = os.path.join(os.path.expanduser("~"), ".clipboard_manager")
HISTORY_FILE = os.path.join(DATA_DIR, "history.json")
DB_FILE = os.path.join(DATA_DIR, "permanent.db")
IMAGES_DIR = os.path.join(DATA_DIR, "images")
THUMBNAIL_SIZE = (120, 80)
MAX_TEXT_PREVIEW = 200


# ─────────────────────────── 工具函数 ───────────────────────────
def ensure_dirs():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(IMAGES_DIR, exist_ok=True)


def compute_md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def pil_to_qpixmap(pil_img: "Image.Image") -> QPixmap:
    pil_img = pil_img.convert("RGBA")
    data = pil_img.tobytes("raw", "RGBA")
    qimg = QImage(data, pil_img.width, pil_img.height, QImage.Format_RGBA8888)
    return QPixmap.fromImage(qimg)


def make_thumbnail(pil_img: "Image.Image", size=THUMBNAIL_SIZE) -> "Image.Image":
    img = pil_img.copy()
    img.thumbnail(size, Image.LANCZOS)
    return img


def now_ts() -> float:
    return time.time()


def ts_to_str(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts).strftime("%m-%d %H:%M")


# ─────────────────────────── 数据模型 ───────────────────────────
class ClipEntry:
    """单条剪贴板条目"""
    def __init__(self, entry_type: str, content, timestamp: float = None,
                 entry_id: str = None, note: str = ""):
        self.type = entry_type        # "text" | "image"
        self.content = content        # 文本str 或 bytes(PNG)
        self.timestamp = timestamp or now_ts()
        self.id = entry_id or compute_md5(
            (str(self.timestamp) + str(content[:50] if isinstance(content, str) else content[:50])).encode()
        )
        self.note = note              # 备注/文件名(图片)

    def get_hash(self) -> str:
        if self.type == "text":
            return compute_md5(self.content.encode("utf-8"))
        else:
            return compute_md5(self.content)

    def get_preview(self) -> str:
        if self.type == "text":
            t = self.content.replace("\n", " ").strip()
            return t[:MAX_TEXT_PREVIEW] + ("…" if len(t) > MAX_TEXT_PREVIEW else "")
        else:
            return f"[图片] {self.note or '未命名'}"


# ─────────────────────────── 历史存储 ───────────────────────────
class HistoryStore:
    """普通历史 - JSON + 本地图片文件"""

    def __init__(self, max_count=100, max_days=30):
        self.max_count = max_count
        self.max_days = max_days          # 0 = 禁用时间清理
        self._entries: list[ClipEntry] = []
        self._hash_map: dict[str, int] = {}   # hash -> index
        self.load()

    # ── 增 ──
    def add(self, entry: ClipEntry) -> bool:
        """添加或更新条目，返回是否真正新增"""
        h = entry.get_hash()
        if h in self._hash_map:
            # 去重: 移到队首并更新时间戳
            idx = self._hash_map[h]
            old = self._entries.pop(idx)
            old.timestamp = entry.timestamp
            self._entries.insert(0, old)
            self._rebuild_hash_map()
            self.save()
            return False
        # 真正新增
        self._entries.insert(0, entry)
        self._hash_map[h] = 0
        self._rebuild_hash_map()
        self._cleanup()
        self.save()
        return True

    # ── 删 ──
    def remove(self, entry_id: str):
        self._entries = [e for e in self._entries if e.id != entry_id]
        self._rebuild_hash_map()
        self.save()

    def clear_all(self):
        self._entries.clear()
        self._hash_map.clear()
        self.save()

    # ── 查 ──
    def get_all(self) -> list:
        return list(self._entries)

    def search(self, keyword: str) -> list:
        kw = keyword.lower()
        return [e for e in self._entries
                if (e.type == "text" and kw in e.content.lower()) or
                   (e.type == "image" and kw in (e.note or "").lower())]

    # ── 内部 ──
    def _rebuild_hash_map(self):
        self._hash_map = {}
        for i, e in enumerate(self._entries):
            self._hash_map[e.get_hash()] = i

    def _cleanup(self):
        # 数量限制
        if self.max_count > 0 and len(self._entries) > self.max_count:
            removed = self._entries[self.max_count:]
            self._entries = self._entries[:self.max_count]
            for e in removed:
                if e.type == "image":
                    self._delete_image_file(e)
        # 时间限制
        if self.max_days > 0:
            cutoff = now_ts() - self.max_days * 86400
            kept, removed = [], []
            for e in self._entries:
                (kept if e.timestamp >= cutoff else removed).append(e)
            for e in removed:
                if e.type == "image":
                    self._delete_image_file(e)
            self._entries = kept
        self._rebuild_hash_map()

    def _delete_image_file(self, entry: ClipEntry):
        path = os.path.join(IMAGES_DIR, f"hist_{entry.id}.png")
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass

    def force_cleanup(self):
        self._cleanup()
        self.save()

    # ── 持久化 ──
    def save(self):
        data = []
        for e in self._entries:
            item = {"id": e.id, "type": e.type, "timestamp": e.timestamp, "note": e.note}
            if e.type == "text":
                item["content"] = e.content
            else:
                # 图片存到文件，JSON只存路径
                path = os.path.join(IMAGES_DIR, f"hist_{e.id}.png")
                if not os.path.exists(path):
                    try:
                        with open(path, "wb") as f:
                            f.write(e.content)
                    except Exception:
                        continue
                item["image_path"] = path
            data.append(item)
        try:
            with open(HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as ex:
            print(f"保存历史失败: {ex}")

    def load(self):
        if not os.path.exists(HISTORY_FILE):
            return
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            for item in data:
                if item["type"] == "text":
                    e = ClipEntry("text", item["content"], item["timestamp"],
                                  item["id"], item.get("note", ""))
                else:
                    path = item.get("image_path", "")
                    if not os.path.exists(path):
                        continue
                    with open(path, "rb") as f:
                        content = f.read()
                    e = ClipEntry("image", content, item["timestamp"],
                                  item["id"], item.get("note", ""))
                self._entries.append(e)
            self._rebuild_hash_map()
            self._cleanup()
        except Exception as ex:
            print(f"加载历史失败: {ex}")


# ─────────────────────────── 永久存储 ───────────────────────────
class PermanentStore:
    """永久保存 - SQLite"""

    def __init__(self):
        self._conn = sqlite3.connect(DB_FILE, check_same_thread=False)
        self._lock = threading.Lock()
        self._create_table()

    def _create_table(self):
        with self._lock:
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS permanent (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    content BLOB,
                    note TEXT,
                    timestamp REAL
                )
            """)
            self._conn.commit()

    def add(self, entry: ClipEntry) -> bool:
        """添加，若重复则更新时间戳，返回True=新增/False=更新"""
        h = entry.get_hash()
        # 检查是否已存在相同内容
        with self._lock:
            cur = self._conn.execute("SELECT id FROM permanent WHERE id=?", (h,))
            row = cur.fetchone()
            if row:
                self._conn.execute("UPDATE permanent SET timestamp=? WHERE id=?",
                                   (now_ts(), h))
                self._conn.commit()
                return False
            content = entry.content if entry.type == "image" else entry.content.encode("utf-8")
            self._conn.execute(
                "INSERT INTO permanent (id,type,content,note,timestamp) VALUES (?,?,?,?,?)",
                (h, entry.type, content, entry.note, entry.timestamp)
            )
            self._conn.commit()
            return True

    def remove(self, entry_id: str):
        with self._lock:
            self._conn.execute("DELETE FROM permanent WHERE id=?", (entry_id,))
            self._conn.commit()

    def get_all(self) -> list:
        with self._lock:
            cur = self._conn.execute(
                "SELECT id,type,content,note,timestamp FROM permanent ORDER BY timestamp DESC"
            )
            rows = cur.fetchall()
        result = []
        for row in rows:
            eid, etype, content, note, ts = row
            if etype == "text":
                content_decoded = content.decode("utf-8") if isinstance(content, bytes) else content
            else:
                content_decoded = bytes(content)
            e = ClipEntry(etype, content_decoded, ts, eid, note or "")
            result.append(e)
        return result

    def search(self, keyword: str) -> list:
        kw = keyword.lower()
        all_entries = self.get_all()
        return [e for e in all_entries
                if (e.type == "text" and kw in e.content.lower()) or
                   (e.type == "image" and kw in (e.note or "").lower())]

    def close(self):
        self._conn.close()


# ─────────────────────────── 剪贴板监控线程 ───────────────────────────
class ClipboardMonitor(QThread):
    new_entry = pyqtSignal(object)   # ClipEntry

    def __init__(self, parent=None):
        super().__init__(parent)
        self._last_hash = ""
        self._running = True

    def run(self):
        while self._running:
            try:
                self._check()
            except Exception:
                pass
            self.msleep(500)    # 每500ms检查一次（比轮询略重，但PIL.ImageGrab必须轮询）

    def _check(self):
        app = QApplication.instance()
        cb = app.clipboard()
        mime = cb.mimeData()

        if mime.hasImage():
            qimg = cb.image()
            if not qimg.isNull():
                ba = BytesIO()
                # QImage -> PIL
                qimg = qimg.convertToFormat(QImage.Format_RGBA8888)
                ptr = qimg.bits()
                ptr.setsize(qimg.byteCount())
                pil = Image.frombytes("RGBA", (qimg.width(), qimg.height()), bytes(ptr))
                pil.save(ba, "PNG")
                data = ba.getvalue()
                h = compute_md5(data)
                if h != self._last_hash:
                    self._last_hash = h
                    note = f"图片_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                    entry = ClipEntry("image", data, note=note)
                    self.new_entry.emit(entry)
        elif mime.hasText():
            text = mime.text().strip()
            if text:
                h = compute_md5(text.encode("utf-8"))
                if h != self._last_hash:
                    self._last_hash = h
                    entry = ClipEntry("text", text)
                    self.new_entry.emit(entry)

    def stop(self):
        self._running = False
        self.wait()


# ─────────────────────────── 条目Widget ───────────────────────────
class EntryItemWidget(QWidget):
    """列表中每个条目的显示Widget"""

    def __init__(self, entry: ClipEntry, parent=None):
        super().__init__(parent)
        self.entry = entry
        self._build_ui()

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(10)

        # 类型图标 / 缩略图
        if self.entry.type == "image" and PIL_AVAILABLE:
            try:
                ba = BytesIO(self.entry.content)
                pil = Image.open(ba)
                thumb = make_thumbnail(pil)
                pixmap = pil_to_qpixmap(thumb)
                lbl = QLabel()
                lbl.setPixmap(pixmap)
                lbl.setFixedSize(QSize(*THUMBNAIL_SIZE))
                lbl.setScaledContents(True)
                layout.addWidget(lbl)
            except Exception:
                lbl = QLabel("🖼")
                lbl.setFixedWidth(40)
                layout.addWidget(lbl)
        else:
            icon_lbl = QLabel("📋")
            icon_lbl.setFixedWidth(28)
            icon_lbl.setAlignment(Qt.AlignCenter)
            layout.addWidget(icon_lbl)

        # 文字内容
        right = QVBoxLayout()
        right.setSpacing(4)  # 稍微增加行间距 (原本是 2)
        preview = QLabel(self.entry.get_preview())
        preview.setWordWrap(True)
        # 将最大高度由 60 调大至 75，防止第二行/第三行被切掉一半
        preview.setMaximumHeight(75)
        # 将字体大小由 13px 调大至 15px
        preview.setStyleSheet("color: #e0e0e0; font-size: 15px;")
        time_lbl = QLabel(ts_to_str(self.entry.timestamp))
        # 将时间标签的字体大小由 11px 调大至 12px
        time_lbl.setStyleSheet("color: #888; font-size: 12px;")
        right.addWidget(preview)
        right.addWidget(time_lbl)
        layout.addLayout(right, 1)


# ─────────────────────────── 设置对话框 ───────────────────────────
class SettingsDialog(QDialog):
    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.config = dict(config)
        self.setWindowTitle("设置")
        self.setMinimumWidth(340)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(12)

        self.max_count_spin = QSpinBox()
        self.max_count_spin.setRange(10, 2000)
        self.max_count_spin.setValue(self.config.get("max_count", 100))
        form.addRow("最大历史条数:", self.max_count_spin)

        self.max_days_spin = QSpinBox()
        self.max_days_spin.setRange(0, 3650)
        self.max_days_spin.setValue(self.config.get("max_days", 30))
        self.max_days_spin.setSpecialValueText("不限制")
        form.addRow("保留天数 (0=不限):", self.max_days_spin)

        self.focus_hide_cb = QCheckBox("失去焦点时自动隐藏")
        self.focus_hide_cb.setChecked(self.config.get("focus_hide", True))
        form.addRow("", self.focus_hide_cb)

        layout.addLayout(form)

        btn_box = QHBoxLayout()
        ok_btn = QPushButton("保存")
        ok_btn.clicked.connect(self._save)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_box.addStretch()
        btn_box.addWidget(cancel_btn)
        btn_box.addWidget(ok_btn)
        layout.addLayout(btn_box)

    def _save(self):
        self.config["max_count"] = self.max_count_spin.value()
        self.config["max_days"] = self.max_days_spin.value()
        self.config["focus_hide"] = self.focus_hide_cb.isChecked()
        self.accept()

    def get_config(self) -> dict:
        return self.config


# ─────────────────────────── 主窗口 ───────────────────────────
class MainWindow(QMainWindow):
    def __init__(self, history: HistoryStore, permanent: PermanentStore,
                 config: dict):
        super().__init__()
        self.history = history
        self.permanent = permanent
        self.config = config
        self._mode = "history"   # "history" | "permanent"
        self._search_keyword = ""

        self.setWindowTitle("📋 剪贴板管理器 - 普通历史")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(600, 750)
        self._center_screen()
        self._build_ui()
        self._apply_style()

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)

    def nativeEvent(self, eventType, message):
        """
        拦截 Windows 底层原生消息。
        只要点击外部任何软件或桌面，Windows 会发送不激活消息，此时立刻隐藏。
        """
        if eventType == b"windows_generic_MSG":
            import ctypes
            from ctypes import wintypes

            # 将传入的 message 转换为 Windows 的 MSG 结构体
            msg = wintypes.MSG.from_address(int(message))

            # 0x001C 是 WM_ACTIVATEAPP 消息 (当应用被激活或取消激活时触发)
            if msg.message == 0x001C:
                # wparam 为 0 表示当前应用正在失去激活状态 (Clicked Outside)
                if msg.wParam == 0:
                    if self.isVisible() and self.config.get("focus_hide", True):
                        # 检查当前是不是因为弹出了设置对话框导致的失去激活
                        active_popup = QApplication.activeModalWidget() or QApplication.activePopupWidget()
                        if active_popup and active_popup != self:
                            return super().nativeEvent(eventType, message)

                        # 确定是点击了外部，执行隐藏
                        self.hide()

        return super().nativeEvent(eventType, message)
    
    def _center_screen(self):
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(
            screen.width() - self.width() - 40,
            (screen.height() - self.height()) // 2
        )

    def _build_ui(self):
        central = QWidget()
        central.setObjectName("centralWidget")
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(8)

        # 标题栏
        title_bar = QHBoxLayout()
        self.title_label = QLabel("📋 普通历史")
        self.title_label.setObjectName("titleLabel")
        title_bar.addWidget(self.title_label)
        title_bar.addStretch()

        # 模式切换按钮
        self.toggle_btn = QPushButton("⭐ 永久保存")
        self.toggle_btn.setObjectName("toggleBtn")
        self.toggle_btn.clicked.connect(self.toggle_mode)
        title_bar.addWidget(self.toggle_btn)

        # 设置按钮
        settings_btn = QPushButton("⚙")
        settings_btn.setObjectName("iconBtn")
        settings_btn.setFixedSize(28, 28)
        settings_btn.clicked.connect(self.open_settings)
        title_bar.addWidget(settings_btn)

        # 关闭按钮
        close_btn = QPushButton("✕")
        close_btn.setObjectName("closeBtn")
        close_btn.setFixedSize(28, 28)
        close_btn.clicked.connect(self.hide)
        title_bar.addWidget(close_btn)

        main_layout.addLayout(title_bar)

        # 搜索框
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("🔍 搜索...")
        self.search_box.setObjectName("searchBox")
        self.search_box.textChanged.connect(self._on_search)
        self.search_box.installEventFilter(self)  # 【新增】安装事件过滤器
        main_layout.addWidget(self.search_box)

        # 列表
        self.list_widget = QListWidget()
        self.list_widget.setObjectName("listWidget")
        self.list_widget.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list_widget.setSpacing(2)
        self.list_widget.itemClicked.connect(self._on_item_clicked)
        self.list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._on_context_menu)
        self.list_widget.installEventFilter(self)  # 【新增】安装事件过滤器
        main_layout.addWidget(self.list_widget)

        # 底部状态栏
        status_bar = QHBoxLayout()
        self.status_label = QLabel("就绪")
        self.status_label.setObjectName("statusLabel")
        status_bar.addWidget(self.status_label)
        status_bar.addStretch()

        clear_btn = QPushButton("清空历史")
        clear_btn.setObjectName("dangerBtn")
        clear_btn.clicked.connect(self._clear_history)
        status_bar.addWidget(clear_btn)
        main_layout.addLayout(status_bar)

        self._refresh_list()

    def _apply_style(self):
        self.setStyleSheet("""
            QMainWindow { background: transparent; }
            #centralWidget {
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 #1a1a2e, stop:1 #16213e);
                border-radius: 14px;
                border: 1px solid #2a2a5e;
            }
            #titleLabel {
                color: #a0c4ff;
                font-size: 15px;
                font-weight: bold;
                font-family: 'Microsoft YaHei', 'PingFang SC', sans-serif;
            }
            #toggleBtn {
                background: #2a2a5e;
                color: #ffd700;
                border: 1px solid #3a3a7e;
                border-radius: 6px;
                padding: 4px 10px;
                font-size: 12px;
            }
            #toggleBtn:hover { background: #3a3a8e; }
            #iconBtn, #closeBtn {
                background: #1e1e3a;
                color: #888;
                border: 1px solid #333;
                border-radius: 6px;
                font-size: 13px;
            }
            #iconBtn:hover { background: #2a2a4a; color: #aaa; }
            #closeBtn:hover { background: #8b2020; color: #fff; }
            #searchBox {
                background: #1e1e38;
                color: #d0d0f0;
                border: 1px solid #3a3a6e;
                border-radius: 8px;
                padding: 6px 12px;
                font-size: 13px;
            }
            #searchBox:focus { border-color: #5a5aae; }
            #listWidget {
                background: #12122a;
                border: 1px solid #2a2a4e;
                border-radius: 8px;
                outline: none;
            }
            #listWidget::item {
                border-radius: 6px;
                margin: 1px 4px;
            }
            #listWidget::item:selected {
                background: #2d2d6e;
            }
            #listWidget::item:hover {
                background: #20204a;
            }
            QScrollBar:vertical {
                background: #1a1a30;
                width: 6px;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical {
                background: #4a4a8e;
                border-radius: 3px;
                min-height: 20px;
            }
            #statusLabel { color: #666; font-size: 11px; }
            #dangerBtn {
                background: #3a1a1a;
                color: #ff8888;
                border: 1px solid #6a2a2a;
                border-radius: 6px;
                padding: 3px 8px;
                font-size: 11px;
            }
            #dangerBtn:hover { background: #6a2020; }
        """)

    # ── 模式切换 ──
    def toggle_mode(self):
        if self._mode == "history":
            self._mode = "permanent"
            self.title_label.setText("⭐ 永久保存")
            self.toggle_btn.setText("📋 普通历史")
            self.setWindowTitle("📋 剪贴板管理器 - 永久保存")
        else:
            self._mode = "history"
            self.title_label.setText("📋 普通历史")
            self.toggle_btn.setText("⭐ 永久保存")
            self.setWindowTitle("📋 剪贴板管理器 - 普通历史")
        self._refresh_list()

    # ── 刷新列表 ──
    def _refresh_list(self):
        kw = self._search_keyword
        if self._mode == "history":
            entries = self.history.search(kw) if kw else self.history.get_all()
        else:
            entries = self.permanent.search(kw) if kw else self.permanent.get_all()

        self.list_widget.clear()
        for entry in entries:
            item = QListWidgetItem()
            widget = EntryItemWidget(entry)
            # 将原代码的 130 和 72 调大，例如改为 140 和 95
            item.setSizeHint(QSize(self.list_widget.width() - 10,
                                   140 if entry.type == "image" else 95))
            item.setData(Qt.UserRole, entry)
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, widget)

        count = len(entries)
        mode_str = "普通历史" if self._mode == "history" else "永久保存"
        self.status_label.setText(f"{mode_str}: {count} 条")

        # 【新增】如果列表有数据，默认选中第一项，方便键盘流直接操作
        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)

    def refresh(self):
        self._refresh_list()

    # ── 搜索 ──
    def _on_search(self, text: str):
        self._search_keyword = text.strip()
        self._refresh_list()

    # ── 点击条目 → 粘贴 ──
    def _on_item_clicked(self, item: QListWidgetItem):
        entry: ClipEntry = item.data(Qt.UserRole)
        self._paste_entry(entry)

    def _paste_entry(self, entry: ClipEntry, as_plain_text=False):
        """将条目写入剪贴板并模拟粘贴"""
        cb = QApplication.clipboard()

        if as_plain_text:
            # 纯文本模式
            if entry.type == "text":
                cb.setText(entry.content)
            else:
                # 如果是图片要求纯文本，则粘贴它的备注或标签名
                cb.setText(entry.note or "[图片]")
        else:
            # 常规模式
            if entry.type == "text":
                cb.setText(entry.content)
            else:
                # 图片
                ba = BytesIO(entry.content)
                try:
                    pil = Image.open(ba)
                    qimg = pil_to_qpixmap(pil)
                    cb.setPixmap(qimg)
                except Exception:
                    return

        self.hide()
        QTimer.singleShot(150, self._simulate_paste)

    def _simulate_paste(self):
        if PYAUTOGUI_AVAILABLE:
            try:
                import pyautogui
                pyautogui.hotkey("ctrl", "v")
                return
            except Exception:
                pass
        # fallback: pynput
        if PYNPUT_AVAILABLE:
            try:
                from pynput.keyboard import Key, Controller
                kc = Controller()
                with kc.pressed(Key.ctrl):
                    kc.press("v")
                    kc.release("v")
            except Exception:
                pass

    # ── 右键菜单 ──
    def _on_context_menu(self, pos: QPoint):
        item = self.list_widget.itemAt(pos)
        if not item:
            return
        entry: ClipEntry = item.data(Qt.UserRole)
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background: #1e1e38; color: #d0d0f0; border: 1px solid #3a3a6e; border-radius:6px; }
            QMenu::item:selected { background: #2d2d6e; }
        """)

        paste_action = menu.addAction("📋 粘贴")
        paste_action.triggered.connect(lambda: self._paste_entry(entry))

        if self._mode == "history":
            fav_action = menu.addAction("⭐ 添加到永久保存")
            fav_action.triggered.connect(lambda: self._add_to_permanent(entry))
            del_action = menu.addAction("🗑 从历史删除")
            del_action.triggered.connect(lambda: self._remove_from_history(entry))
        else:
            del_action = menu.addAction("🗑 从永久删除")
            del_action.triggered.connect(lambda: self._remove_from_permanent(entry))

        menu.exec_(self.list_widget.viewport().mapToGlobal(pos))

    def _add_to_permanent(self, entry: ClipEntry):
        added = self.permanent.add(entry)
        msg = "已添加到永久保存" if added else "内容已存在，已更新时间戳"
        self.status_label.setText(msg)
        QTimer.singleShot(3000, lambda: self.status_label.setText("就绪"))

    def _remove_from_history(self, entry: ClipEntry):
        self.history.remove(entry.id)
        self._refresh_list()

    def _remove_from_permanent(self, entry: ClipEntry):
        self.permanent.remove(entry.id)
        self._refresh_list()

    def _clear_history(self):
        if self._mode == "history":
            ret = QMessageBox.question(self, "确认", "清空所有普通历史记录？",
                                       QMessageBox.Yes | QMessageBox.No)
            if ret == QMessageBox.Yes:
                self.history.clear_all()
                self._refresh_list()

    # ── 设置 ──
    def open_settings(self):
        dlg = SettingsDialog(self.config, self)
        if dlg.exec_() == QDialog.Accepted:
            new_cfg = dlg.get_config()
            self.config.update(new_cfg)
            self.history.max_count = new_cfg["max_count"]
            self.history.max_days = new_cfg["max_days"]
            self.history.force_cleanup()
            save_config(self.config)
            self._refresh_list()

    # ── 失焦隐藏 ──
    def eventFilter(self, obj, event):
        # 拦截键盘按下事件
        if event.type() == QEvent.KeyPress:
            key = event.key()

            # 1. 处理方向键上下选择
            if key in (Qt.Key_Up, Qt.Key_Down):
                count = self.list_widget.count()
                if count > 0:
                    current_row = self.list_widget.currentRow()
                    if key == Qt.Key_Down:
                        next_row = current_row + 1
                        if next_row >= count:
                            next_row = count - 1  # 停留在最底部（也可以改为0回到顶部）
                    else:  # Qt.Key_Up
                        next_row = current_row - 1
                        if next_row < 0:
                            next_row = 0  # 停留在最顶部

                    self.list_widget.setCurrentRow(next_row)
                    # 确保选中的滚动条跟随可见
                    self.list_widget.scrollToItem(self.list_widget.currentItem())
                    return True  # 拦截事件，防止输入框光标左右乱跳

            # 2. 处理回车直接粘贴
            elif key in (Qt.Key_Return, Qt.Key_Enter):
                current_item = self.list_widget.currentItem()
                if current_item:
                    entry = current_item.data(Qt.UserRole)
                    # 检查是否同时按下了 Shift 键
                    if event.modifiers() == Qt.ShiftModifier:
                        self._paste_entry(entry, as_plain_text=True)
                    else:
                        self._paste_entry(entry, as_plain_text=False)
                    return True  # 拦截回车，防止输入框触发其他默认行为

        return super().eventFilter(obj, event)

    def _maybe_hide(self):
        if not self.isActiveWindow():
            self.hide()

    # ── 键盘 ──
    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.hide()
        elif event.key() == Qt.Key_G and event.modifiers() == Qt.ControlModifier:
            self.toggle_mode()
        else:
            super().keyPressEvent(event)

    # ── 拖动 ──
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPos() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton and hasattr(self, "_drag_pos"):
            self.move(event.globalPos() - self._drag_pos)


# ─────────────────────────── 全局快捷键 ───────────────────────────
class GlobalHotkeyManager(QThread):
    """使用 Windows API 注册最高优先级的全局热键（完美拦截）"""
    signal_alt_v = pyqtSignal()
    signal_ctrl_g = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._running = True
        self.user32 = ctypes.windll.user32

        # 热键 ID (任意唯一的整数)
        self.HOTKEY_ALT_V_ID = 1001
        self.HOTKEY_CTRL_G_ID = 1002

        # Windows 快捷键修饰键常量
        self.MOD_ALT = 0x0001
        self.MOD_CONTROL = 0x0002

        # 键码 (V = 0x56, G = 0x47)
        self.VK_V = 0x56
        self.VK_G = 0x47

    def start_listening(self):
        # 启动线程来监听 Windows 消息队列
        self.daemon = True
        self.start()

    def run(self):
        # 1. 注册热键（注册成功后，系统会自动拦截对应按键）
        # RegisterHotKey(hWnd=None, id, fsModifiers, vk)
        res1 = self.user32.RegisterHotKey(None, self.HOTKEY_ALT_V_ID, self.MOD_ALT, self.VK_V)
        res2 = self.user32.RegisterHotKey(None, self.HOTKEY_CTRL_G_ID, self.MOD_CONTROL, self.VK_G)

        if not res1 or not res2:
            print("警告: 全局热键注册失败，可能被其他最高权限软件占用了")

        # 2. 消息循环监听
        msg = wintypes.MSG()
        while self._running:
            # GetMessage 会阻塞线程，直到有热键消息产生
            if self.user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
                # 0x0312 是 WM_HOTKEY 消息
                if msg.message == 0x0312:
                    hk_id = msg.wParam
                    if hk_id == self.HOTKEY_ALT_V_ID:
                        self.signal_alt_v.emit()
                    elif hk_id == self.HOTKEY_CTRL_G_ID:
                        self.signal_ctrl_g.emit()

                self.user32.TranslateMessage(ctypes.byref(msg))
                self.user32.DispatchMessageW(ctypes.byref(msg))

    def stop(self):
        self._running = False
        # 注销热键，释放系统资源
        self.user32.UnregisterHotKey(None, self.HOTKEY_ALT_V_ID)
        self.user32.UnregisterHotKey(None, self.HOTKEY_CTRL_G_ID)
        self.wait()
# ─────────────────────────── 配置 ───────────────────────────
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")

DEFAULT_CONFIG = {
    "max_count": 100,
    "max_days": 30,
    "focus_hide": True,
}


def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                cfg = json.load(f)
            return {**DEFAULT_CONFIG, **cfg}
        except Exception:
            pass
    return dict(DEFAULT_CONFIG)


def save_config(cfg: dict):
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass


# ─────────────────────────── 应用主类 ───────────────────────────
class ClipboardManagerApp:
    def __init__(self):
        ensure_dirs()
        self.app = QApplication(sys.argv)
        self.app.setApplicationName(APP_NAME)
        self.app.setQuitOnLastWindowClosed(False)

        self.config = load_config()
        self.history = HistoryStore(
            max_count=self.config["max_count"],
            max_days=self.config["max_days"]
        )
        self.permanent = PermanentStore()
        self.window = MainWindow(self.history, self.permanent, self.config)

        # 托盘图标
        self._setup_tray()

        # 剪贴板监控
        self.monitor = ClipboardMonitor()
        self.monitor.new_entry.connect(self._on_new_clip)
        self.monitor.start()

        # 全局快捷键 (已修复跨线程卡死问题)
        self.hotkey_mgr = GlobalHotkeyManager()
        self.hotkey_mgr.signal_alt_v.connect(self._toggle_window)  # 连接到主线程槽函数
        self.hotkey_mgr.signal_ctrl_g.connect(self._toggle_mode)
        self.hotkey_mgr.start_listening()

    def _setup_tray(self):
        # 创建简单图标
        pixmap = QPixmap(32, 32)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor("#4a90d9"))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(2, 2, 28, 28, 6, 6)
        painter.setPen(QColor("white"))
        painter.setFont(QFont("Arial", 16, QFont.Bold))
        painter.drawText(pixmap.rect(), Qt.AlignCenter, "C")
        painter.end()

        self.tray = QSystemTrayIcon(QIcon(pixmap), self.app)
        self.tray.setToolTip("剪贴板管理器\nAlt+V 打开")

        menu = QMenu()
        menu.setStyleSheet("""
            QMenu { background: #1e1e38; color: #d0d0f0; border: 1px solid #3a3a6e; }
            QMenu::item:selected { background: #2d2d6e; }
        """)

        show_action = QAction("📋 显示历史 (Alt+V)", menu)
        show_action.triggered.connect(self._toggle_window)
        menu.addAction(show_action)

        menu.addSeparator()

        cleanup_action = QAction("🧹 立即清理历史", menu)
        cleanup_action.triggered.connect(self._force_cleanup)
        menu.addAction(cleanup_action)

        settings_action = QAction("⚙ 设置", menu)
        settings_action.triggered.connect(self.window.open_settings)
        menu.addAction(settings_action)

        menu.addSeparator()

        quit_action = QAction("✕ 退出", menu)
        quit_action.triggered.connect(self._quit)
        menu.addAction(quit_action)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self._toggle_window()

    def _toggle_window(self):
        if self.window.isVisible():
            self.window.hide()
        else:
            self.window.refresh()
            self.window.show()
            self.window.raise_()
            self.window.activateWindow()
            self.window.search_box.setFocus()

    def _toggle_mode(self):
        if not self.window.isVisible():
            self.window.show()
            self.window.raise_()
            self.window.activateWindow()
        self.window.toggle_mode()

    def _on_new_clip(self, entry: ClipEntry):
        added = self.history.add(entry)
        if self.window.isVisible():
            self.window.refresh()

    def _force_cleanup(self):
        self.history.force_cleanup()
        if self.window.isVisible():
            self.window.refresh()
        self.tray.showMessage("剪贴板管理器", "历史清理完成", QSystemTrayIcon.Information, 2000)

    def _quit(self):
        self.monitor.stop()
        self.hotkey_mgr.stop()
        self.permanent.close()
        self.app.quit()

    def run(self):
        self.tray.showMessage(
            "剪贴板管理器",
            "已启动！按 Alt+V 打开历史面板",
            QSystemTrayIcon.Information,
            3000
        )
        sys.exit(self.app.exec_())


# ─────────────────────────── 入口 ───────────────────────────
if __name__ == "__main__":
    app = ClipboardManagerApp()
    app.run()
