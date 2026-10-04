"""Render a Minecraft skin (and cape) as a flat front/back figure with QPainter."""
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QImage, QPainter, QPixmap


def _part(skin: QImage, x, y, w, h, mirror=False) -> QImage:
    img = skin.copy(x, y, w, h)
    return img.flipped(Qt.Orientation.Horizontal) if mirror else img


def _hat_usable(skin: QImage) -> bool:
    """Old 64x32 skins often have a fully opaque (usually black) hat layer. Minecraft
    ignores it in that case ("Notch transparency hack"), so we do too."""
    if skin.height() >= 64:
        return True
    for y in range(0, 16):
        for x in range(32, 64):
            if skin.pixelColor(x, y).alpha() < 255:
                return True
    return False


def detect_slim(skin: QImage) -> bool:
    """Slim skins leave the 4th arm column transparent."""
    if skin.height() < 64:
        return False
    s = skin.width() // 64
    return skin.pixelColor(54 * s, 20 * s).alpha() == 0 and skin.pixelColor(55 * s, 31 * s).alpha() == 0


def render_skin(skin: QImage, slim: bool, back=False, cape: QImage | None = None, scale=10) -> QPixmap:
    if skin.isNull():
        return QPixmap()
    # Normalise HD skins down to 64px-wide coordinates
    if skin.width() != 64:
        skin = skin.scaledToWidth(64, Qt.TransformationMode.FastTransformation)
    skin = skin.convertToFormat(QImage.Format.Format_ARGB32)
    legacy = skin.height() < 64
    w = 3 if slim else 4

    canvas = QImage(16, 32, QImage.Format.Format_ARGB32)
    canvas.fill(Qt.GlobalColor.transparent)
    p = QPainter(canvas)

    def draw(img, x, y):
        p.drawImage(x, y, img)

    if not back:
        layers = [
            # (base rect, overlay rect, dest x, dest y)
            ((8, 8, 8, 8), (40, 8, 8, 8), 4, 0),                    # head
            ((20, 20, 8, 12), (20, 36, 8, 12), 4, 8),               # body
            ((44, 20, w, 12), (44, 36, w, 12), 4 - w, 8),           # right arm (viewer left)
            ((4, 20, 4, 12), (4, 36, 4, 12), 4, 20),                # right leg
        ]
        if legacy:
            draw(_part(skin, 44, 20, w, 12, True), 12, 8)
            draw(_part(skin, 4, 20, 4, 12, True), 8, 20)
        else:
            layers += [((36, 52, w, 12), (52, 52, w, 12), 12, 8),   # left arm
                       ((20, 52, 4, 12), (4, 52, 4, 12), 8, 20)]    # left leg
    else:
        layers = [
            ((24, 8, 8, 8), (56, 8, 8, 8), 4, 0),
            ((32, 20, 8, 12), (32, 36, 8, 12), 4, 8),
            ((48 + w, 20, w, 12), (48 + w, 36, w, 12), 12, 8),      # right arm now on viewer right
            ((12, 20, 4, 12), (12, 36, 4, 12), 8, 20),
        ]
        if legacy:
            draw(_part(skin, 48 + w, 20, w, 12, True), 4 - w, 8)
            draw(_part(skin, 12, 20, 4, 12, True), 4, 20)
        else:
            layers += [((40 + w, 52, w, 12), (56 + w, 52, w, 12), 4 - w, 8),
                       ((28, 52, 4, 12), (12, 52, 4, 12), 4, 20)]

    for base, overlay, x, y in layers:
        draw(_part(skin, *base), x, y)
    hat_ok = _hat_usable(skin)
    for base, overlay, x, y in layers:
        if not legacy or (overlay[1] < 32 and hat_ok):   # legacy skins only have the hat layer
            draw(_part(skin, *overlay), x, y)

    if back and cape is not None and not cape.isNull():
        cs = max(1, cape.width() // 64)
        draw(cape.copy(1 * cs, 1 * cs, 10 * cs, 16 * cs).scaled(10, 16), 3, 8)
    p.end()

    return QPixmap.fromImage(canvas.scaled(16 * scale, 32 * scale, Qt.AspectRatioMode.IgnoreAspectRatio,
                                           Qt.TransformationMode.FastTransformation))


def render_cape(cape: QImage, scale=6) -> QPixmap:
    if cape.isNull():
        return QPixmap()
    cs = max(1, cape.width() // 64)
    img = cape.copy(QRect(1 * cs, 1 * cs, 10 * cs, 16 * cs))
    return QPixmap.fromImage(img.scaled(10 * scale, 16 * scale, Qt.AspectRatioMode.IgnoreAspectRatio,
                                        Qt.TransformationMode.FastTransformation))


def render_head(skin: QImage, size=32) -> QPixmap:
    if skin.isNull():
        return QPixmap()
    if skin.width() != 64:
        skin = skin.scaledToWidth(64, Qt.TransformationMode.FastTransformation)
    head = QImage(8, 8, QImage.Format.Format_ARGB32)
    head.fill(Qt.GlobalColor.transparent)
    p = QPainter(head)
    p.drawImage(0, 0, skin.copy(8, 8, 8, 8))
    if _hat_usable(skin.convertToFormat(QImage.Format.Format_ARGB32)):
        p.drawImage(0, 0, skin.copy(40, 8, 8, 8))
    p.end()
    return QPixmap.fromImage(head.scaled(size, size, Qt.AspectRatioMode.IgnoreAspectRatio,
                                         Qt.TransformationMode.FastTransformation))

