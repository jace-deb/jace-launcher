"""Minecraft: Bedrock Edition page: install/play the Bedrock launcher, manage worlds and
packs, and get Bedrock content from Jace Store."""
import html

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMessageBox, QPushButton, QTabWidget, QVBoxLayout, QWidget)

from jace import bedrock
from jace.content import JaceStore
from jace.ui.common import run_task, show_error
from jace.ui.settings_page import open_folder

STORE_TYPES = [
    ("All Bedrock", "bedrock_addon,bedrock_texture,bedrock_world,bedrock_skin,bedrock_template"),
    ("Add-Ons", "bedrock_addon"),
    ("Texture Packs", "bedrock_texture"),
    ("Worlds", "bedrock_world"),
    ("Skin Packs", "bedrock_skin"),
    ("World Templates", "bedrock_template"),
]


def _muted(text=""):
    lab = QLabel(text)
    lab.setObjectName("muted")
    lab.setWordWrap(True)
    return lab


class ContentList(QWidget):
    """Worlds, or packs: list + Import / Delete / Open folder."""

    def __init__(self, page: "BedrockPage", kinds: list[str]):
        super().__init__()
        self.page, self.kinds = page, kinds
        lay = QVBoxLayout(self)
        self.list = QListWidget()
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        imp = QPushButton("Import file…")
        imp.setObjectName("primary")
        imp.clicked.connect(page.import_files)
        rm = QPushButton("Delete")
        rm.setObjectName("danger")
        rm.clicked.connect(self._delete)
        op = QPushButton("Open folder")
        op.clicked.connect(lambda: open_folder(bedrock.com_mojang() / bedrock.FOLDERS[self.kinds[0]]))
        row.addWidget(imp)
        row.addWidget(op)
        row.addStretch()
        row.addWidget(rm)
        lay.addLayout(row)

    def fill(self, content: dict):
        self.list.clear()
        labels = {"resource": "Resource pack", "behavior": "Behavior pack", "skin": "Skin pack",
                  "template": "World template", "world": "World"}
        for kind in self.kinds:
            for item in content.get(kind, []):
                it = QListWidgetItem(item["name"] if len(self.kinds) == 1 else f"{item['name']}\n{labels[kind]}")
                it.setData(Qt.ItemDataRole.UserRole, item["path"])
                self.list.addItem(it)
        if self.list.count() == 0:
            self.list.addItem("Nothing here yet. Import a file or get something from the Jace Store tab.")

    def _delete(self):
        it = self.list.currentItem()
        path = it and it.data(Qt.ItemDataRole.UserRole)
        if not path:
            return
        name = it.text().splitlines()[0]
        if QMessageBox.question(self, "Delete", f"Delete {name}? This can't be undone.") != QMessageBox.StandardButton.Yes:
            return
        try:
            bedrock.remove(path)
        except (OSError, bedrock.BedrockError) as e:
            show_error(self, str(e))
        self.page.refresh()


class StoreTab(QWidget):
    def __init__(self, page: "BedrockPage"):
        super().__init__()
        self.page = page
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText("Search Bedrock add-ons, texture packs, worlds…")
        self.query.returnPressed.connect(self.search)
        self.kind = QComboBox()
        for label, t in STORE_TYPES:
            self.kind.addItem(label, t)
        self.kind.currentIndexChanged.connect(self.search)
        go = QPushButton("Search")
        go.clicked.connect(self.search)
        top.addWidget(self.query, 1)
        top.addWidget(self.kind)
        top.addWidget(go)
        lay.addLayout(top)
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda _: self.install())
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        self.status = _muted()
        row.addWidget(self.status, 1)
        self.install_btn = QPushButton("Install")
        self.install_btn.setObjectName("primary")
        self.install_btn.clicked.connect(self.install)
        row.addWidget(self.install_btn)
        lay.addLayout(row)
        self.loaded = False

    def search(self):
        self.loaded = True
        self.status.setText("Searching Jace Store…")
        self.list.clear()

        def done(res):
            hits, total = res
            self.list.clear()
            for h in hits:
                it = QListWidgetItem(f"{h['title']}\n{h.get('description') or ''}")
                it.setData(Qt.ItemDataRole.UserRole, h["id"])
                it.setToolTip(h.get("description") or "")
                self.list.addItem(it)
            self.status.setText(f"{total} result(s)" if hits else
                                "Nothing yet. Bedrock creators can publish here: Jace Store → Minecraft Bedrock.")
        def fail(m):
            self.status.setText("Jace Store's Bedrock section isn't open yet - check back soon." if "400" in m
                                else f"Couldn't reach Jace Store: {m}")
        run_task(JaceStore().search, self.query.text().strip(), self.kind.currentData(),
                 on_done=done, on_error=fail)

    def install(self):
        it = self.list.currentItem()
        slug = it and it.data(Qt.ItemDataRole.UserRole)
        if not slug:
            return
        self.install_btn.setEnabled(False)

        def done(added):
            self.install_btn.setEnabled(True)
            self.status.setText("Installed: " + ", ".join(added))
            self.page.refresh()

        def fail(m):
            self.install_btn.setEnabled(True)
            self.status.setText(m)
        run_task(bedrock.install_from_store, slug, on_done=done, on_error=fail, on_status=self.status.setText)


