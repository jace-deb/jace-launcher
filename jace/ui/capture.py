"""Camera and screen capture for calls (Qt Multimedia, on the UI thread).

Each picture is shrunk (camera to 640x360, screen to 1280x720 at most), turned into RGBA
and handed to the call engine through a voice.FrameSource."""
from __future__ import annotations

from PySide6.QtCore import QObject, QSize, Qt, Signal
from PySide6.QtGui import QGuiApplication, QImage

from jace import voice

LIMITS = {"camera": (QSize(640, 360), 24), "screen": (QSize(1280, 720), 12)}


class Capture(QObject):
    """One camera or screen capture. `failed` says why it stopped on its own."""
    failed = Signal(str)

    def __init__(self, kind: str, parent=None):
        super().__init__(parent)
        from PySide6.QtMultimedia import QCamera, QMediaCaptureSession, QMediaDevices, QScreenCapture, QVideoSink

        self.kind = kind
        self.limit, fps = LIMITS[kind]
        self.source = voice.FrameSource(fps)
        self.session = QMediaCaptureSession(self)
        self.sink = QVideoSink(self)
        self.sink.videoFrameChanged.connect(self._frame)
        self.session.setVideoSink(self.sink)
        self._last = 0.0
        if kind == "camera":
            if not QMediaDevices.videoInputs():
                raise RuntimeError("No camera found")
            self.device = QCamera(QMediaDevices.defaultVideoInput(), self)
            self.device.errorOccurred.connect(lambda _e, msg: self.failed.emit(msg or "The camera stopped"))
            self.session.setCamera(self.device)
        else:
            self.device = QScreenCapture(self)
            self.device.setScreen(QGuiApplication.primaryScreen())
            self.device.errorOccurred.connect(lambda _e, msg: self.failed.emit(msg or "Screen sharing stopped"))
            self.session.setScreenCapture(self.device)

    def start(self):
        self.device.start()

    def stop(self):
        self.device.stop()
        self.sink.videoFrameChanged.disconnect(self._frame)

    def _frame(self, frame):
        import time

        now = time.monotonic()
        if now - self._last < 1 / self.source.fps:      # only as many pictures as we send
            return
        self._last = now
        img = frame.toImage()
        if img.isNull():
            return
        if img.width() > self.limit.width() or img.height() > self.limit.height():
            img = img.scaled(self.limit, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        w, h = img.width() // 16 * 16, img.height() // 2 * 2       # rows without padding; even height for video
        if w < 16 or h < 2:
            return
        img = img.copy(0, 0, w, h).convertToFormat(QImage.Format.Format_RGBA8888)
        self.source.latest = (w, h, bytes(img.constBits())[: w * h * 4])
