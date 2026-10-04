"""Instance icons: a custom image if the instance has one, else a generated tile."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter

LOADER_COLORS = {"vanilla": "#5b8c3a", "fabric": "#c6a875", "quilt": "#9c5bd6", "forge": "#df7a3a",
                 "neoforge": "#e0a046", "legacyfabric": "#4f8fd6"}


def icon_image(inst, size=256) -> QImage:
    if inst.icon_path.is_file():
        img = QImage(str(inst.icon_path))
        if not img.isNull():
            return img.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                              Qt.TransformationMode.SmoothTransformation)
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(LOADER_COLORS.get(inst.loader, "#555")))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(0, 0, size, size, size * 0.19, size * 0.19)
    p.setPen(QColor("#ffffff"))
    f = QFont()
    f.setBold(True)
    f.setPixelSize(size // 3)
    p.setFont(f)
    initials = "".join(w[0] for w in inst.name.split()[:2]).upper() or "?"
    p.drawText(img.rect(), Qt.AlignmentFlag.AlignCenter, initials)
    p.end()
    return img
