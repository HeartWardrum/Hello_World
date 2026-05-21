"""
轻量级剪贴板管理工具 - Clipboard Manager (修复版)
修复：
  1. ClipboardMonitor 通过信号机制在主线程访问剪贴板，避免跨线程崩溃
  2. 图片缩略图异步生成，不阻塞 UI 刷新
  3. _refresh_list 去抖动，避免搜索每次输入都全量重建
  4. GlobalHotkeyManager 用 PostThreadMessage 安全退出，不永久阻塞
  5. nativeEvent 改用 QApplication.focusChanged + event filter，彻底绕开 Win11 原生指针问题
"""

import sys
import os
import json
import sqlite3
import hashlib
import time
import threading
import datetime
from io import BytesIO
import ctypes
from ctypes import wintypes

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QListWidget, QListWidgetItem, QLineEdit, QPushButton, QLabel,
    QSystemTrayIcon, QMenu, QAction, QSizePolicy,
    QMessageBox, QDialog, QCheckBox, QSpinBox, QFormLayout,
)
from PyQt5.QtCore import (
    Qt, QThread, pyqtSignal, QTimer, QSize, QPoint, QSettings, QEvent, QRunnable, QThreadPool, pyqtSlot, QObject
)
from PyQt5.QtGui import (
    QIcon, QPixmap, QImage, QColor, QPainter, QFont, QCursor,
)

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    print("警告: Pillow未安装，图片支持受限")

try:
    from pynput import keyboard as pynput_keyboard
    PYNPUT_AVAILABLE = True
except ImportError:
    PYNPUT_AVAILABLE = False

try:
    import pyautogui
    PYAUTOGUI_AVAILABLE = True
except ImportError:
    PYAUTOGUI_AVAILABLE = False


APP_NAME = "ClipboardManager"
DATA_DIR = os.path.join(os.path.expanduser("~"), ".clipboard_manager")
HISTORY_FILE = os.path.join(DATA_DIR, "history.json")
DB_FILE = os.path.join(DATA_DIR, "permanent.db")
IMAGES_DIR = os.path.join(DATA_DIR, "images")
THUMBNAIL_SIZE = (120, 80)
MAX_TEXT_PREVIEW = 200
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")

DEFAULT_CONFIG = {
    "max_count": 100,
    "max_days": 30,
    "focus_hide": True,
}


def ensure_dirs():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(IMAGES_DIR, exist_ok=True)


def compute_md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def pil_to_qpixmap(pil_img) -> QPixmap:
    pil_img = pil_img.convert("RGBA")
    data = pil_img.tobytes("raw", "RGBA")
    qimg = QImage(data, pil_img.width, pil_img.height, QImage.Format_RGBA8888)
    return QPixmap.fromImage(qimg)


def make_thumbnail(pil_img, size=THUMBNAIL_SIZE):
    img = pil_img.copy()
    img.thumbnail(size, Image.LANCZOS)
    return img


def now_ts() -> float:
    return time.time()


def ts_to_str(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts).strftime("%m-%d %H:%M")


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


