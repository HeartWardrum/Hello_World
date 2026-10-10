"""
轻量级剪贴板管理工具 v3.2 - 热键修复与性能优化版
基于 v3 的增强：
  1. 全局热键 Alt+V 可配置（Alt+V / Ctrl+Shift+V / ... 任意组合）
  2. 窗口内快捷键 Ctrl+K（操作菜单）、Ctrl+G（切换模式）可配置
  3. 快捷键支持禁用（清空即禁用）
  4. 全局热键运行时重注册，注册失败托盘提示
  5. 修复 poll_ms 保存后不生效的问题
其余逻辑与 v3 保持一致。
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
from collections import OrderedDict

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QListWidget, QListWidgetItem, QLineEdit, QPushButton, QLabel,
    QSystemTrayIcon, QMenu, QAction,
    QMessageBox, QDialog, QCheckBox, QSpinBox, QFormLayout,
    QSplitter, QTextEdit, QFrame, QShortcut,
)
from PyQt5.QtCore import (
    Qt, QThread, pyqtSignal, QTimer, QSize, QPoint, QSettings,
    QRunnable, QThreadPool, pyqtSlot, QObject, QBuffer, QIODevice,
)
from PyQt5.QtGui import (
    QIcon, QPixmap, QImage, QColor, QPainter, QFont, QCursor,
    QKeySequence,
)

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

try:
    import pyautogui
    PYAUTOGUI_AVAILABLE = True
except ImportError:
    PYAUTOGUI_AVAILABLE = False

try:
    from pynput.keyboard import Key, Controller as PynputController
    PYNPUT_AVAILABLE = True
except ImportError:
    PYNPUT_AVAILABLE = False


APP_NAME = "ClipboardManager"
DATA_DIR = os.path.join(os.path.expanduser("~"), ".clipboard_manager")
HISTORY_FILE = os.path.join(DATA_DIR, "history.json")
DB_FILE = os.path.join(DATA_DIR, "permanent.db")
IMAGES_DIR = os.path.join(DATA_DIR, "images")
THUMBNAIL_SIZE = (120, 80)
MAX_TEXT_PREVIEW = 200
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")

# 剪贴板图片最大边长，超过则等比缩小后再 PNG 编码（毫秒级差异很大）
MAX_IMAGE_DIM = 3000

DEFAULT_CONFIG = {
    "max_count": 100,
    "max_days": 30,
    "focus_hide": True,
    "poll_ms": 800,
    "window_w": 900,
    "window_h": 680,
    # 快捷键：空字符串 = 禁用
    "hotkey_global": "alt+v",     # 全局：显示/隐藏
    "hotkey_actions": "ctrl+k",   # 面板：打开操作菜单
    "hotkey_mode": "ctrl+g",      # 面板：切换历史/收藏
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
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            return {**DEFAULT_CONFIG, **cfg}
        except Exception:
            pass
    return dict(DEFAULT_CONFIG)


def save_config(cfg: dict):
    """原子写入配置，避免异常退出造成配置文件损坏。"""
    try:
        tmp_path = CONFIG_FILE + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, CONFIG_FILE)
    except Exception as ex:
        print(f"保存配置失败: {ex}")


# ─────────────────────────── 快捷键工具 ───────────────────────────
def parse_qt_shortcut(s: str):
    """'ctrl+k' → (key, modifiers)。失败返回 (0, Qt.NoModifier)。"""
    if not s:
        return 0, Qt.NoModifier
    seq = QKeySequence(s)
    if seq.isEmpty():
        return 0, Qt.NoModifier
    combo = seq[0]
    key = combo & ~Qt.KeyboardModifierMask
    mods = combo & Qt.KeyboardModifierMask
    return int(key), mods


def normalize_shortcut_text(s: str) -> str:
    """统一成 'Ctrl+K' 展示形式。"""
    if not s:
        return ""
    return QKeySequence(s).toString(QKeySequence.NativeText)


def qt_key_to_vk(key: int):
    """Qt 主键 → Win32 虚拟键码。"""
    if Qt.Key_A <= key <= Qt.Key_Z:
        return key  # Qt 的 Key_A..Key_Z 恰好等于 ASCII 'A'..'Z'
    if Qt.Key_0 <= key <= Qt.Key_9:
        return key
    if Qt.Key_F1 <= key <= Qt.Key_F24:
        return 0x70 + (key - Qt.Key_F1)  # VK_F1 = 0x70
    mapping = {
        Qt.Key_Space: 0x20,
        Qt.Key_Tab: 0x09,
        Qt.Key_Return: 0x0D,
        Qt.Key_Enter: 0x0D,
        Qt.Key_Escape: 0x1B,
        Qt.Key_Backspace: 0x08,
        Qt.Key_Delete: 0x2E,
        Qt.Key_Insert: 0x2D,
        Qt.Key_Home: 0x24,
        Qt.Key_End: 0x23,
        Qt.Key_PageUp: 0x21,
        Qt.Key_PageDown: 0x22,
        Qt.Key_Left: 0x25,
        Qt.Key_Up: 0x26,
        Qt.Key_Right: 0x27,
        Qt.Key_Down: 0x28,
        Qt.Key_Pause: 0x13,
        Qt.Key_Print: 0x2C,
        Qt.Key_CapsLock: 0x14,
        Qt.Key_NumLock: 0x90,
        Qt.Key_ScrollLock: 0x91,
        Qt.Key_Menu: 0x5D,
        Qt.Key_Minus: 0xBD,
        Qt.Key_Equal: 0xBB,
        Qt.Key_BracketLeft: 0xDB,
        Qt.Key_BracketRight: 0xDD,
        Qt.Key_Backslash: 0xDC,
        Qt.Key_Semicolon: 0xBA,
        Qt.Key_Apostrophe: 0xDE,
        Qt.Key_Comma: 0xBC,
        Qt.Key_Period: 0xBE,
        Qt.Key_Slash: 0xBF,
        Qt.Key_QuoteLeft: 0xC0,
    }
    # Shift+数字/标点在 Qt 中可能以符号键值表示，映射回对应的物理主键。
    shifted_ascii = {
        Qt.Key_Exclam: ord("1"), Qt.Key_At: ord("2"), Qt.Key_NumberSign: ord("3"),
        Qt.Key_Dollar: ord("4"), Qt.Key_Percent: ord("5"), Qt.Key_AsciiCircum: ord("6"),
        Qt.Key_Ampersand: ord("7"), Qt.Key_Asterisk: ord("8"),
        Qt.Key_ParenLeft: ord("9"), Qt.Key_ParenRight: ord("0"),
        Qt.Key_Underscore: 0xBD, Qt.Key_Plus: 0xBB,
        Qt.Key_BraceLeft: 0xDB, Qt.Key_BraceRight: 0xDD, Qt.Key_Bar: 0xDC,
        Qt.Key_Colon: 0xBA, Qt.Key_QuoteDbl: 0xDE, Qt.Key_Less: 0xBC,
        Qt.Key_Greater: 0xBE, Qt.Key_Question: 0xBF, Qt.Key_AsciiTilde: 0xC0,
    }
    return mapping.get(key, shifted_ascii.get(key))


def parse_win_hotkey(s: str):
    """'alt+v' → (modifiers, vk)。失败返回 (None, None)。"""
    if not s:
        return None, None
    seq = QKeySequence(s)
    if seq.isEmpty():
        return None, None
    combo = seq[0]
    mods = 0
    if combo & Qt.ControlModifier:
        mods |= 0x0002  # MOD_CONTROL
    if combo & Qt.AltModifier:
        mods |= 0x0001  # MOD_ALT
    if combo & Qt.ShiftModifier:
        mods |= 0x0004  # MOD_SHIFT
    if combo & Qt.MetaModifier:
        mods |= 0x0008  # MOD_WIN

    key = combo & ~Qt.KeyboardModifierMask
    vk = qt_key_to_vk(int(key))
    if vk is None or mods == 0:
        return None, None
    return mods, vk


# ─────────────────────────── 数据模型 ───────────────────────────
class ClipEntry:
    def __init__(self, entry_type: str, content, timestamp: float = None,
                 entry_id: str = None, note: str = "", image_path: str = ""):
        self.type = entry_type
        self.note = note
        self.timestamp = timestamp or now_ts()
        self._image_path = image_path
        self._hash_cache = None

        if entry_type == "image" and image_path:
            self.content = None
            self._lazy = True
        else:
            self.content = content
            self._lazy = False

        self.id = entry_id or compute_md5(
            (str(self.timestamp) + (image_path or (content[:50] if isinstance(content, str) else ""))).encode()
        )

    def _ensure_loaded(self):
        if self._lazy and self.content is None:
            if os.path.exists(self._image_path):
                try:
                    with open(self._image_path, "rb") as f:
                        self.content = f.read()
                    self._hash_cache = compute_md5(self.content)
                    self._lazy = False
                except Exception:
                    self.content = b""
                    self._lazy = False
            else:
                self.content = b""
                self._lazy = False

    def get_content(self):
        if self.type == "image":
            self._ensure_loaded()
        return self.content

    def get_hash(self) -> str:
        if self._hash_cache:
            return self._hash_cache
        if self.type == "text":
            self._hash_cache = compute_md5(self.content.encode("utf-8"))
        elif self._lazy and self._image_path and os.path.isfile(self._image_path):
            # 启动加载历史时只流式计算哈希，不把全部图片内容常驻内存。
            digest = hashlib.md5()
            try:
                with open(self._image_path, "rb") as f:
                    for chunk in iter(lambda: f.read(1024 * 1024), b""):
                        digest.update(chunk)
                self._hash_cache = digest.hexdigest()
            except OSError:
                self._ensure_loaded()
                self._hash_cache = compute_md5(self.content or b"")
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
    SAVE_DEBOUNCE_SEC = 1.0

    def __init__(self, max_count=100, max_days=30):
        self.max_count = max_count
        self.max_days = max_days
        self._entries: list = []
        self._hash_map: dict = {}
        self._dirty = False
        self._save_timer: threading.Timer = None
        self._save_lock = threading.Lock()
        self.load()

    def get_all(self) -> list:
        return list(self._entries)

    def search(self, keyword: str) -> list:
        kw = keyword.lower()
        return [e for e in self._entries
                if (e.type == "text" and kw in e.content.lower()) or
                   (e.type == "image" and kw in (e.note or "").lower())]

    def add(self, entry: ClipEntry) -> bool:
        h = entry.get_hash()
        existing = self._hash_map.get(h)
        if existing is not None:
            try:
                self._entries.remove(existing)
            except ValueError:
                pass
            existing.timestamp = entry.timestamp
            self._entries.insert(0, existing)
            self._mark_dirty()
            return False

        self._entries.insert(0, entry)
        self._hash_map[h] = entry
        self._cleanup()
        self._mark_dirty()
        return True

    def remove(self, entry_id: str):
        for i, e in enumerate(self._entries):
            if e.id == entry_id:
                self._entries.pop(i)
                self._hash_map.pop(e.get_hash(), None)
                break
        self._mark_dirty()

    def clear_all(self):
        self._entries.clear()
        self._hash_map.clear()
        self._mark_dirty()

    def force_cleanup(self):
        self._cleanup()
        self._mark_dirty()
        self._flush_save()

    def consume_dirty(self) -> bool:
        d = self._dirty
        self._dirty = False
        return d

    def _mark_dirty(self):
        self._dirty = True
        self._schedule_save()

    def _cleanup(self):
        removed_any = False
        if self.max_count > 0 and len(self._entries) > self.max_count:
            removed = self._entries[self.max_count:]
            self._entries = self._entries[:self.max_count]
            for e in removed:
                self._hash_map.pop(e.get_hash(), None)
                if e.type == "image":
                    self._delete_image_file(e)
            removed_any = True

        if self.max_days > 0:
            cutoff = now_ts() - self.max_days * 86400
            kept, removed = [], []
            for e in self._entries:
                (kept if e.timestamp >= cutoff else removed).append(e)
            for e in removed:
                self._hash_map.pop(e.get_hash(), None)
                if e.type == "image":
                    self._delete_image_file(e)
            self._entries = kept
            removed_any = removed_any or bool(removed)

        return removed_any

    def _delete_image_file(self, entry: ClipEntry):
        path = entry._image_path or os.path.join(IMAGES_DIR, f"hist_{entry.id}.png")
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass

    def _schedule_save(self):
        with self._save_lock:
            if self._save_timer is not None:
                self._save_timer.cancel()
            self._save_timer = threading.Timer(self.SAVE_DEBOUNCE_SEC, self._flush_save)
            self._save_timer.daemon = True
            self._save_timer.start()

    def _flush_save(self):
        with self._save_lock:
            self._save_timer = None
        self.save()

    def save(self):
        data = []
        for e in self._entries:
            item = {"id": e.id, "type": e.type, "timestamp": e.timestamp, "note": e.note}
            if e.type == "text":
                item["content"] = e.content
            else:
                path = e._image_path or os.path.join(IMAGES_DIR, f"hist_{e.id}.png")
                if not os.path.exists(path):
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
            tmp = HISTORY_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, HISTORY_FILE)
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
                    if not path:
                        continue
                    e = ClipEntry("image", None, item["timestamp"],
                                  item["id"], item.get("note", ""),
                                  image_path=path)
                self._entries.append(e)
                self._hash_map[e.get_hash()] = e
            self._cleanup()
        except Exception as ex:
            print(f"加载历史失败: {ex}")


# ─────────────────────────── 永久存储 ───────────────────────────
class PermanentStore:
    def __init__(self):
        self._conn = sqlite3.connect(DB_FILE, check_same_thread=False)
        self._lock = threading.Lock()
        self._create_table()
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
                e = ClipEntry(etype, bytes(content) if content else b"", ts, eid, note or "")
            result.append(e)
        return result

    def search(self, keyword: str) -> list:
        kw = f"%{keyword.lower()}%"
        with self._lock:
            cur = self._conn.execute(
                "SELECT id,type,content,note,timestamp FROM permanent "
                "WHERE LOWER(IFNULL(note,'')) LIKE ? "
                "   OR (type='text' AND LOWER(CAST(content AS TEXT)) LIKE ?) "
                "ORDER BY timestamp DESC",
                (kw, kw)
            )
            rows = cur.fetchall()
        result = []
        for row in rows:
            eid, etype, content, note, ts = row
            if etype == "text":
                content_decoded = content.decode("utf-8") if isinstance(content, bytes) else content
                e = ClipEntry(etype, content_decoded, ts, eid, note or "")
            else:
                e = ClipEntry(etype, bytes(content) if content else b"", ts, eid, note or "")
            result.append(e)
        return result

    def close(self):
        self._conn.close()


# ─────────────────────────── 剪贴板监控 ───────────────────────────
class ImageEncodeSignals(QObject):
    done = pyqtSignal(object)


class ImageEncodeTask(QRunnable):
    def __init__(self, qimage_copy: QImage, signals: ImageEncodeSignals):
        super().__init__()
        self.qimage = qimage_copy
        self.signals = signals
        self.setAutoDelete(True)

    @pyqtSlot()
    def run(self):
        try:
            img = self.qimage
            if img.width() > MAX_IMAGE_DIM or img.height() > MAX_IMAGE_DIM:
                img = img.scaled(MAX_IMAGE_DIM, MAX_IMAGE_DIM,
                                 Qt.KeepAspectRatio, Qt.SmoothTransformation)
            # QImage 原生编码，避免将整张图复制到 PIL 再编码，且不再依赖 Pillow 才能保存图片。
            buffer = QBuffer()
            if not buffer.open(QIODevice.WriteOnly):
                raise RuntimeError("无法创建图片编码缓冲区")
            if not img.save(buffer, "PNG", 3):
                buffer.close()
                raise RuntimeError("Qt PNG 编码失败")
            data = bytes(buffer.data())
            buffer.close()
            note = f"图片_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            entry = ClipEntry("image", data, note=note)
            self.signals.done.emit(entry)
        except Exception as ex:
            print(f"图片编码失败: {ex}")


class ClipboardChecker(QObject):
    new_entry = pyqtSignal(object)

    def __init__(self, poll_ms=800, parent=None):
        super().__init__(parent)
        self._last_hash = ""
        self._poll_ms = poll_ms
        self._timer = QTimer(self)
        self._timer.setInterval(poll_ms)
        self._timer.timeout.connect(self._check)
        self._cb = None
        self._last_clipboard_seq = None
        self._get_clipboard_sequence = None
        if sys.platform == "win32":
            try:
                get_seq = ctypes.windll.user32.GetClipboardSequenceNumber
                get_seq.argtypes = []
                get_seq.restype = wintypes.DWORD
                self._get_clipboard_sequence = get_seq
            except Exception:
                self._get_clipboard_sequence = None
        self._img_signals = ImageEncodeSignals()
        self._img_signals.done.connect(self.new_entry)
        self._img_pool = QThreadPool()
        self._img_pool.setMaxThreadCount(1)

    def set_poll_ms(self, ms: int):
        self._poll_ms = ms
        self._timer.setInterval(ms)

    def start(self):
        self._cb = QApplication.clipboard()
        self._timer.start()

    def stop(self):
        self._timer.stop()

    def _check(self):
        try:
            # 大图片的 image()/scale/hash 很耗时。Windows 剪贴板序号未变化时直接返回。
            if self._get_clipboard_sequence is not None:
                seq = int(self._get_clipboard_sequence())
                if self._last_clipboard_seq is not None and seq == self._last_clipboard_seq:
                    return
                self._last_clipboard_seq = seq
            if self._cb is None:
                self._cb = QApplication.clipboard()
            mime = self._cb.mimeData()

            if mime.hasImage():
                qimg = self._cb.image()
                if qimg.isNull():
                    return
                small = qimg.scaled(64, 64, Qt.KeepAspectRatio, Qt.FastTransformation)
                small = small.convertToFormat(QImage.Format_RGBA8888)
                ptr = small.bits()
                ptr.setsize(small.byteCount())
                quick_hash = compute_md5(bytes(ptr))
                if quick_hash == self._last_hash:
                    return
                self._last_hash = quick_hash
                qimg_copy = qimg.copy()
                self._img_pool.start(ImageEncodeTask(qimg_copy, self._img_signals))
            elif mime.hasText():
                text = mime.text().strip()
                if not text:
                    return
                h = compute_md5(text.encode("utf-8"))
                if h == self._last_hash:
                    return
                self._last_hash = h
                self.new_entry.emit(ClipEntry("text", text))
        except Exception as ex:
            print(f"剪贴板检测异常: {ex}")


# ─────────────────────────── 异步缩略图加载 ───────────────────────────
class ThumbnailSignals(QObject):
    done = pyqtSignal(str, QImage)


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
            data = self.entry.get_content()
            if not data:
                return
            ba = BytesIO(data)
            with Image.open(ba) as pil:
                thumb = make_thumbnail(pil)
                rgba = thumb.convert("RGBA")
                raw = rgba.tobytes("raw", "RGBA")
                image = QImage(raw, rgba.width, rgba.height, rgba.width * 4,
                               QImage.Format_RGBA8888).copy()
            self.signals.done.emit(self.entry_id, image)
        except Exception:
            self.signals.done.emit(self.entry_id, QImage())


# ─────────────────────────── 条目Widget ───────────────────────────
class EntryItemWidget(QWidget):
    def __init__(self, entry: ClipEntry, parent=None):
        super().__init__(parent)
        self.entry = entry
        self._thumb_lbl: QLabel = None
        self._build_ui()

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(10)

        icon_lbl = QLabel()
        icon_lbl.setFixedSize(20, 20)
        icon_lbl.setAlignment(Qt.AlignCenter)
        if self.entry.type == "image":
            icon_lbl.setText("🖼")
            icon_lbl.setStyleSheet("font-size: 14px;")
        else:
            icon_lbl.setText("📄")
            icon_lbl.setStyleSheet("color: #a0a0a0; font-size: 14px;")
        layout.addWidget(icon_lbl)

        if self.entry.type == "image":
            self._thumb_lbl = QLabel()
            self._thumb_lbl.setFixedSize(THUMBNAIL_SIZE[0] // 2, THUMBNAIL_SIZE[1] // 2)
            self._thumb_lbl.setStyleSheet("background:#2c2c2e; border-radius:4px;")
            layout.addWidget(self._thumb_lbl)

        preview_text = self.entry.get_preview().replace('\n', ' ')
        preview_lbl = QLabel()
        preview_lbl.setStyleSheet("color: #d0d0d0; font-size: 15px; font-family: 'Segoe UI', sans-serif;")
        preview_lbl.setWordWrap(False)
        metrics = preview_lbl.fontMetrics()
        elided_text = metrics.elidedText(preview_text, Qt.ElideRight, 250)
        preview_lbl.setText(elided_text)
        layout.addWidget(preview_lbl, 1)

    def set_thumbnail(self, pixmap: QPixmap):
        if self._thumb_lbl is not None and not pixmap.isNull():
            scaled = pixmap.scaled(
                self._thumb_lbl.width(), self._thumb_lbl.height(),
                Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            self._thumb_lbl.setPixmap(scaled)


# ─────────────────────────── 全局快捷键（可重注册）───────────────────────────
class GlobalHotkeyManager(QThread):
    signal_triggered = pyqtSignal()
    signal_register_failed = pyqtSignal(str)

    WM_HOTKEY = 0x0312
    WM_QUIT = 0x0012
    WM_APP_RELOAD_HOTKEY = 0x8000 + 1
    HOTKEY_ID = 1001
    MOD_NOREPEAT = 0x4000
    PM_NOREMOVE = 0x0000

    def __init__(self, hotkey_str: str = "alt+v"):
        super().__init__()
        self._running = True
        self.user32 = ctypes.windll.user32
        self.kernel32 = ctypes.windll.kernel32
        self._thread_id = None
        self._hotkey_str = hotkey_str or ""
        self._mods = None
        self._vk = None
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._configure_winapi()

    def _configure_winapi(self):
        """为 Win32 API 声明正确的参数/返回类型，避免 64 位环境的类型截断。"""
        try:
            self.user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int,
                                                   wintypes.UINT, wintypes.UINT]
            self.user32.RegisterHotKey.restype = wintypes.BOOL
            self.user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
            self.user32.UnregisterHotKey.restype = wintypes.BOOL
            self.user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT,
                                                       wintypes.WPARAM, wintypes.LPARAM]
            self.user32.PostThreadMessageW.restype = wintypes.BOOL
            self.user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                                                wintypes.UINT, wintypes.UINT]
            self.user32.GetMessageW.restype = ctypes.c_int
            self.user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                                                 wintypes.UINT, wintypes.UINT, wintypes.UINT]
            self.user32.PeekMessageW.restype = wintypes.BOOL
            self.user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
            self.user32.TranslateMessage.restype = wintypes.BOOL
            self.user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
            self.user32.DispatchMessageW.restype = ctypes.c_ssize_t
            self.kernel32.GetCurrentThreadId.argtypes = []
            self.kernel32.GetCurrentThreadId.restype = wintypes.DWORD
        except Exception:
            # 允许在部分 Wine/兼容环境中继续尝试使用 API。
            pass

    def start_listening(self):
        self.start()

    def update_hotkey(self, hotkey_str: str):
        """线程安全更新配置；消息队列就绪后再投递重注册消息。"""
        with self._lock:
            self._hotkey_str = hotkey_str or ""
        if not self._ready.is_set():
            # 启动阶段的更新会由 run() 读取最新配置，不丢失修改。
            return
        thread_id = self._thread_id
        if thread_id:
            ok = self.user32.PostThreadMessageW(
                thread_id, self.WM_APP_RELOAD_HOTKEY, 0, 0
            )
            if not ok:
                # 通常意味着线程正在退出；不在 UI 线程直接调用 RegisterHotKey。
                self.signal_register_failed.emit(hotkey_str or "")

    def _register(self):
        self.user32.UnregisterHotKey(None, self.HOTKEY_ID)
        with self._lock:
            s = self._hotkey_str
        mods, vk = parse_win_hotkey(s)
        if mods is None:
            self._mods = self._vk = None  # 空字符串或不支持的键组合：禁用全局热键
            return
        ok = self.user32.RegisterHotKey(
            None, self.HOTKEY_ID, mods | self.MOD_NOREPEAT, vk
        )
        if ok:
            self._mods, self._vk = mods, vk
        else:
            self._mods = self._vk = None
            self.signal_register_failed.emit(s)

    def run(self):
        msg = wintypes.MSG()
        # 关键修复：先创建线程消息队列，再公开 thread_id。
        # 否则启动瞬间 PostThreadMessage 可能因队列不存在而失败。
        self.user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, self.PM_NOREMOVE)
        self._thread_id = int(self.kernel32.GetCurrentThreadId())
        self._ready.set()
        self._register()
        try:
            while self._running:
                ret = self.user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if ret <= 0:
                    break
                if msg.message == self.WM_HOTKEY and msg.wParam == self.HOTKEY_ID:
                    self.signal_triggered.emit()
                elif msg.message == self.WM_APP_RELOAD_HOTKEY:
                    self._register()
                self.user32.TranslateMessage(ctypes.byref(msg))
                self.user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            self.user32.UnregisterHotKey(None, self.HOTKEY_ID)
            self._ready.clear()
            self._thread_id = None

    def stop(self):
        self._running = False
        if self._ready.is_set() and self._thread_id:
            self.user32.PostThreadMessageW(self._thread_id, self.WM_QUIT, 0, 0)
        if self.isRunning():
            self.wait(2000)


# ─────────────────────────── 快捷键录制控件 ───────────────────────────
class ShortcutEdit(QLineEdit):
    """点击后按下组合键即录制。按 Esc 清空（禁用）。"""

    def __init__(self, value: str = "", parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setPlaceholderText("点击后按组合键… (Esc 清空)")
        self._value = value or ""
        self.setText(normalize_shortcut_text(self._value))

    def value(self) -> str:
        return self._value

    def setValue(self, s: str):
        self._value = s or ""
        self.setText(normalize_shortcut_text(self._value))

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key_Escape:
            self.setValue("")
            return
        # 只按修饰键不算
        if key in (Qt.Key_Control, Qt.Key_Alt, Qt.Key_Shift, Qt.Key_Meta,
                   Qt.Key_AltGr, Qt.Key_unknown):
            return
        mods = event.modifiers()
        # 至少要有 Ctrl/Alt/Shift/Win 之一，避免单键误触
        if not (mods & (Qt.ControlModifier | Qt.AltModifier |
                        Qt.ShiftModifier | Qt.MetaModifier)):
            return
        seq = QKeySequence(mods | key)
        portable = seq.toString(QKeySequence.PortableText).lower()
        self.setValue(portable)


# ─────────────────────────── 设置对话框 ───────────────────────────
class SettingsDialog(QDialog):
    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.config = dict(config)
        self.setWindowTitle("设置")
        self.setMinimumWidth(420)
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

        # ── 快捷键 ──
        self.hotkey_global_edit = ShortcutEdit(self.config.get("hotkey_global", "alt+v"))
        form.addRow("全局：显示/隐藏:", self.hotkey_global_edit)

        self.hotkey_actions_edit = ShortcutEdit(self.config.get("hotkey_actions", "ctrl+k"))
        form.addRow("面板：操作菜单:", self.hotkey_actions_edit)

        self.hotkey_mode_edit = ShortcutEdit(self.config.get("hotkey_mode", "ctrl+g"))
        form.addRow("面板：切换模式:", self.hotkey_mode_edit)

        hint = QLabel("提示：快捷键需至少含一个修饰键；清空即禁用。修改全局热键后立即生效。")
        hint.setStyleSheet("color: #888888; font-size: 11px;")
        hint.setWordWrap(True)
        layout.addLayout(form)
        layout.addWidget(hint)

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
        self.config["hotkey_global"] = self.hotkey_global_edit.value()
        self.config["hotkey_actions"] = self.hotkey_actions_edit.value()
        self.config["hotkey_mode"] = self.hotkey_mode_edit.value()
        self.accept()

    def get_config(self) -> dict:
        return self.config


class ImagePreviewSignals(QObject):
    done = pyqtSignal(str, QImage)


class ImagePreviewLoader(QRunnable):
    """后台读取/缩放预览图，只把 QImage 交回主线程。"""
    def __init__(self, entry: ClipEntry, max_size, signals: ImagePreviewSignals):
        super().__init__()
        self.entry = entry
        self.entry_id = entry.id
        self.max_size = (max(1, int(max_size[0])), max(1, int(max_size[1])))
        self.signals = signals
        self.setAutoDelete(True)

    @pyqtSlot()
    def run(self):
        try:
            raw = self.entry.get_content()
            if not raw:
                return
            if PIL_AVAILABLE:
                with Image.open(BytesIO(raw)) as pil:
                    pil.thumbnail(self.max_size, Image.LANCZOS)
                    rgba = pil.convert("RGBA")
                    buf = rgba.tobytes("raw", "RGBA")
                    image = QImage(buf, rgba.width, rgba.height, rgba.width * 4,
                                   QImage.Format_RGBA8888).copy()
            else:
                image = QImage.fromData(raw)
                if not image.isNull():
                    image = image.scaled(self.max_size[0], self.max_size[1],
                                         Qt.KeepAspectRatio, Qt.SmoothTransformation)
            if not image.isNull():
                self.signals.done.emit(self.entry_id, image)
        except Exception as ex:
            print(f"图片预览加载失败: {ex}")


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
        self._preview_signals = ImagePreviewSignals()
        self._preview_signals.done.connect(self._on_preview_image_ready)
        self._thumb_pool = QThreadPool.globalInstance()
        self._thumb_pool.setMaxThreadCount(max(2, min(4, self._thumb_pool.maxThreadCount())))
        self._item_map: dict = {}
        self._current_preview_id = None
        self._actions_shortcut = QShortcut(QKeySequence(), self)
        self._actions_shortcut.setContext(Qt.WindowShortcut)
        self._actions_shortcut.activated.connect(self._trigger_actions_shortcut)
        self._mode_shortcut = QShortcut(QKeySequence(), self)
        self._mode_shortcut.setContext(Qt.WindowShortcut)
        self._mode_shortcut.activated.connect(self.toggle_mode)
        self._current_ids: list = []
        self._thumb_loaded: set = set()
        self._thumb_loading: set = set()

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(200)
        self._search_timer.timeout.connect(self._do_refresh)

        w = config.get("window_w", 900)
        h = config.get("window_h", 680)
        self.setWindowTitle("ClipboardManager")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(w, h)
        self._build_ui()
        self._apply_style()
        self._apply_window_shortcuts()

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

    def _position_near_cursor(self):
        cursor_pos = QCursor.pos()
        screen = QApplication.screenAt(cursor_pos)
        if screen is None:
            screen = QApplication.primaryScreen()
        avail = screen.availableGeometry()
        w, h = self.width(), self.height()
        x = avail.x() + (avail.width() - w) // 2
        y = avail.y() + (avail.height() - h) // 3
        self.move(x, y)

    def _build_ui(self):
        central = QWidget()
        central.setObjectName("centralWidget")
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        top_bar = QWidget()
        top_bar.setObjectName("topBar")
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(20, 15, 20, 15)

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Type to filter entries...")
        self.search_box.setObjectName("searchBox")
        self.search_box.textChanged.connect(self._on_search)
        self.search_box.installEventFilter(self)
        top_layout.addWidget(self.search_box)

        self.toggle_btn = QPushButton("All Types ▾")
        self.toggle_btn.setObjectName("toggleBtn")
        self.toggle_btn.setCursor(Qt.PointingHandCursor)
        self.toggle_btn.clicked.connect(self.toggle_mode)
        top_layout.addWidget(self.toggle_btn)

        main_layout.addWidget(top_bar)

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setObjectName("mainSplitter")
        self.splitter.setHandleWidth(1)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(10, 5, 10, 5)
        left_layout.setSpacing(5)

        self.list_title = QLabel("Today")
        self.list_title.setObjectName("listTitle")
        left_layout.addWidget(self.list_title)

        self.list_widget = QListWidget()
        self.list_widget.setObjectName("listWidget")
        self.list_widget.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list_widget.setSpacing(2)
        self.list_widget.setUniformItemSizes(True)
        self.list_widget.itemClicked.connect(self._on_item_clicked)
        self.list_widget.currentItemChanged.connect(self._on_item_selection_changed)
        self.list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._on_context_menu)
        self.list_widget.installEventFilter(self)
        self.list_widget.verticalScrollBar().valueChanged.connect(
            lambda _: self._schedule_visible_thumbnails()
        )
        left_layout.addWidget(self.list_widget)
        self.splitter.addWidget(left_panel)

        self.right_panel = QWidget()
        self.right_panel.setObjectName("rightPanel")
        right_layout = QVBoxLayout(self.right_panel)
        right_layout.setContentsMargins(20, 20, 20, 20)
        right_layout.setSpacing(15)

        self.preview_text = QTextEdit()
        self.preview_text.setObjectName("previewText")
        self.preview_text.setReadOnly(True)
        self.preview_text.setLineWrapMode(QTextEdit.WidgetWidth)
        right_layout.addWidget(self.preview_text, 1)

        self.preview_image = QLabel()
        self.preview_image.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.preview_image.hide()
        right_layout.addWidget(self.preview_image, 1)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        line.setStyleSheet("background-color: #333333;")
        right_layout.addWidget(line)

        info_title = QLabel("Information")
        info_title.setObjectName("infoTitle")
        right_layout.addWidget(info_title)

        info_grid = QFormLayout()
        info_grid.setContentsMargins(0, 0, 0, 0)
        info_grid.setVerticalSpacing(10)

        self.info_type = QLabel("-")
        self.info_type.setObjectName("infoValue")
        self.info_chars = QLabel("-")
        self.info_chars.setObjectName("infoValue")

        info_grid.addRow(self._create_info_label("Type"), self.info_type)
        info_grid.addRow(self._create_info_label("Characters"), self.info_chars)
        right_layout.addLayout(info_grid)

        self.splitter.addWidget(self.right_panel)
        self.splitter.setSizes([400, 600])
        main_layout.addWidget(self.splitter, 1)

        bottom_bar = QWidget()
        bottom_bar.setObjectName("bottomBar")
        bottom_layout = QHBoxLayout(bottom_bar)
        bottom_layout.setContentsMargins(15, 8, 15, 8)

        app_icon = QLabel("📋 Clipboard History")
        app_icon.setStyleSheet("color: #888888; font-size: 12px; font-weight: bold;")
        bottom_layout.addWidget(app_icon)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #777; font-size: 11px;")
        bottom_layout.addWidget(self.status_label)
        bottom_layout.addStretch()

        self.shortcut_lbl = QLabel()
        self.shortcut_lbl.setStyleSheet("color: #999999; font-size: 12px;")
        bottom_layout.addWidget(self.shortcut_lbl)
        self._update_shortcut_hint()

        main_layout.addWidget(bottom_bar)

        self._refresh_list()
        self._setup_focus_watcher()

    def _update_shortcut_hint(self):
        """底部提示随配置更新。"""
        paste = "⏎"
        actions = normalize_shortcut_text(self.config.get("hotkey_actions", "")) or "—"
        mode = normalize_shortcut_text(self.config.get("hotkey_mode", "")) or "—"
        self.shortcut_lbl.setText(
            f"<b>Paste</b> {paste}  |  <b>Actions</b> {actions}  |  <b>Mode</b> {mode}"
        )

    def _create_info_label(self, text):
        lbl = QLabel(text)
        lbl.setStyleSheet("color: #777777; font-size: 12px;")
        return lbl

    def _apply_style(self):
        self.setStyleSheet("""
            QMainWindow { background: transparent; }
            #centralWidget {
                background-color: #1c1c1e;
                border-radius: 12px;
                border: 1px solid #3a3a3c;
            }
            #topBar { border-bottom: 1px solid #2c2c2e; }
            #searchBox {
                background: transparent; color: #ffffff; border: none;
                font-size: 22px; font-family: 'Segoe UI', sans-serif;
            }
            #toggleBtn {
                background: transparent; color: #a0a0a0; border: 1px solid #3a3a3c;
                border-radius: 6px; padding: 4px 10px; font-size: 13px;
            }
            #toggleBtn:hover { background: #2c2c2e; color: #ffffff; }
            #mainSplitter::handle { background-color: #2c2c2e; }
            #listTitle { color: #888888; font-size: 12px; padding-left: 4px; padding-bottom: 4px; }
            #listWidget { background: transparent; border: none; outline: none; }
            #listWidget::item { border-radius: 6px; margin-bottom: 2px; }
            #listWidget::item:selected { background-color: #2c2c2e; }
            #listWidget::item:hover:!selected { background-color: #242426; }
            QScrollBar:vertical { background: transparent; width: 8px; }
            QScrollBar::handle:vertical { background: #4a4a4c; border-radius: 4px; min-height: 20px; }
            QScrollBar::handle:vertical:hover { background: #5a5a5c; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
            #rightPanel { background: transparent; }
            #previewText {
                background: transparent; border: none; color: #e0e0e0;
                font-size: 14px; font-family: 'Consolas', 'Courier New', monospace;
            }
            #infoTitle { color: #888888; font-size: 13px; font-weight: bold; margin-bottom: 5px; }
            #infoValue { color: #d0d0d0; font-size: 12px; }
            #bottomBar {
                background-color: #1e1e20; border-top: 1px solid #2c2c2e;
                border-bottom-left-radius: 12px; border-bottom-right-radius: 12px;
            }
        """)

    def _on_item_selection_changed(self, current, previous):
        if not current:
            self._current_preview_id = None
            self.preview_text.clear()
            self.preview_text.show()
            self.preview_image.hide()
            self.info_type.setText("-")
            self.info_chars.setText("-")
            return

        entry = current.data(Qt.UserRole)
        if entry.type == "text":
            self._current_preview_id = None
            self.preview_image.hide()
            self.preview_text.show()
            self.preview_text.setText(entry.content)
            self.info_type.setText("Text")
            self.info_chars.setText(f"{len(entry.content)}")
        elif entry.type == "image":
            self.preview_text.hide()
            self.preview_image.show()
            self.preview_image.clear()
            self._current_preview_id = entry.id
            self.info_type.setText("Image")
            self.info_chars.setText("N/A")
            max_w = max(1, self.right_panel.width() - 40)
            max_h = max(1, self.preview_image.height() or self.right_panel.height() - 180)
            self._thumb_pool.start(ImagePreviewLoader(
                entry, (max_w, max_h), self._preview_signals
            ))

    def toggle_mode(self):
        if self._mode == "history":
            self._mode = "permanent"
            self.toggle_btn.setText("Permanent ▾")
            self.list_title.setText("Starred")
        else:
            self._mode = "history"
            self.toggle_btn.setText("All Types ▾")
            self.list_title.setText("Today")
        self._current_ids = []
        self._refresh_list()

    def _refresh_list(self):
        self._do_refresh()

    def _on_search(self, text: str):
        self._search_keyword = text.strip()
        self._search_timer.start()

    def _entry_row_height(self, entry: ClipEntry) -> int:
        return 40

    def _update_status(self, count: int):
        self.status_label.setText(f"({count})")

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
        if (new_ids and new_ids[0] not in old_ids and new_ids[1:] == old_ids[:len(new_ids) - 1]):
            self._prepend_entry(entries[0])
            self._current_ids = new_ids
            self._update_status(len(entries))
            return True
        if (new_ids and new_ids[0] in old_ids and new_ids[1:] == [i for i in old_ids if i != new_ids[0]]):
            self._move_entry_to_top(new_ids[0], entries[0])
            self._current_ids = new_ids
            self._update_status(len(entries))
            return True
        if len(new_ids) < len(old_ids) and new_ids == old_ids[:len(new_ids)]:
            while len(self._current_ids) > len(new_ids):
                self._remove_entry_by_id(self._current_ids[-1])
            self._current_ids = new_ids
            self._update_status(len(entries))
            return True
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
        top_left = viewport.topLeft()
        bottom_right = viewport.bottomRight()

        first_idx = self.list_widget.indexAt(top_left)
        first_row = first_idx.row() if first_idx.isValid() else 0
        last_idx = self.list_widget.indexAt(bottom_right)
        last_row = last_idx.row() if last_idx.isValid() else self.list_widget.count() - 1

        for row in range(max(0, first_row), min(last_row + 1, self.list_widget.count())):
            item = self.list_widget.item(row)
            if not item:
                continue
            entry = item.data(Qt.UserRole)
            if entry.type != "image":
                continue
            if entry.id in self._thumb_loaded or entry.id in self._thumb_loading:
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

    def _on_thumbnail_ready(self, entry_id: str, image: QImage):
        self._thumb_loading.discard(entry_id)
        if image.isNull():
            return
        self._thumb_loaded.add(entry_id)
        pair = self._item_map.get(entry_id)
        if pair:
            _, widget = pair
            if isinstance(widget, EntryItemWidget):
                widget.set_thumbnail(QPixmap.fromImage(image))

    def _on_preview_image_ready(self, entry_id: str, image: QImage):
        # 用户快速切换条目时，丢弃过期任务的结果。
        if entry_id != self._current_preview_id or image.isNull():
            return
        self.preview_image.setPixmap(QPixmap.fromImage(image))

    def refresh(self):
        self._current_ids = []
        self._refresh_list()

    def refresh_if_dirty(self):
        if self.history.consume_dirty():
            self._do_refresh()

    def _on_item_clicked(self, item: QListWidgetItem):
        entry = item.data(Qt.UserRole)
        self._paste_entry(entry)

    def _paste_entry(self, entry: ClipEntry, as_plain_text=False):
        if hasattr(QApplication.instance(), "is_pasting"):
            QApplication.instance().is_pasting = True

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
                    pass

        self.hide()
        QTimer.singleShot(150, self._simulate_paste)

    def _simulate_paste(self):
        if PYAUTOGUI_AVAILABLE:
            try:
                pyautogui.hotkey("ctrl", "v")
            except Exception:
                pass
        elif PYNPUT_AVAILABLE:
            try:
                kc = PynputController()
                with kc.pressed(Key.ctrl):
                    kc.press("v")
                    kc.release("v")
            except Exception:
                pass

        if hasattr(QApplication.instance(), "is_pasting"):
            QTimer.singleShot(300, lambda: setattr(QApplication.instance(), "is_pasting", False))

    def _on_context_menu(self, pos: QPoint):
        item = self.list_widget.itemAt(pos)
        if not item:
            return
        entry = item.data(Qt.UserRole)
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background: #1c1c1e; color: #e0e0e0; border: 1px solid #3a3a3c; border-radius:6px; padding: 4px; }
            QMenu::item { padding: 6px 20px; border-radius: 4px; }
            QMenu::item:selected { background: #2c2c2e; }
        """)
        paste_action = menu.addAction("📋 Paste")
        paste_action.triggered.connect(lambda: self._paste_entry(entry))

        if self._mode == "history":
            fav_action = menu.addAction("⭐ Star")
            fav_action.triggered.connect(lambda: self._add_to_permanent(entry))
            del_action = menu.addAction("🗑 Delete")
            del_action.triggered.connect(lambda: self._remove_from_history(entry))
        else:
            del_action = menu.addAction("🗑 Remove Star")
            del_action.triggered.connect(lambda: self._remove_from_permanent(entry))
        menu.exec_(self.list_widget.viewport().mapToGlobal(pos))

    def _add_to_permanent(self, entry: ClipEntry):
        added = self.permanent.add(entry)
        msg = "Saved!" if added else "Updated!"
        self.status_label.setText(msg)
        QTimer.singleShot(3000, lambda: self.status_label.setText(""))

    def _remove_from_history(self, entry: ClipEntry):
        self.history.remove(entry.id)
        self._current_ids = []
        self._refresh_list()

    def _remove_from_permanent(self, entry: ClipEntry):
        self.permanent.remove(entry.id)
        self._current_ids = []
        self._refresh_list()

    def open_settings(self):
        old_cfg = dict(self.config)
        dlg = SettingsDialog(self.config, self)
        if dlg.exec_() == QDialog.Accepted:
            new_cfg = dlg.get_config()
            self.config.update(new_cfg)
            self.history.max_count = new_cfg["max_count"]
            self.history.max_days = new_cfg["max_days"]
            self.history.force_cleanup()
            save_config(self.config)

            # poll_ms 立即生效
            if hasattr(self, "_on_poll_changed"):
                self._on_poll_changed(new_cfg.get("poll_ms", 800))

            # 全局热键若变更，通知外部重注册
            if new_cfg.get("hotkey_global") != old_cfg.get("hotkey_global"):
                if hasattr(self, "_on_global_hotkey_changed"):
                    self._on_global_hotkey_changed(new_cfg.get("hotkey_global", ""))

            # 窗口内快捷键也立即重绑，避免仅更新显示文本但实际仍使用旧绑定。
            self._apply_window_shortcuts()

            # 底部提示刷新
            self._update_shortcut_hint()

            self._current_ids = []
            self._refresh_list()

    def _apply_window_shortcuts(self):
        """更新窗口内快捷键；WindowShortcut 在窗口任意子控件有焦点时均可用。"""
        actions = (self.config.get("hotkey_actions", "") or "").strip()
        mode = (self.config.get("hotkey_mode", "") or "").strip()
        self._actions_shortcut.setKey(QKeySequence(actions) if actions else QKeySequence())
        self._mode_shortcut.setKey(QKeySequence(mode) if mode else QKeySequence())
        self._actions_shortcut.setEnabled(bool(actions) and not QKeySequence(actions).isEmpty())
        self._mode_shortcut.setEnabled(bool(mode) and not QKeySequence(mode).isEmpty())

    def _trigger_actions_shortcut(self):
        current_item = self.list_widget.currentItem()
        if current_item:
            rect = self.list_widget.visualItemRect(current_item)
            self._on_context_menu(rect.center())

    def eventFilter(self, obj, event):
        from PyQt5.QtCore import QEvent
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
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPos() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton and hasattr(self, "_drag_pos"):
            self.move(event.globalPos() - self._drag_pos)