class BedrockPage(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("page")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        title = QLabel("Minecraft Bedrock")
        title.setObjectName("h1")
        lay.addWidget(title)
        if bedrock.IS_WIN:
            blurb = ("Play Minecraft: Bedrock Edition from the Microsoft Store / Xbox app, and add worlds and packs "
                     "from Jace Store or your own files.")
        else:
            blurb = ("Play Minecraft: Bedrock Edition with the <b>Minecraft Bedrock Launcher</b> (open source, "
                     "<a href='https://minecraft-linux.github.io' style='color:#3ddc84'>minecraft-linux.github.io</a>). "
                     "It runs the Android version of Bedrock, so you need to <b>own Minecraft on Google Play</b>. "
                     "Sign in with Google in its window the first time. Jace Launcher never sees your Google account.")
        sub = _muted(blurb)
        sub.setTextFormat(Qt.TextFormat.RichText)
        sub.setOpenExternalLinks(True)
        lay.addWidget(sub)

        card = QFrame()
        card.setObjectName("card")
        cl = QHBoxLayout(card)
        cl.setContentsMargins(18, 14, 18, 14)
        self.state = QLabel()
        self.state.setWordWrap(True)
        self.state.setTextFormat(Qt.TextFormat.RichText)
        cl.addWidget(self.state, 1)
        self.install_btn = QPushButton("Install Bedrock launcher")
        self.install_btn.setObjectName("primary")
        self.install_btn.clicked.connect(self.install)
        self.update_btn = QPushButton("Update")
        self.update_btn.clicked.connect(self.update_launcher)
        self.play_btn = QPushButton("▶  Play Bedrock")
        self.play_btn.setObjectName("play")
        self.play_btn.clicked.connect(self.play)
        for b in (self.install_btn, self.update_btn, self.play_btn):
            cl.addWidget(b)
        lay.addWidget(card)

        self.tabs = QTabWidget()
        self.worlds = ContentList(self, ["world"])
        self.packs = ContentList(self, ["behavior", "resource", "skin", "template"])
        self.store = StoreTab(self)
        self.tabs.addTab(self.worlds, "Worlds")
        self.tabs.addTab(self.packs, "Packs")
        self.tabs.addTab(self.store, "Jace Store")
        self.tabs.currentChanged.connect(lambda i: self.store.loaded or i != 2 or self.store.search())
        lay.addWidget(self.tabs, 1)
        self._busy = False

    def showEvent(self, e):
        super().showEvent(e)
        self.refresh()

    def refresh(self):
        kind = bedrock.installed()
        why = bedrock.unsupported_reason()
        names = {"flatpak": "installed (Flatpak)", "native": "installed", "mac": "installed",
                 "windows": "Bedrock opens from the Microsoft Store / Xbox app"}
        if why:
            self.state.setText(f"<span style='color:#e0b44a'>{html.escape(why)}</span>")
        elif kind:
            self.state.setText(f"<b>Minecraft Bedrock Launcher</b> {names[kind]}")
        else:
            self.state.setText("<b>Minecraft Bedrock Launcher</b> isn't installed yet. "
                               "One click installs it" + (" from Flathub." if not bedrock.IS_MAC else "."))
        busy = self._busy
        self.install_btn.setVisible(not kind and not bedrock.IS_WIN)
        self.install_btn.setEnabled(not busy and not why)
        self.update_btn.setVisible(kind in ("flatpak", "mac"))
        self.update_btn.setEnabled(not busy)
        self.play_btn.setVisible(bool(kind))
        try:
            content = bedrock.list_content()
        except OSError:
            content = {}
        self.worlds.fill(content)
        self.packs.fill(content)

    def _job(self, fn, done_text):
        self._busy = True
        self.refresh()

        def done(_):
            self._busy = False
            self.refresh()
            self.state.setText(self.state.text() + f"<br><span style='color:#3ddc84'>{html.escape(done_text)}</span>")

        def fail(m):
            self._busy = False
            self.refresh()
            show_error(self, m)
        run_task(fn, on_done=done, on_error=fail, on_status=lambda t: self.state.setText(html.escape(t)))

    def install(self):
        self._job(bedrock.install, "Installed! Click Play Bedrock and sign in with Google in its window.")

    def update_launcher(self):
        self._job(bedrock.update, "Up to date")

    def play(self):
        try:
            bedrock.play()
        except (OSError, bedrock.BedrockError) as e:
            show_error(self, str(e))

    def import_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Import Bedrock files", "",
                                                "Bedrock files (*.mcpack *.mcaddon *.mcworld *.mctemplate *.zip)")
        if not files:
            return
        added, problems = [], []
        for f in files:
            try:
                added += bedrock.import_file(f)
            except (OSError, bedrock.BedrockError) as e:
                problems.append(str(e))
        self.refresh()
        if problems:
            show_error(self, "\n".join(problems), "Some files weren't imported")
        if added:
            QMessageBox.information(self, "Imported", "\n".join(added) +
                                    "\n\nTurn packs on in a world's Resource Packs / Behavior Packs settings.")