# ─────────────────────────── 数据模型 ───────────────────────────
class ClipEntry:
    def __init__(self, entry_type: str, content, timestamp: float = None,
                 entry_id: str = None, note: str = ""):
        self.type = entry_type
        self.content = content
        self.timestamp = timestamp or now_ts()
        self.id = entry_id or compute_md5(
            (str(self.timestamp) + str(content[:50] if isinstance(content, str) else content[:50])).encode()
        )
        self.note = note

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
    def __init__(self, max_count=100, max_days=30):
        self.max_count = max_count
        self.max_days = max_days
        self._entries: list = []
        self._hash_map: dict = {}
        self.load()

    def add(self, entry: ClipEntry) -> bool:
        h = entry.get_hash()
        if h in self._hash_map:
            idx = self._hash_map[h]
            old = self._entries.pop(idx)
            old.timestamp = entry.timestamp
            self._entries.insert(0, old)
            self._rebuild_hash_map()
            self.save()
            return False
        self._entries.insert(0, entry)
        self._hash_map[h] = 0
        self._rebuild_hash_map()
        self._cleanup()
        self.save()
        return True

    def remove(self, entry_id: str):
        self._entries = [e for e in self._entries if e.id != entry_id]
        self._rebuild_hash_map()
        self.save()

    def clear_all(self):
        self._entries.clear()
        self._hash_map.clear()
        self.save()

    def get_all(self) -> list:
        return list(self._entries)

    def search(self, keyword: str) -> list:
        kw = keyword.lower()
        return [e for e in self._entries
                if (e.type == "text" and kw in e.content.lower()) or
                   (e.type == "image" and kw in (e.note or "").lower())]

    def _rebuild_hash_map(self):
        self._hash_map = {}
        for i, e in enumerate(self._entries):
            self._hash_map[e.get_hash()] = i

    def _cleanup(self):
        if self.max_count > 0 and len(self._entries) > self.max_count:
            removed = self._entries[self.max_count:]
            self._entries = self._entries[:self.max_count]
            for e in removed:
                if e.type == "image":
                    self._delete_image_file(e)
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

    def save(self):
        data = []
        for e in self._entries:
            item = {"id": e.id, "type": e.type, "timestamp": e.timestamp, "note": e.note}
            if e.type == "text":
                item["content"] = e.content
            else:
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
        h = entry.get_hash()
        with self._lock:
            cur = self._conn.execute("SELECT id FROM permanent WHERE id=?", (h,))
            row = cur.fetchone()
            if row:
                self._conn.execute("UPDATE permanent SET timestamp=? WHERE id=?", (now_ts(), h))
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
        return [e for e in self.get_all()
                if (e.type == "text" and kw in e.content.lower()) or
                   (e.type == "image" and kw in (e.note or "").lower())]

    def close(self):
        self._conn.close()


# ─────────────────────────── 剪贴板监控线程（修复版）───────────────────────────
class ClipboardChecker(QObject):
    """运行在主线程，由定时器驱动，安全访问剪贴板"""
    new_entry = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._last_hash = ""
        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._check)

    def start(self):
        self._timer.start()

    def stop(self):
        self._timer.stop()

    def _check(self):
        try:
            cb = QApplication.clipboard()
            mime = cb.mimeData()

            if mime.hasImage():
                qimg = cb.image()
                if not qimg.isNull() and PIL_AVAILABLE:
                    qimg_conv = qimg.convertToFormat(QImage.Format_RGBA8888)
                    ptr = qimg_conv.bits()
                    ptr.setsize(qimg_conv.byteCount())
                    pil = Image.frombytes("RGBA", (qimg_conv.width(), qimg_conv.height()), bytes(ptr))
                    ba = BytesIO()
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
        except Exception as ex:
            print(f"剪贴板检测异常: {ex}")


# ─────────────────────────── 异步缩略图加载 ───────────────────────────
class ThumbnailSignals(QObject):
    done = pyqtSignal(str, QPixmap)   # entry_id, pixmap


class ThumbnailLoader(QRunnable):
    def __init__(self, entry_id: str, data: bytes, signals: ThumbnailSignals):
        super().__init__()
        self.entry_id = entry_id
        self.data = data
        self.signals = signals
        self.setAutoDelete(True)

    @pyqtSlot()
    def run(self):
        try:
            ba = BytesIO(self.data)
            pil = Image.open(ba)
            thumb = make_thumbnail(pil)
            pixmap = pil_to_qpixmap(thumb)
            self.signals.done.emit(self.entry_id, pixmap)
        except Exception:
            pass


# ─────────────────────────── 条目Widget ───────────────────────────
class EntryItemWidget(QWidget):
    def __init__(self, entry: ClipEntry, parent=None):
        super().__init__(parent)
        self.entry = entry
        self._thumb_lbl = None
        self._build_ui()

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(10)

        if self.entry.type == "image":
            self._thumb_lbl = QLabel("🖼")
            self._thumb_lbl.setFixedSize(QSize(*THUMBNAIL_SIZE))
            self._thumb_lbl.setAlignment(Qt.AlignCenter)
            self._thumb_lbl.setStyleSheet("color:#888;font-size:24px;")
            layout.addWidget(self._thumb_lbl)
        else:
            icon_lbl = QLabel("📋")
            icon_lbl.setFixedWidth(28)
            icon_lbl.setAlignment(Qt.AlignCenter)
            layout.addWidget(icon_lbl)

        right = QVBoxLayout()
        right.setSpacing(4)
        preview = QLabel(self.entry.get_preview())
        preview.setWordWrap(True)
        preview.setMaximumHeight(75)
        preview.setStyleSheet("color: #e0e0e0; font-size: 15px;")
        time_lbl = QLabel(ts_to_str(self.entry.timestamp))
        time_lbl.setStyleSheet("color: #888; font-size: 12px;")
        right.addWidget(preview)
        right.addWidget(time_lbl)
        layout.addLayout(right, 1)

    def set_thumbnail(self, pixmap: QPixmap):
        if self._thumb_lbl:
            self._thumb_lbl.setPixmap(pixmap.scaled(
                QSize(*THUMBNAIL_SIZE), Qt.KeepAspectRatio, Qt.SmoothTransformation))


