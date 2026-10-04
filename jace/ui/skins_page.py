"""Skin & cape changer with a local skin library."""
import re

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize, Qt
from PySide6.QtGui import QIcon, QImage
from PySide6.QtWidgets import (QButtonGroup, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QInputDialog, QLabel,
                               QListWidget, QListWidgetItem, QMessageBox, QPushButton, QRadioButton, QVBoxLayout,
                               QWidget)

from jace import accounts as acc_mod
from jace.accounts import accounts
from jace.config import SKINS_DIR, read_json, write_json
from jace.skin_render import detect_slim, render_cape, render_head, render_skin
from jace.ui.common import fetch_image, run_task, show_error

STEVE = "https://textures.minecraft.net/texture/31f477eb1a7beee631c2ca64d06f8f68fa93a3386d04452ab27f43acdf1b60cb"
LIBRARY = SKINS_DIR / "library.json"


def image_png_bytes(img: QImage) -> bytes:
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(ba)


def valid_skin(img: QImage) -> bool:
    return not img.isNull() and img.width() % 64 == 0 and img.height() in (img.width(), img.width() // 2)


class SkinsPage(QWidget):
    def __init__(self, runner):
        super().__init__()
        self.runner = runner
        self.setObjectName("page")
        self.skin = QImage()           # skin currently shown in the preview
        self.skin_is_live = True       # preview == what's on the account
        self.cape = QImage()
        self.capes: list[dict] = []
        self.profile = None
        self._hold_preview = False     # keep a skin copied from a friend when the profile loads

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        t = QLabel("Skins & Capes")
        t.setObjectName("h1")
        outer.addWidget(t)
        self.who = QLabel("")
        self.who.setObjectName("muted")
        self.who.setWordWrap(True)
        outer.addWidget(self.who)

        body = QHBoxLayout()
        outer.addLayout(body, 1)

        # ---- preview card
        card = QFrame()
        card.setObjectName("card")
        cl = QVBoxLayout(card)
        prev = QHBoxLayout()
        self.front = QLabel()
        self.back = QLabel()
        for lab, cap in ((self.front, "Front"), (self.back, "Back")):
            box = QVBoxLayout()
            lab.setFixedSize(QSize(160, 320))
            lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
            box.addWidget(lab)
            c = QLabel(cap)
            c.setObjectName("muted")
            c.setAlignment(Qt.AlignmentFlag.AlignCenter)
            box.addWidget(c)
            prev.addLayout(box)
        cl.addLayout(prev)
        model = QHBoxLayout()
        model.addWidget(QLabel("Arm model:"))
        self.classic = QRadioButton("Classic (Steve)")
        self.slim = QRadioButton("Slim (Alex)")
        self.classic.setChecked(True)
        grp = QButtonGroup(self)
        grp.addButton(self.classic)
        grp.addButton(self.slim)
        self.slim.toggled.connect(lambda *_: self._mark_dirty())
        model.addWidget(self.classic)
        model.addWidget(self.slim)
        model.addStretch()
        cl.addLayout(model)
        self.apply_btn = QPushButton("Apply skin to account")
        self.apply_btn.setObjectName("primary")
        self.apply_btn.clicked.connect(self.apply_skin)
        cl.addWidget(self.apply_btn)
        body.addWidget(card)

        # ---- right column
        right = QVBoxLayout()
        grid = QGridLayout()
        b1 = QPushButton("Open skin file…")
        b1.clicked.connect(self.open_file)
        b2 = QPushButton("Copy from player…")
        b2.clicked.connect(self.from_player)
        b3 = QPushButton("Save to library")
        b3.clicked.connect(self.save_to_library)
        b4 = QPushButton("Reset to default")
        b4.clicked.connect(self.reset_skin)
        grid.addWidget(b1, 0, 0)
        grid.addWidget(b2, 0, 1)
        grid.addWidget(b3, 1, 0)
        grid.addWidget(b4, 1, 1)
        right.addLayout(grid)

        right.addWidget(self._section("Skin library  (click to preview, double-click to apply)"))
        self.library = QListWidget()
        self.library.setViewMode(QListWidget.ViewMode.IconMode)
        self.library.setIconSize(QSize(48, 48))
        self.library.setGridSize(QSize(96, 86))
        self.library.setMovement(QListWidget.Movement.Static)
        self.library.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.library.itemClicked.connect(self._library_preview)
        self.library.itemDoubleClicked.connect(lambda it: (self._library_preview(it), self.apply_skin()))
        self.library.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)
        from PySide6.QtGui import QAction
        rm = QAction("Remove from library", self.library)
        rm.triggered.connect(self._library_remove)
        self.library.addAction(rm)
        right.addWidget(self.library, 1)

        right.addWidget(self._section("Capes  (click to equip)"))
        self.cape_list = QListWidget()
        self.cape_list.setViewMode(QListWidget.ViewMode.IconMode)
        self.cape_list.setIconSize(QSize(40, 64))
        self.cape_list.setGridSize(QSize(110, 100))
        self.cape_list.setMovement(QListWidget.Movement.Static)
        self.cape_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.cape_list.setWordWrap(True)
        self.cape_list.itemClicked.connect(self.choose_cape)
        right.addWidget(self.cape_list, 1)
        body.addLayout(right, 1)

        self.load_library()

    def _section(self, text):
        lab = QLabel(text)
        lab.setStyleSheet("font-weight:600;color:#aab0ba;margin-top:8px;")
        return lab

    # ------------------------------------------------------------ account state
    def _account(self):
        a = accounts.current()
        return a if a and a["type"] == "msa" else None

    def showEvent(self, e):
        super().showEvent(e)
        self.reload()

    def reload(self):
        a = accounts.current()
        self.cape_list.clear()
        if not a:
            self.who.setText("Add an account on the Accounts page to change your skin.")
            self.apply_btn.setEnabled(False)
            self._load_url(STEVE, slim=False)
            return
        if a["type"] != "msa":
            self.who.setText(f"{a['username']} is an offline account. You can preview skins and build a library, "
                             "but only Microsoft accounts can upload skins and wear capes.")
            self.apply_btn.setEnabled(False)
            if self.skin.isNull():
                self._load_url(STEVE, slim=False)
            return
        self.who.setText(f"Signed in as {a['username']} - loading profile…")
        self.apply_btn.setEnabled(True)

        def fetch():
            acc = accounts.ensure_fresh(a)
            return acc_mod.get_profile(acc["access_token"])
        run_task(fetch, on_done=self._got_profile, on_error=lambda m: self.who.setText(f"Couldn't load profile: {m}"))

    def _got_profile(self, prof):
        if not prof:
            return
        self.profile = prof
        self.who.setText(f"Signed in as {prof['name']}")
        active = next((s for s in prof.get("skins", []) if s.get("state") == "ACTIVE"), None)
        if self._hold_preview:
            self._hold_preview = False
        elif active:
            self._load_url(active["url"], active.get("variant", "CLASSIC").upper() == "SLIM", live=True)
        self.capes = prof.get("capes", [])
        self._fill_capes()

    def _fill_capes(self):
        self.cape_list.clear()
        none = QListWidgetItem("No cape")
        none.setData(Qt.ItemDataRole.UserRole, None)
        self.cape_list.addItem(none)
        self.cape = QImage()
        for c in self.capes:
            it = QListWidgetItem(c.get("alias", "Cape") + ("\n✓ equipped" if c.get("state") == "ACTIVE" else ""))
            it.setData(Qt.ItemDataRole.UserRole, c["id"])
            self.cape_list.addItem(it)

            def done(img, it=it, active=c.get("state") == "ACTIVE"):
                try:
                    it.setIcon(QIcon(render_cape(img, 4)))
                except RuntimeError:
                    return
                if active:
                    self.cape = img
                    self._render()
            run_task(fetch_image, c["url"], on_done=done, on_error=lambda m: None)
        if not self.capes:
            none.setText("No capes on\nthis account")

    # ------------------------------------------------------------ preview
    def _set_preview(self, img: QImage, slim: bool | None, live=False):
        if not valid_skin(img):
            show_error(self, "That isn't a valid Minecraft skin (it must be a 64×64 or 64×32 PNG).")
            return
        self.skin = img
        self.slim.blockSignals(True)
        (self.slim if (detect_slim(img) if slim is None else slim) else self.classic).setChecked(True)
        self.slim.blockSignals(False)
        self.skin_is_live = live
        self._render()

    def _load_url(self, url, slim, live=False):
        run_task(fetch_image, url, on_done=lambda img: self._set_preview(img, slim, live),
                 on_error=lambda m: None)

    def _mark_dirty(self):
        self.skin_is_live = False
        self._render()

    def _render(self):
        slim = self.slim.isChecked()
        self.front.setPixmap(render_skin(self.skin, slim, back=False))
        self.back.setPixmap(render_skin(self.skin, slim, back=True, cape=self.cape))
        self.apply_btn.setText("Apply skin to account" + ("" if self.skin_is_live else "  •"))

    def show_preview(self, url: str, slim: bool):
        """Preview someone else's skin (from the Friends page) so it can be applied."""
        self._hold_preview = True
        self._load_url(url, slim)

    # ------------------------------------------------------------ actions
    def open_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose a skin", "", "PNG images (*.png)")
        if path:
            self._set_preview(QImage(path), None)

    def from_player(self):
        name, ok = QInputDialog.getText(self, "Copy skin", "Player username:")
        if not ok or not name.strip():
            return

        def got(res):
            url, slim, _cape = res
            self._load_url(url, slim)
        run_task(acc_mod.lookup_player_skin, name.strip(), on_done=got, on_error=lambda m: show_error(self, m))

    def apply_skin(self):
        a = self._account()
        if not a or self.skin.isNull():
            return
        data, slim = image_png_bytes(self.skin), self.slim.isChecked()

        def go():
            acc = accounts.ensure_fresh(a)
            return acc_mod.upload_skin(acc["access_token"], data, slim)

        def done(prof):
            self.runner.notify("Skin updated! It can take a minute to show up in-game.")
            if prof:
                self._got_profile(prof)
        self.runner.run_job(go, "Uploading skin", done)

    def reset_skin(self):
        a = self._account()
        if not a:
            return
        if QMessageBox.question(self, "Reset skin", "Reset your skin to the default?") != QMessageBox.StandardButton.Yes:
            return
        def done(prof):
            self.runner.notify("Skin reset.")
            if prof:
                self._got_profile(prof)
        self.runner.run_job(lambda: acc_mod.reset_skin(accounts.ensure_fresh(a)["access_token"]),
                            "Resetting skin", done)

    def choose_cape(self, it):
        a = self._account()
        if not a:
            return
        cape_id = it.data(Qt.ItemDataRole.UserRole)

        def done(prof):
            self.runner.notify("Cape updated!")
            if prof:
                self._got_profile(prof)
            else:
                self.reload()
        self.runner.run_job(lambda: acc_mod.set_cape(accounts.ensure_fresh(a)["access_token"], cape_id),
                            "Changing cape", done)

    # ------------------------------------------------------------ library
    def load_library(self):
        self.library.clear()
        meta = read_json(LIBRARY, {})
        for name, info in sorted(meta.items()):
            path = SKINS_DIR / f"{name}.png"
            img = QImage(str(path))
            if img.isNull():
                continue
            it = QListWidgetItem(QIcon(render_head(img, 48)), name)
            it.setData(Qt.ItemDataRole.UserRole, (name, info.get("slim", False)))
            self.library.addItem(it)

    def save_to_library(self):
        if self.skin.isNull():
            return
        name, ok = QInputDialog.getText(self, "Save skin", "Name:")
        name = re.sub(r"[^A-Za-z0-9 _-]+", "", name or "").strip()
        if not ok or not name:
            return
        self.skin.save(str(SKINS_DIR / f"{name}.png"), "PNG")
        meta = read_json(LIBRARY, {})
        meta[name] = {"slim": self.slim.isChecked()}
        write_json(LIBRARY, meta)
        self.load_library()

    def _library_preview(self, it):
        name, slim = it.data(Qt.ItemDataRole.UserRole)
        self._set_preview(QImage(str(SKINS_DIR / f"{name}.png")), slim)

    def _library_remove(self):
        it = self.library.currentItem()
        if not it:
            return
        name, _ = it.data(Qt.ItemDataRole.UserRole)
        meta = read_json(LIBRARY, {})
        meta.pop(name, None)
        write_json(LIBRARY, meta)
        (SKINS_DIR / f"{name}.png").unlink(missing_ok=True)
        self.load_library()