class HotkeySignalReceiver(QObject):
    """把热键工作线程的回调安全地切换到 Qt 主线程执行。"""
    def __init__(self, on_triggered, on_failed, parent=None):
        super().__init__(parent)
        self._on_triggered_callback = on_triggered
        self._on_failed_callback = on_failed

    @pyqtSlot()
    def handle_triggered(self):
        self._on_triggered_callback()

    @pyqtSlot(str)
    def handle_register_failed(self, hotkey):
        self._on_failed_callback(hotkey)


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

        # 接线：设置变更 → 立即生效
        self.window._on_poll_changed = self._apply_poll_ms
        self.window._on_global_hotkey_changed = self._apply_global_hotkey

        self._setup_tray()

        self.monitor = ClipboardChecker(poll_ms=self.config.get("poll_ms", 800))
        self.monitor.new_entry.connect(self._on_new_clip)
        self.monitor.start()

        self.hotkey_mgr = GlobalHotkeyManager(self.config.get("hotkey_global", "alt+v"))
        self._hotkey_receiver = HotkeySignalReceiver(
            self._toggle_window, self._on_hotkey_failed, self.app
        )
        self.hotkey_mgr.signal_triggered.connect(self._hotkey_receiver.handle_triggered)
        self.hotkey_mgr.signal_register_failed.connect(self._hotkey_receiver.handle_register_failed)
        self.hotkey_mgr.start_listening()

    def _apply_poll_ms(self, ms: int):
        try:
            self.monitor.set_poll_ms(int(ms))
        except Exception:
            pass

    def _apply_global_hotkey(self, hotkey_str: str):
        self.hotkey_mgr.update_hotkey(hotkey_str or "")

    def _on_hotkey_failed(self, s: str):
        display = normalize_shortcut_text(s) or s or "(空)"
        self.tray.showMessage(
            "剪贴板管理器",
            f"全局热键注册失败（可能被占用）：{display}",
            QSystemTrayIcon.Warning, 3000
        )

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
        self.tray.setToolTip("剪贴板管理器")

        menu = QMenu()
        menu.setStyleSheet("""
            QMenu { background: #1e1e38; color: #d0d0f0; border: 1px solid #3a3a6e; }
            QMenu::item:selected { background: #2d2d6e; }
        """)
        show_action = QAction("📋 显示历史", menu)
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
        if self.window.isVisible():
            self.window.refresh_if_dirty()

    def _force_cleanup(self):
        self.history.force_cleanup()
        if self.window.isVisible():
            self.window.refresh()
        self.tray.showMessage("剪贴板管理器", "历史清理完成",
                              QSystemTrayIcon.Information, 2000)

    def _quit(self):
        self.monitor.stop()
        self.hotkey_mgr.stop()
        try:
            self.history._flush_save()
        except Exception:
            pass
        self.permanent.close()
        self.app.quit()

    def run(self):
        self.tray.showMessage(
            "剪贴板管理器",
            "已启动！在设置里可自定义快捷键",
            QSystemTrayIcon.Information,
            3000
        )
        sys.exit(self.app.exec_())


if __name__ == "__main__":
    app = ClipboardManagerApp()
    app.run()