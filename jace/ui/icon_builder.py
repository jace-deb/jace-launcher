"""Instance icon builder: shape + background + text, symbol or a Minecraft block/item texture."""
import random
import zipfile
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QLinearGradient, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGridLayout,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QSlider,
                               QTabWidget, QVBoxLayout, QWidget)

from jace.config import GAME_ROOT

SIZE = 256
SYMBOLS = list("★♥♦♣♠⚔⛏⚒☀☾✦❄☁⚡☠♛♜⚑✿❖⬢◆●▲✚✪♫⌂⚙")
PALETTE = ["#3ddc84", "#2f9e5f", "#4f8fd6", "#2b4c8c", "#9c5bd6", "#5b2a86", "#df7a3a", "#e0a046", "#d6455a",
           "#7a1f2b", "#e8d8a8", "#6b4a2b", "#3a3f4b", "#16181d", "#f2f2f2", "#00b4c8"]


# --- Minecraft textures from an installed client jar ------------------------------

_tex_cache: dict = {}


def find_client_jar() -> Path | None:
    jars = []
    for d in (GAME_ROOT / "versions").glob("*"):
        jar = d / f"{d.name}.jar"
        if jar.is_file() and jar.stat().st_size > 1_000_000:   # real client jars, not loader stubs
            jars.append(jar)
    return max(jars, key=lambda j: j.stat().st_mtime) if jars else None


def texture_names(jar: Path) -> list[str]:
    if jar not in _tex_cache:
        with zipfile.ZipFile(jar) as z:
            names = [n for n in z.namelist() if n.endswith(".png") and (
                n.startswith("assets/minecraft/textures/item/") or n.startswith("assets/minecraft/textures/block/")
                or n.startswith("assets/minecraft/textures/items/") or n.startswith("assets/minecraft/textures/blocks/"))]
        _tex_cache[jar] = sorted(names, key=lambda n: Path(n).stem)
    return _tex_cache[jar]


def load_texture(jar: Path, name: str) -> QImage:
    with zipfile.ZipFile(jar) as z:
        img = QImage.fromData(z.read(name))
    if not img.isNull() and img.height() > img.width():          # animated strip: first frame
        img = img.copy(0, 0, img.width(), img.width())
    return img


# --- Rendering ---------------------------------------------------------------------

def render(state: dict, size=SIZE) -> QImage:
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    rect = QRectF(0, 0, size, size)
    path = QPainterPath()
    if state["shape"] == "circle":
        path.addEllipse(rect)
    elif state["shape"] == "square":
        path.addRect(rect)
    else:
        r = size * state["roundness"] / 200
        path.addRoundedRect(rect, r, r)
    c1, c2 = QColor(state["color1"]), QColor(state["color2"])
    if state["background"] == "solid":
        p.fillPath(path, c1)
    else:
        end = QPointF(size, size) if state["background"] == "diagonal" else QPointF(0, size)
        g = QLinearGradient(QPointF(0, 0), end)
        g.setColorAt(0, c1)
        g.setColorAt(1, c2)
        p.fillPath(path, g)
    p.setClipPath(path)

    scale = state["content_size"] / 100
    kind = state["content"]
    if kind in ("text", "symbol") and state.get(kind):
        text = state[kind]
        f = QFont()
        f.setBold(True)
        f.setPixelSize(int(size * scale * (0.62 if kind == "symbol" or len(text) == 1 else
                                           0.5 if len(text) == 2 else 0.38)))
        p.setFont(f)
        if state["shadow"]:
            p.setPen(QColor(0, 0, 0, 110))
            p.drawText(rect.translated(size * 0.02, size * 0.025), Qt.AlignmentFlag.AlignCenter, text)
        p.setPen(QColor(state["fg"]))
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
    elif kind == "texture" and state.get("texture_img") is not None and not state["texture_img"].isNull():
        side = size * scale * 0.75
        target = QRectF((size - side) / 2, (size - side) / 2, side, side)
        tex = state["texture_img"].scaled(int(side), int(side), Qt.AspectRatioMode.KeepAspectRatio,
                                          Qt.TransformationMode.FastTransformation)   # crisp pixels
        if state["shadow"]:
            shadow = QImage(tex.size(), QImage.Format.Format_ARGB32)
            shadow.fill(Qt.GlobalColor.transparent)
            sp = QPainter(shadow)
            sp.drawImage(0, 0, tex)
            sp.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
            sp.fillRect(shadow.rect(), QColor(0, 0, 0, 110))
            sp.end()
            p.drawImage(target.topLeft() + QPointF(size * 0.025, size * 0.03), shadow)
        p.drawImage(target.topLeft(), tex)
    p.end()
    return img


