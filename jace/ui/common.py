"""Shared UI helpers: theme, background tasks and async image loading."""
import traceback

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QLabel, QMessageBox

from jace.net import session

ACCENT = "#3ddc84"

STYLE = f"""
* {{ font-family: "Inter", "Segoe UI", "Noto Sans", sans-serif; font-size: 13px; color: #e6e8eb; }}
QMainWindow, QDialog, #page {{ background: #16181d; }}
QWidget#sidebar {{ background: #101216; border-right: 1px solid #23262d; }}
QWidget#bottombar {{ background: #101216; border-top: 1px solid #23262d; }}
QLabel#brand {{ font-size: 20px; font-weight: 800; color: {ACCENT}; padding: 18px 16px 12px 16px; }}
QLabel#h1 {{ font-size: 22px; font-weight: 700; }}
QLabel#muted, QLabel[muted="true"] {{ color: #8b919c; }}
QPushButton#nav {{ text-align: left; padding: 11px 18px; border: none; border-radius: 8px;
    margin: 2px 10px; background: transparent; color: #aab0ba; font-size: 14px; }}
QPushButton#nav:hover {{ background: #1c1f26; color: #fff; }}
QPushButton#nav:checked {{ background: #1f2a24; color: {ACCENT}; font-weight: 600; }}
QPushButton {{ background: #262a33; border: 1px solid #323743; border-radius: 7px; padding: 7px 14px; }}
QPushButton:hover {{ background: #2e333e; }}
QPushButton:disabled {{ color: #5c616b; }}
QPushButton#primary {{ background: {ACCENT}; color: #0c1410; font-weight: 700; border: none; }}
QPushButton#primary:hover {{ background: #5ae69a; }}
QPushButton#primary:disabled {{ background: #2a4a37; color: #6b8a77; }}
QPushButton#play {{ background: {ACCENT}; color: #0c1410; font-weight: 800; font-size: 16px;
    border: none; border-radius: 9px; padding: 10px 38px; }}
QPushButton#play:hover {{ background: #5ae69a; }}
QPushButton#play:disabled {{ background: #2a4a37; color: #6b8a77; }}
QPushButton#danger {{ background: #3a1f24; border-color: #5a2a32; color: #ff8a95; }}
QLineEdit, QComboBox, QSpinBox, QPlainTextEdit, QTextBrowser {{ background: #1e2128; border: 1px solid #2f343e;
    border-radius: 7px; padding: 6px 8px; selection-background-color: {ACCENT}; selection-color: #000; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border-color: {ACCENT}; }}
QComboBox QAbstractItemView {{ background: #1e2128; border: 1px solid #2f343e; }}
QListWidget, QTreeWidget, QTableWidget {{ background: #1a1d23; border: 1px solid #262a32; border-radius: 9px;
    outline: none; }}
QListWidget::item {{ border-radius: 8px; padding: 4px; }}
QListWidget::item:selected, QTreeWidget::item:selected {{ background: #23332a; }}
QListWidget::item:hover {{ background: #20242b; }}
QTabWidget::pane {{ border: 1px solid #262a32; border-radius: 9px; top: -1px; }}
QTabBar::tab {{ background: transparent; padding: 8px 16px; color: #8b919c; border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ color: {ACCENT}; border-bottom: 2px solid {ACCENT}; }}
QProgressBar {{ background: #1e2128; border: none; border-radius: 4px; height: 8px; text-align: center; font-size: 1px; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; }}
QScrollBar::handle:vertical {{ background: #2e333d; border-radius: 5px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 16px; height: 16px; }}
QGroupBox {{ border: 1px solid #262a32; border-radius: 9px; margin-top: 14px; padding: 12px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 4px; color: #aab0ba; }}
QFrame#card {{ background: #1c1f26; border: 1px solid #262a32; border-radius: 12px; }}
QToolTip {{ background: #262a33; color: #fff; border: 1px solid #3a3f4b; }}
"""


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(str)
    status = Signal(str)
    progress = Signal(int, int)


_live: set = set()


class Task(QRunnable):
    """Run fn in a worker thread. If fn accepts a `callback` kwarg it gets a
    minecraft-launcher-lib style callback dict wired to the status/progress signals."""

    def __init__(self, fn, *args, use_callback=False, **kwargs):
        super().__init__()
        self.fn, self.args, self.kwargs, self.use_callback = fn, args, kwargs, use_callback
        self.signals = _Signals()
        self._max = 0

    def run(self):
        try:
            if self.use_callback:
                def set_max(m):
                    self._max = int(m)
                cb = {"setStatus": lambda s: self.signals.status.emit(str(s)),
                      "setProgress": lambda v: self.signals.progress.emit(int(v), self._max),
                      "setMax": set_max}
                self.kwargs["callback"] = cb
            result = self.fn(*self.args, **self.kwargs)
            self.signals.done.emit(result)
        except Exception as e:  # noqa: BLE001 - surface every failure in the UI
            traceback.print_exc()
            self.signals.failed.emit(str(e) or e.__class__.__name__)


def run_task(fn, *args, on_done=None, on_error=None, on_status=None, on_progress=None,
             use_callback=False, **kwargs) -> Task:
    t = Task(fn, *args, use_callback=use_callback, **kwargs)
    if on_done:
        t.signals.done.connect(on_done)
    t.signals.failed.connect(on_error or (lambda msg: show_error(None, msg)))
    if on_status:
        t.signals.status.connect(on_status)
    if on_progress:
        t.signals.progress.connect(on_progress)
    # keep the task (and its signal object) alive until results reach the UI thread
    t.setAutoDelete(False)
    _live.add(t)
    t.signals.done.connect(lambda *_: _live.discard(t))
    t.signals.failed.connect(lambda *_: _live.discard(t))
    QThreadPool.globalInstance().start(t)
    return t


def show_error(parent, msg: str, title="Something went wrong"):
    QMessageBox.critical(parent, title, msg)


# --- Async images ---------------------------------------------------------------
_image_cache: dict[str, QImage] = {}


def fetch_image(url: str) -> QImage:
    if url in _image_cache:
        return _image_cache[url]
    r = session.get(url, timeout=20)
    r.raise_for_status()
    img = QImage.fromData(r.content)
    _image_cache[url] = img
    return img


def load_image_into(label: QLabel, url: str, size: int):
    """Fill a label with a remote image, scaled to size x size."""
    if not url:
        return

    def apply(img):
        try:
            if not img.isNull():
                label.setPixmap(QPixmap.fromImage(img).scaled(
                    size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        except RuntimeError:
            pass  # label was deleted before the image arrived
    if url in _image_cache:
        apply(_image_cache[url])
    else:
        run_task(fetch_image, url, on_done=apply, on_error=lambda m: None)


def fmt_count(n: int) -> str:
    for unit, div in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if n >= div:
            return f"{n / div:.1f}{unit}"
    return str(n)
