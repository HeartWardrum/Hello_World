"""
轻量级剪贴板管理工具 v2 - 性能优化版
优化项：
  1. 启动提速：HistoryStore 懒加载图片（只存路径，按需读取）
  2. 唤起提速：Alt+V 先 show 再刷新；列表增量 prepend/移除；可见区缩略图懒加载
  3. 鼠标位置唤起：窗口出现在当前鼠标旁边，自动适应屏幕边缘
  4. 剪贴板轮询降频至 800ms（可配置），避免与 UI 抢资源
  5. 图片内容懒读取（只有粘贴/预览时才真正读文件）
  6. 搜索去抖动从 300ms→200ms，提升响应感
  7. PermanentStore 使用 WAL 模式，降低 SQLite 锁开销
  8. 数据未变时跳过列表重建
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
    Qt, QThread, pyqtSignal, QTimer, QSize, QPoint, QSettings, QEvent,
    QRunnable, QThreadPool, pyqtSlot, QObject, QRect
)
from PyQt5.QtGui import (
    QIcon, QPixmap, QImage, QColor, QPainter, QFont, QCursor,
)

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

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
    "poll_ms": 800,          # 新增：剪贴板轮询间隔（毫秒）
    "window_w": 560,
    "window_h": 680,
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
    """
    优化：图片 entry 只存文件路径，按需读取 bytes，避免启动时全量加载到内存
    _content_bytes 是懒加载缓存
    """
    def __init__(self, entry_type: str, content, timestamp: float = None,
                 entry_id: str = None, note: str = "", image_path: str = ""):
        self.type = entry_type
        self.note = note
        self.timestamp = timestamp or now_ts()
        self._image_path = image_path  # 图片走懒加载路径

        if entry_type == "image" and image_path:
            # 懒加载：只存路径，不读文件
            self.content = None          # 懒加载占位
            self._lazy = True
            self._hash_cache = compute_md5(image_path.encode())  # 用路径做临时 hash
        else:
            self.content = content
            self._lazy = False
            self._hash_cache = None

        self.id = entry_id or compute_md5(
            (str(self.timestamp) + (image_path or str(content)[:50] if isinstance(content, str) else "")).encode()
        )

    def _ensure_loaded(self):
        """按需读取图片文件"""
        if self._lazy and self.content is None:
            if os.path.exists(self._image_path):
                try:
                    with open(self._image_path, "rb") as f:
                        self.content = f.read()
                    self._hash_cache = compute_md5(self.content)
                    self._lazy = False
                except Exception:
                    self.content = b""

    def get_content(self):
        """获取内容，图片触发懒加载"""
        if self.type == "image":
            self._ensure_loaded()
        return self.content

    def get_hash(self) -> str:
        if self._hash_cache:
            return self._hash_cache
        if self.type == "text":
            self._hash_cache = compute_md5(self.content.encode("utf-8"))
        else:
            self._ensure_loaded()
            self._hash_cache = compute_md5(self.content or b"")
        return self._hash_cache

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
        self._dirty = False   # 标记数据是否变化，控制 UI 是否需要刷新
        self.load()

    def add(self, entry: ClipEntry) -> bool:
        h = entry.get_hash()
        if h in self._hash_map:
            idx = self._hash_map[h]
            old = self._entries.pop(idx)
            old.timestamp = entry.timestamp
            self._entries.insert(0, old)
            self._rebuild_hash_map()
            self._dirty = True
            self.save()
            return False
        self._entries.insert(0, entry)
        self._hash_map[h] = 0
        self._rebuild_hash_map()
        self._cleanup()
        self._dirty = True
        self.save()
        return True

    def consume_dirty(self) -> bool:
        """检查并消费 dirty 标记"""
        d = self._dirty
        self._dirty = False
        return d

    def remove(self, entry_id: str):
        self._entries = [e for e in self._entries if e.id != entry_id]
        self._rebuild_hash_map()
        self._dirty = True
        self.save()

    def clear_all(self):
        self._entries.clear()
        self._hash_map.clear()
        self._dirty = True
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
        path = entry._image_path or os.path.join(IMAGES_DIR, f"hist_{entry.id}.png")
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
                # 确定图片路径
                path = e._image_path or os.path.join(IMAGES_DIR, f"hist_{e.id}.png")
                if not os.path.exists(path):
                    # 需要写入文件（新抓到的图片，content 已在内存）
                    raw = e.get_content()
                    if raw:
                        try:
                            with open(path, "wb") as f:
                                f.write(raw)
                            e._image_path = path
                        except Exception:
                            continue
                    else:
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
                    # ★ 关键优化：不读文件，只存路径，懒加载
                    e = ClipEntry("image", None, item["timestamp"],
                                  item["id"], item.get("note", ""),
                                  image_path=path)
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
        # ★ WAL 模式：减少锁争用，读写并发更高
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")

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
        content = entry.get_content() if entry.type == "image" else entry.content.encode("utf-8")
        with self._lock:
            cur = self._conn.execute("SELECT id FROM permanent WHERE id=?", (h,))
            if cur.fetchone():
                self._conn.execute("UPDATE permanent SET timestamp=? WHERE id=?", (now_ts(), h))
                self._conn.commit()
                return False
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
                e = ClipEntry(etype, content_decoded, ts, eid, note or "")
            else:
                e = ClipEntry(etype, bytes(content), ts, eid, note or "")
            result.append(e)
        return result

    def search(self, keyword: str) -> list:
        kw = keyword.lower()
        return [e for e in self.get_all()
                if (e.type == "text" and kw in e.content.lower()) or
                   (e.type == "image" and kw in (e.note or "").lower())]

    def close(self):
        self._conn.close()


# ─────────────────────────── 剪贴板监控（主线程 QTimer）───────────────────────────
class ClipboardChecker(QObject):
    new_entry = pyqtSignal(object)

    def __init__(self, poll_ms=800, parent=None):
        super().__init__(parent)
        self._last_hash = ""
        self._poll_ms = poll_ms
        self._timer = QTimer(self)
        self._timer.setInterval(poll_ms)
        self._timer.timeout.connect(self._check)

    def set_poll_ms(self, ms: int):
        self._poll_ms = ms
        self._timer.setInterval(ms)

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
    done = pyqtSignal(str, QPixmap)


class ThumbnailLoader(QRunnable):
    def __init__(self, entry_id: str, entry: ClipEntry, signals: ThumbnailSignals):
        super().__init__()
        self.entry_id = entry_id
        self.entry = entry
        self.signals = signals
        self.setAutoDelete(True)

    @pyqtSlot()
    def run(self):
        try:
            data = self.entry.get_content()   # 懒加载：在工作线程里读文件
            if not data:
                return
            ba = BytesIO(data)
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

    def __init__(self):
        super().__init__()
        self._running = True
        self.user32 = ctypes.windll.user32
        self.HOTKEY_ALT_V_ID = 1001
        self.MOD_ALT = 0x0001
        self.VK_V = 0x56
        self._thread_id = None

    def start_listening(self):
        self.daemon = True
        self.start()

    def run(self):
        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        res1 = self.user32.RegisterHotKey(None, self.HOTKEY_ALT_V_ID, self.MOD_ALT, self.VK_V)
        if not res1:
            print("警告: 全局热键 Alt+V 注册失败（可能已被其他程序占用）")

        msg = wintypes.MSG()
        while self._running:
            ret = self.user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1)
            if ret != 0:
                if msg.message == 0x0312:
                    if msg.wParam == self.HOTKEY_ALT_V_ID:
                        self.signal_alt_v.emit()
                elif msg.message == 0x0012:
                    break
                self.user32.TranslateMessage(ctypes.byref(msg))
                self.user32.DispatchMessageW(ctypes.byref(msg))
            else:
                self.msleep(10)

    def stop(self):
        self._running = False
        if self._thread_id:
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, 0x0012, 0, 0)
        self.user32.UnregisterHotKey(None, self.HOTKEY_ALT_V_ID)
        self.wait(2000)


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

        self.poll_spin = QSpinBox()
        self.poll_spin.setRange(200, 5000)
        self.poll_spin.setSingleStep(100)
        self.poll_spin.setValue(self.config.get("poll_ms", 800))
        self.poll_spin.setSuffix(" ms")
        form.addRow("监控轮询间隔:", self.poll_spin)

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
        self.config["poll_ms"] = self.poll_spin.value()
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
        self._item_map: dict = {}      # entry_id -> (item, widget)
        self._current_ids: list = []   # 当前列表顺序（用于增量对比）
        self._thumb_loaded: set = set()
        self._thumb_loading: set = set()

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(200)   # ★ 从 300 降到 200ms
        self._search_timer.timeout.connect(self._do_refresh)

        w = config.get("window_w", 560)
        h = config.get("window_h", 680)
        self.setWindowTitle("📋 剪贴板管理器 - 普通历史")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(w, h)
        self._build_ui()
        self._apply_style()

    # ── 失焦隐藏 ──
    def _setup_focus_watcher(self):
        QApplication.instance().focusChanged.connect(self._on_focus_changed)

    def _on_focus_changed(self, old, now):
        if not self.config.get("focus_hide", True):
            return
        if not self.isVisible():
            return
        if now is None or (now.window() is not self and not isinstance(now.window(), QDialog)):
            QTimer.singleShot(150, self._maybe_hide)

    def _maybe_hide(self):
        if not self.isActiveWindow():
            if not (QApplication.activeModalWidget() or QApplication.activePopupWidget()):
                self.hide()

    # ── ★ 关键：定位到鼠标附近并自动防止超出屏幕 ──
    def _position_near_cursor(self):
        cursor_pos = QCursor.pos()
        screen = QApplication.screenAt(cursor_pos)
        if screen is None:
            screen = QApplication.primaryScreen()
        avail: QRect = screen.availableGeometry()

        w, h = self.width(), self.height()
        # 默认：鼠标右下方偏移 10px
        x = cursor_pos.x() + 10
        y = cursor_pos.y() + 10

        # 防止超出屏幕右边
        if x + w > avail.right():
            x = cursor_pos.x() - w - 10
        # 防止超出屏幕下边
        if y + h > avail.bottom():
            y = cursor_pos.y() - h - 10
        # 最终保证在屏幕内
        x = max(avail.left(), min(x, avail.right() - w))
        y = max(avail.top(), min(y, avail.bottom() - h))

        self.move(x, y)

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
        # ★ 批量模式：减少 layoutChanged 触发次数
        self.list_widget.setUniformItemSizes(False)
        self.list_widget.itemClicked.connect(self._on_item_clicked)
        self.list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._on_context_menu)
        self.list_widget.installEventFilter(self)
        self.list_widget.verticalScrollBar().valueChanged.connect(
            lambda _: self._schedule_visible_thumbnails()
        )
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
        self._current_ids = []   # 强制完整重建
        self._refresh_list()

    def _refresh_list(self):
        self._do_refresh()

    def _on_search(self, text: str):
        self._search_keyword = text.strip()
        self._search_timer.start()

    def _entry_row_height(self, entry: ClipEntry) -> int:
        return 140 if entry.type == "image" else 95

    def _update_status(self, count: int):
        mode_str = "普通历史" if self._mode == "history" else "永久保存"
        self.status_label.setText(f"{mode_str}: {count} 条")

    def _insert_entry_at(self, row: int, entry: ClipEntry) -> QListWidgetItem:
        item = QListWidgetItem()
        item.setSizeHint(QSize(max(self.list_widget.width() - 10, 200),
                               self._entry_row_height(entry)))
        item.setData(Qt.UserRole, entry)
        if row < 0:
            self.list_widget.addItem(item)
        else:
            self.list_widget.insertItem(row, item)
        widget = EntryItemWidget(entry)
        self.list_widget.setItemWidget(item, widget)
        self._item_map[entry.id] = (item, widget)
        return item

    def _prepend_entry(self, entry: ClipEntry):
        self._insert_entry_at(0, entry)
        self.list_widget.setCurrentRow(0)

    def _remove_entry_by_id(self, entry_id: str):
        pair = self._item_map.pop(entry_id, None)
        if not pair:
            return
        item, widget = pair
        row = self.list_widget.row(item)
        if row >= 0:
            self.list_widget.takeItem(row)
        widget.deleteLater()
        self._thumb_loaded.discard(entry_id)
        self._thumb_loading.discard(entry_id)

    def _move_entry_to_top(self, entry_id: str, entry: ClipEntry):
        pair = self._item_map.get(entry_id)
        if not pair:
            self._prepend_entry(entry)
            return
        item, old_widget = pair
        row = self.list_widget.row(item)
        if row <= 0:
            item.setData(Qt.UserRole, entry)
            return
        self.list_widget.removeItemWidget(item)
        taken = self.list_widget.takeItem(row)
        old_widget.deleteLater()
        taken.setData(Qt.UserRole, entry)
        self.list_widget.insertItem(0, taken)
        widget = EntryItemWidget(entry)
        self.list_widget.setItemWidget(taken, widget)
        self._item_map[entry_id] = (taken, widget)
        self._thumb_loaded.discard(entry_id)
        self.list_widget.setCurrentRow(0)

    def _try_incremental_sync(self, entries: list, new_ids: list) -> bool:
        old_ids = self._current_ids
        if not old_ids:
            return False

        # 顶部新增（常见：复制新内容）
        if (new_ids and new_ids[0] not in old_ids and
                new_ids[1:] == old_ids[:len(new_ids) - 1]):
            self._prepend_entry(entries[0])
            self._current_ids = new_ids
            self._update_status(len(entries))
            return True

        # 重复内容移到顶部
        if (new_ids and new_ids[0] in old_ids and
                new_ids[1:] == [i for i in old_ids if i != new_ids[0]]):
            self._move_entry_to_top(new_ids[0], entries[0])
            self._current_ids = new_ids
            self._update_status(len(entries))
            return True

        # 尾部裁剪（超出 max_count / 过期清理）
        if len(new_ids) < len(old_ids) and new_ids == old_ids[:len(new_ids)]:
            while len(self._current_ids) > len(new_ids):
                self._remove_entry_by_id(self._current_ids[-1])
            self._current_ids = new_ids
            self._update_status(len(entries))
            return True

        # 单条删除
        if len(new_ids) == len(old_ids) - 1:
            removed = set(old_ids) - set(new_ids)
            if len(removed) == 1 and new_ids == [i for i in old_ids if i not in removed]:
                self._remove_entry_by_id(removed.pop())
                self._current_ids = new_ids
                self._update_status(len(entries))
                return True

        return False

    def _full_rebuild_list(self, entries: list, new_ids: list):
        self.list_widget.setUpdatesEnabled(False)
        self.list_widget.clear()
        self._item_map.clear()
        self._thumb_loaded.clear()
        self._thumb_loading.clear()

        for entry in entries:
            self._insert_entry_at(-1, entry)

        self.list_widget.setUpdatesEnabled(True)
        self._current_ids = new_ids
        self._update_status(len(entries))

        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)
        self._schedule_visible_thumbnails()

    def _schedule_visible_thumbnails(self):
        if not PIL_AVAILABLE or self.list_widget.count() == 0:
            return
        viewport = self.list_widget.viewport().rect()
        for row in range(self.list_widget.count()):
            item = self.list_widget.item(row)
            if not item:
                continue
            entry = item.data(Qt.UserRole)
            if entry.type != "image":
                continue
            if entry.id in self._thumb_loaded or entry.id in self._thumb_loading:
                continue
            if not viewport.intersects(self.list_widget.visualItemRect(item)):
                continue
            self._thumb_loading.add(entry.id)
            self._thumb_pool.start(ThumbnailLoader(entry.id, entry, self._thumb_signals))

    def _do_refresh(self):
        kw = self._search_keyword
        if self._mode == "history":
            entries = self.history.search(kw) if kw else self.history.get_all()
        else:
            entries = self.permanent.search(kw) if kw else self.permanent.get_all()

        new_ids = [e.id for e in entries]

        if new_ids == self._current_ids:
            self._update_status(len(entries))
            return

        if not kw and self._try_incremental_sync(entries, new_ids):
            self._schedule_visible_thumbnails()
            return

        self._full_rebuild_list(entries, new_ids)

    def _on_thumbnail_ready(self, entry_id: str, pixmap: QPixmap):
        self._thumb_loading.discard(entry_id)
        self._thumb_loaded.add(entry_id)
        pair = self._item_map.get(entry_id)
        if pair:
            _, widget = pair
            widget.set_thumbnail(pixmap)

    def refresh(self):
        """外部调用刷新（有新数据时）"""
        self._current_ids = []   # 强制重建
        self._refresh_list()

    def refresh_if_dirty(self):
        """仅在数据有变化时才刷新（增量优先）"""
        if self.history.consume_dirty():
            self._do_refresh()

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
                    data = entry.get_content()
                    ba = BytesIO(data)
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
        self._current_ids = []
        self._refresh_list()

    def _remove_from_permanent(self, entry: ClipEntry):
        self.permanent.remove(entry.id)
        self._current_ids = []
        self._refresh_list()

    def _clear_history(self):
        if self._mode == "history":
            ret = QMessageBox.question(self, "确认", "清空所有普通历史记录？",
                                       QMessageBox.Yes | QMessageBox.No)
            if ret == QMessageBox.Yes:
                self.history.clear_all()
                self._full_rebuild_list([], [])

    def open_settings(self):
        dlg = SettingsDialog(self.config, self)
        if dlg.exec_() == QDialog.Accepted:
            new_cfg = dlg.get_config()
            self.config.update(new_cfg)
            self.history.max_count = new_cfg["max_count"]
            self.history.max_days = new_cfg["max_days"]
            self.history.force_cleanup()
            save_config(self.config)
            self._current_ids = []
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
            elif key == Qt.Key_G and event.modifiers() == Qt.ControlModifier:
                self.toggle_mode()
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

        self.monitor = ClipboardChecker(poll_ms=self.config.get("poll_ms", 800))
        self.monitor.new_entry.connect(self._on_new_clip)
        self.monitor.start()

        self.hotkey_mgr = GlobalHotkeyManager()
        self.hotkey_mgr.signal_alt_v.connect(self._toggle_window)
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
            win = self.window
            had_search = bool(win._search_keyword)
            win._position_near_cursor()
            win.search_box.blockSignals(True)
            win.search_box.clear()
            win.search_box.blockSignals(False)
            win._search_keyword = ""
            win.show()
            win.raise_()
            win.activateWindow()
            win.search_box.setFocus()

            def _deferred_refresh():
                if had_search:
                    win._do_refresh()
                else:
                    win.refresh_if_dirty()

            QTimer.singleShot(0, _deferred_refresh)

    def _on_new_clip(self, entry: ClipEntry):
        self.history.add(entry)
        # 窗口可见时才刷新，避免后台无谓重建
        if self.window.isVisible():
            self.window.refresh_if_dirty()

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