class ColorButton(QPushButton):
    def __init__(self, color: str, on_change):
        super().__init__()
        self.setFixedSize(QSize(46, 28))
        self.on_change = on_change
        self.set_color(color)
        self.clicked.connect(self._pick)

    def set_color(self, color: str):
        self.color = color
        self.setStyleSheet(f"background:{color}; border:1px solid #444b57; border-radius:6px;")

    def _pick(self):
        c = QColorDialog.getColor(QColor(self.color), self, "Pick a color")
        if c.isValid():
            self.set_color(c.name())
            self.on_change()


class IconBuilderDialog(QDialog):
    def __init__(self, initial_text="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Icon builder")
        self.resize(820, 560)
        self.jar = find_client_jar()
        self.state = {"shape": "rounded", "roundness": 38, "background": "diagonal", "color1": "#3ddc84",
                      "color2": "#2b4c8c", "content": "text", "text": initial_text[:3].upper() or "J",
                      "symbol": "⛏", "fg": "#ffffff", "content_size": 80, "shadow": True,
                      "texture": None, "texture_img": None}

        outer = QHBoxLayout(self)
        left = QVBoxLayout()
        self.preview = QLabel()
        self.preview.setFixedSize(SIZE, SIZE)
        left.addWidget(self.preview)
        small = QHBoxLayout()
        self.small = [QLabel() for _ in range(3)]
        for lab in self.small:
            small.addWidget(lab)
        small.addStretch()
        left.addLayout(small)
        rnd = QPushButton("🎲  Randomize")
        rnd.clicked.connect(self.randomize)
        left.addWidget(rnd)
        left.addStretch()
        outer.addLayout(left)

        right = QVBoxLayout()
        form = QFormLayout()
        self.shape = QComboBox()
        for label, key in (("Rounded square", "rounded"), ("Circle", "circle"), ("Square", "square")):
            self.shape.addItem(label, key)
        self.shape.currentIndexChanged.connect(lambda: self._set("shape", self.shape.currentData()))
        form.addRow("Shape", self.shape)
        self.round = QSlider(Qt.Orientation.Horizontal)
        self.round.setRange(0, 100)
        self.round.setValue(self.state["roundness"])
        self.round.valueChanged.connect(lambda v: self._set("roundness", v))
        form.addRow("Roundness", self.round)
        self.bg = QComboBox()
        for label, key in (("Diagonal gradient", "diagonal"), ("Vertical gradient", "vertical"), ("Solid", "solid")):
            self.bg.addItem(label, key)
        self.bg.currentIndexChanged.connect(lambda: self._set("background", self.bg.currentData()))
        form.addRow("Background", self.bg)
        colors = QHBoxLayout()
        self.c1 = ColorButton(self.state["color1"], lambda: self._set("color1", self.c1.color))
        self.c2 = ColorButton(self.state["color2"], lambda: self._set("color2", self.c2.color))
        colors.addWidget(self.c1)
        colors.addWidget(self.c2)
        colors.addStretch()
        form.addRow("Colors", colors)
        swatches = QGridLayout()
        for i, col in enumerate(PALETTE):
            b = QPushButton()
            b.setFixedSize(QSize(22, 22))
            b.setStyleSheet(f"background:{col}; border:1px solid #444b57; border-radius:4px;")
            b.setToolTip("Click: first color · Right-click: second color")
            b.clicked.connect(lambda _=False, c=col: (self.c1.set_color(c), self._set("color1", c)))
            b.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            b.customContextMenuRequested.connect(lambda _=None, c=col: (self.c2.set_color(c), self._set("color2", c)))
            swatches.addWidget(b, i // 8, i % 8)
        form.addRow("", swatches)
        right.addLayout(form)

        self.tabs = QTabWidget()
        # text
        tw = QWidget()
        tf = QFormLayout(tw)
        self.text = QLineEdit(self.state["text"])
        self.text.setMaxLength(3)
        self.text.textChanged.connect(lambda t: self._set("text", t))
        tf.addRow("Text (1-3 letters)", self.text)
        self.fg = ColorButton(self.state["fg"], lambda: self._set("fg", self.fg.color))
        tf.addRow("Text color", self.fg)
        self.tabs.addTab(tw, "Text")
        # symbol
        sw = QWidget()
        sg = QGridLayout(sw)
        for i, sym in enumerate(SYMBOLS):
            b = QPushButton(sym)
            b.setFixedSize(QSize(36, 32))
            b.clicked.connect(lambda _=False, s=sym: self._set("symbol", s))
            sg.addWidget(b, i // 10, i % 10)
        self.tabs.addTab(sw, "Symbol")
        # block / item
        bw = QWidget()
        bl = QVBoxLayout(bw)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search blocks and items, e.g. diamond, grass, creeper…")
        bl.addWidget(self.search)
        self.textures = QListWidget()
        self.textures.setViewMode(QListWidget.ViewMode.IconMode)
        self.textures.setIconSize(QSize(32, 32))
        self.textures.setGridSize(QSize(46, 46))
        self.textures.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.textures.setMovement(QListWidget.Movement.Static)
        self.textures.currentItemChanged.connect(self._pick_texture)
        bl.addWidget(self.textures)
        self.tex_note = QLabel("")
        self.tex_note.setObjectName("muted")
        self.tex_note.setWordWrap(True)
        bl.addWidget(self.tex_note)
        self.search.textChanged.connect(self._fill_textures)
        self.tabs.addTab(bw, "Block / item")
        self.tabs.addTab(QLabel("No picture - just the background."), "None")
        self.tabs.currentChanged.connect(self._tab_changed)
        right.addWidget(self.tabs, 1)

        opts = QFormLayout()
        self.size_slider = QSlider(Qt.Orientation.Horizontal)
        self.size_slider.setRange(30, 120)
        self.size_slider.setValue(self.state["content_size"])
        self.size_slider.valueChanged.connect(lambda v: self._set("content_size", v))
        opts.addRow("Picture size", self.size_slider)
        self.shadow = QCheckBox("Drop shadow")
        self.shadow.setChecked(True)
        self.shadow.toggled.connect(lambda v: self._set("shadow", v))
        opts.addRow("", self.shadow)
        right.addLayout(opts)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Save).setText("Use this icon")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        right.addWidget(bb)
        outer.addLayout(right, 1)
        self._fill_textures()
        self._refresh()

    # -- state
    def _set(self, key, value):
        self.state[key] = value
        if key == "symbol":
            self.state["content"] = "symbol"
        self._refresh()

    def _tab_changed(self, i):
        self.state["content"] = ["text", "symbol", "texture", "none"][i]
        self._refresh()

    def _refresh(self):
        img = render(self.state)
        self.preview.setPixmap(QPixmap.fromImage(img))
        for lab, sz in zip(self.small, (64, 32, 16)):
            lab.setPixmap(QPixmap.fromImage(img.scaled(sz, sz, Qt.AspectRatioMode.KeepAspectRatio,
                                                       Qt.TransformationMode.SmoothTransformation)))

    def _fill_textures(self):
        self.textures.clear()
        if not self.jar:
            self.tex_note.setText("Install any Minecraft version (create an instance and press Play once) to use "
                                  "block and item pictures.")
            return
        q = self.search.text().strip().lower().replace(" ", "_")
        names = [n for n in texture_names(self.jar) if q in Path(n).stem]
        shown = names[:400]
        for n in shown:
            it = QListWidgetItem(QIcon(QPixmap.fromImage(load_texture(self.jar, n).scaled(
                32, 32, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation))), "")
            it.setToolTip(Path(n).stem.replace("_", " "))
            it.setData(Qt.ItemDataRole.UserRole, n)
            self.textures.addItem(it)
        more = f" Showing {len(shown)} of {len(names)} - type to narrow it down." if len(names) > len(shown) else ""
        self.tex_note.setText(f"Pictures from Minecraft {self.jar.stem}.{more}")

    def _pick_texture(self, it):
        if not it:
            return
        self.state["texture"] = it.data(Qt.ItemDataRole.UserRole)
        self.state["texture_img"] = load_texture(self.jar, self.state["texture"])
        self.state["content"] = "texture"
        self._refresh()

    def randomize(self):
        a, b = random.sample(PALETTE, 2)
        self.c1.set_color(a)
        self.c2.set_color(b)
        self.state.update(color1=a, color2=b, background=random.choice(["diagonal", "vertical", "solid"]),
                          roundness=random.randint(15, 60), shape=random.choice(["rounded", "rounded", "circle"]))
        if self.jar and random.random() < 0.6:
            names = texture_names(self.jar)
            self.state["texture"] = random.choice(names)
            self.state["texture_img"] = load_texture(self.jar, self.state["texture"])
            self.state["content"] = "texture"
            self.tabs.blockSignals(True)
            self.tabs.setCurrentIndex(2)
            self.tabs.blockSignals(False)
        else:
            self.state["symbol"] = random.choice(SYMBOLS)
            self.state["content"] = "symbol"
            self.tabs.blockSignals(True)
            self.tabs.setCurrentIndex(1)
            self.tabs.blockSignals(False)
        self.shape.setCurrentIndex(["rounded", "circle", "square"].index(self.state["shape"]))
        self.bg.setCurrentIndex(["diagonal", "vertical", "solid"].index(self.state["background"]))
        self.round.setValue(self.state["roundness"])
        self._refresh()

    def result_image(self) -> QImage:
        return render(self.state)