# ─────────────────────────── 全局快捷键 ───────────────────────────
class GlobalHotkeyManager(QThread):
    signal_alt_v = pyqtSignal()
    signal_ctrl_g = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._running = True
        self.user32 = ctypes.windll.user32
        self.HOTKEY_ALT_V_ID = 1001
        self.HOTKEY_CTRL_G_ID = 1002
        self.MOD_ALT = 0x0001
        self.MOD_CONTROL = 0x0002
        self.VK_V = 0x56
        self.VK_G = 0x47
        self._thread_id = None

    def start_listening(self):
        self.daemon = True
        self.start()

    def run(self):
        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        res1 = self.user32.RegisterHotKey(None, self.HOTKEY_ALT_V_ID, self.MOD_ALT, self.VK_V)
        res2 = self.user32.RegisterHotKey(None, self.HOTKEY_CTRL_G_ID, self.MOD_CONTROL, self.VK_G)
        if not res1 or not res2:
            print("警告: 全局热键注册失败")

        msg = wintypes.MSG()
        while self._running:
            # 使用 PeekMessage 替代 GetMessage，避免永久阻塞
            ret = self.user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1)  # PM_REMOVE=1
            if ret != 0:
                if msg.message == 0x0312:   # WM_HOTKEY
                    if msg.wParam == self.HOTKEY_ALT_V_ID:
                        self.signal_alt_v.emit()
                    elif msg.wParam == self.HOTKEY_CTRL_G_ID:
                        self.signal_ctrl_g.emit()
                elif msg.message == 0x0012:  # WM_QUIT → 安全退出
                    break
                self.user32.TranslateMessage(ctypes.byref(msg))
                self.user32.DispatchMessageW(ctypes.byref(msg))
            else:
                self.msleep(10)  # 空闲时 yield CPU，不让此线程空转

    def stop(self):
        self._running = False
        # 向热键线程发送 WM_QUIT，安全唤醒 PeekMessage 循环
        if self._thread_id:
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, 0x0012, 0, 0)
        self.user32.UnregisterHotKey(None, self.HOTKEY_ALT_V_ID)
        self.user32.UnregisterHotKey(None, self.HOTKEY_CTRL_G_ID)
        self.wait(2000)  # 最多等 2 秒，不永久阻塞


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
    def __init__(self, history: HistoryStore, permanent: PermanentStore, config: dict):
        super().__init__()
        self.history = history
        self.permanent = permanent
        self.config = config
        self._mode = "history"
        self._search_keyword = ""
        self._thumb_signals = ThumbnailSignals()
        self._thumb_signals.done.connect(self._on_thumbnail_ready)
        self._thumb_pool = QThreadPool.globalInstance()
        self._thumb_pool.setMaxThreadCount(4)
        # entry_id -> list widget item（用于回填缩略图）
        self._item_map: dict = {}

        # 去抖动：搜索框输入 300ms 后才真正刷新
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(300)
        self._search_timer.timeout.connect(self._do_refresh)

        self.setWindowTitle("📋 剪贴板管理器 - 普通历史")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(600, 750)
        self._center_screen()
        self._build_ui()
        self._apply_style()

    # ── 失焦隐藏：用 Qt 自带信号，完全避开 nativeEvent ──
    def _setup_focus_watcher(self):
        QApplication.instance().focusChanged.connect(self._on_focus_changed)

    def _on_focus_changed(self, old, now):
        if not self.config.get("focus_hide", True):
            return
        if not self.isVisible():
            return
        # 如果新焦点窗口不是本窗口的子控件，则隐藏
        if now is None or (now.window() is not self and not isinstance(now.window(), QDialog)):
            # 用 singleShot 延迟，避免弹右键菜单时误隐藏
            QTimer.singleShot(150, self._maybe_hide)

    def _maybe_hide(self):
        if not self.isActiveWindow():
            # 检查是否有模态对话框
            if not (QApplication.activeModalWidget() or QApplication.activePopupWidget()):
                self.hide()

    def _center_screen(self):
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.width() - self.width() - 40,
                  (screen.height() - self.height()) // 2)

    def _build_ui(self):
        central = QWidget()
        central.setObjectName("centralWidget")
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(8)

        title_bar = QHBoxLayout()
        self.title_label = QLabel("📋 普通历史")
        self.title_label.setObjectName("titleLabel")
        title_bar.addWidget(self.title_label)
        title_bar.addStretch()

        self.toggle_btn = QPushButton("⭐ 永久保存")
        self.toggle_btn.setObjectName("toggleBtn")
        self.toggle_btn.clicked.connect(self.toggle_mode)
        title_bar.addWidget(self.toggle_btn)

        settings_btn = QPushButton("⚙")
        settings_btn.setObjectName("iconBtn")
        settings_btn.setFixedSize(28, 28)
        settings_btn.clicked.connect(self.open_settings)
        title_bar.addWidget(settings_btn)

        close_btn = QPushButton("✕")
        close_btn.setObjectName("closeBtn")
        close_btn.setFixedSize(28, 28)
        close_btn.clicked.connect(self.hide)
        title_bar.addWidget(close_btn)

        main_layout.addLayout(title_bar)

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("🔍 搜索...")
        self.search_box.setObjectName("searchBox")
        self.search_box.textChanged.connect(self._on_search)
        self.search_box.installEventFilter(self)
        main_layout.addWidget(self.search_box)

        self.list_widget = QListWidget()
        self.list_widget.setObjectName("listWidget")
        self.list_widget.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list_widget.setSpacing(2)
        self.list_widget.itemClicked.connect(self._on_item_clicked)
        self.list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._on_context_menu)
        self.list_widget.installEventFilter(self)
        main_layout.addWidget(self.list_widget)

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
        self._setup_focus_watcher()

    def _apply_style(self):
        self.setStyleSheet("""
            QMainWindow { background: transparent; }
            #centralWidget {
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 #1a1a2e, stop:1 #16213e);
                border-radius: 14px;
                border: 1px solid #2a2a5e;
            }
            #titleLabel { color: #a0c4ff; font-size: 15px; font-weight: bold;
                          font-family: 'Microsoft YaHei', 'PingFang SC', sans-serif; }
            #toggleBtn { background: #2a2a5e; color: #ffd700; border: 1px solid #3a3a7e;
                         border-radius: 6px; padding: 4px 10px; font-size: 12px; }
            #toggleBtn:hover { background: #3a3a8e; }
            #iconBtn, #closeBtn { background: #1e1e3a; color: #888; border: 1px solid #333;
                                  border-radius: 6px; font-size: 13px; }
            #iconBtn:hover { background: #2a2a4a; color: #aaa; }
            #closeBtn:hover { background: #8b2020; color: #fff; }
            #searchBox { background: #1e1e38; color: #d0d0f0; border: 1px solid #3a3a6e;
                         border-radius: 8px; padding: 6px 12px; font-size: 13px; }
            #searchBox:focus { border-color: #5a5aae; }
            #listWidget { background: #12122a; border: 1px solid #2a2a4e;
                          border-radius: 8px; outline: none; }
            #listWidget::item { border-radius: 6px; margin: 1px 4px; }
            #listWidget::item:selected { background: #2d2d6e; }
            #listWidget::item:hover { background: #20204a; }
            QScrollBar:vertical { background: #1a1a30; width: 6px; border-radius: 3px; }
            QScrollBar::handle:vertical { background: #4a4a8e; border-radius: 3px; min-height: 20px; }
            #statusLabel { color: #666; font-size: 11px; }
            #dangerBtn { background: #3a1a1a; color: #ff8888; border: 1px solid #6a2a2a;
                         border-radius: 6px; padding: 3px 8px; font-size: 11px; }
            #dangerBtn:hover { background: #6a2020; }
        """)

    def toggle_mode(self):
        if self._mode == "history":
            self._mode = "permanent"
            self.title_label.setText("⭐ 永久保存")
            self.toggle_btn.setText("📋 普通历史")
        else:
            self._mode = "history"
            self.title_label.setText("📋 普通历史")
            self.toggle_btn.setText("⭐ 永久保存")
        self._refresh_list()

    def _refresh_list(self):
        self._do_refresh()

    def _on_search(self, text: str):
        self._search_keyword = text.strip()
        self._search_timer.start()  # 去抖动，300ms 后执行

    def _do_refresh(self):
        kw = self._search_keyword
        if self._mode == "history":
            entries = self.history.search(kw) if kw else self.history.get_all()
        else:
            entries = self.permanent.search(kw) if kw else self.permanent.get_all()

        self.list_widget.clear()
        self._item_map.clear()

        for entry in entries:
            item = QListWidgetItem()
            widget = EntryItemWidget(entry)
            item.setSizeHint(QSize(self.list_widget.width() - 10,
                                   140 if entry.type == "image" else 95))
            item.setData(Qt.UserRole, entry)
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, widget)
            self._item_map[entry.id] = (item, widget)

            # 异步加载图片缩略图
            if entry.type == "image" and PIL_AVAILABLE:
                loader = ThumbnailLoader(entry.id, entry.content, self._thumb_signals)
                self._thumb_pool.start(loader)

        count = len(entries)
        mode_str = "普通历史" if self._mode == "history" else "永久保存"
        self.status_label.setText(f"{mode_str}: {count} 条")

        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)

    def _on_thumbnail_ready(self, entry_id: str, pixmap: QPixmap):
        pair = self._item_map.get(entry_id)
        if pair:
            _, widget = pair
            widget.set_thumbnail(pixmap)

    def refresh(self):
        self._refresh_list()

    def _on_item_clicked(self, item: QListWidgetItem):
        entry = item.data(Qt.UserRole)
        self._paste_entry(entry)

    def _paste_entry(self, entry: ClipEntry, as_plain_text=False):
        cb = QApplication.clipboard()
        if as_plain_text:
            cb.setText(entry.content if entry.type == "text" else (entry.note or "[图片]"))
        else:
            if entry.type == "text":
                cb.setText(entry.content)
            else:
                try:
                    ba = BytesIO(entry.content)
                    pil = Image.open(ba)
                    pixmap = pil_to_qpixmap(pil)
                    cb.setPixmap(pixmap)
                except Exception:
                    return
        self.hide()
        QTimer.singleShot(150, self._simulate_paste)

    def _simulate_paste(self):
        if PYAUTOGUI_AVAILABLE:
            try:
                pyautogui.hotkey("ctrl", "v")
                return
            except Exception:
                pass
        if PYNPUT_AVAILABLE:
            try:
                from pynput.keyboard import Key, Controller
                kc = Controller()
                with kc.pressed(Key.ctrl):
                    kc.press("v")
                    kc.release("v")
            except Exception:
                pass

    def _on_context_menu(self, pos: QPoint):
        item = self.list_widget.itemAt(pos)
        if not item:
            return
        entry = item.data(Qt.UserRole)
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

    def eventFilter(self, obj, event):
        if event.type() == QEvent.KeyPress:
            key = event.key()
            if key in (Qt.Key_Up, Qt.Key_Down):
                count = self.list_widget.count()
                if count > 0:
                    current_row = self.list_widget.currentRow()
                    next_row = current_row + (1 if key == Qt.Key_Down else -1)
                    next_row = max(0, min(next_row, count - 1))
                    self.list_widget.setCurrentRow(next_row)
                    self.list_widget.scrollToItem(self.list_widget.currentItem())
                return True
            elif key in (Qt.Key_Return, Qt.Key_Enter):
                current_item = self.list_widget.currentItem()
                if current_item:
                    entry = current_item.data(Qt.UserRole)
                    self._paste_entry(entry, as_plain_text=(event.modifiers() == Qt.ShiftModifier))
                return True
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.hide()
        elif event.key() == Qt.Key_G and event.modifiers() == Qt.ControlModifier:
            self.toggle_mode()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPos() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton and hasattr(self, "_drag_pos"):
            self.move(event.globalPos() - self._drag_pos)


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

        self._setup_tray()

        # 修复：剪贴板监控在主线程用 QTimer 驱动
        self.monitor = ClipboardChecker()
        self.monitor.new_entry.connect(self._on_new_clip)
        self.monitor.start()

        # 全局快捷键
        self.hotkey_mgr = GlobalHotkeyManager()
        self.hotkey_mgr.signal_alt_v.connect(self._toggle_window)
        self.hotkey_mgr.signal_ctrl_g.connect(self._toggle_mode)
        self.hotkey_mgr.start_listening()

    def _setup_tray(self):
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
        self.history.add(entry)
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


if __name__ == "__main__":
    app = ClipboardManagerApp()
    app.run()
