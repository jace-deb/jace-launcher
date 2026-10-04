"""Browse and install mods, modpacks, resource packs and shaders from Modrinth / CurseForge."""
import webbrowser

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QInputDialog,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
                               QVBoxLayout, QWidget)

from jace.content import (PROJECT_TYPES, SOURCES, delete_project, install_modpack_version, install_version,
                          installed_projects)
from jace.instances import list_instances
from jace.ui.common import fetch_image, fmt_count, load_image_into, run_task, show_error

PAGE_SIZE = 20


class VersionPicker(QDialog):
    def __init__(self, title, versions, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Install {title}")
        self.resize(560, 420)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f"<b>{title}</b> - pick a version (newest compatible is selected):"))
        self.list = QListWidget()
        for v in versions:
            gv = ", ".join(v["game_versions"][:4]) + ("…" if len(v["game_versions"]) > 4 else "")
            ld = ", ".join(v["loaders"])
            text = f"{v['name']}\n{gv}   {ld}   {v['date']}"
            if not v["file"]:
                text += "   (manual download only)"
            it = QListWidgetItem(text)
            it.setData(Qt.ItemDataRole.UserRole, v)
            self.list.addItem(it)
        self.list.setCurrentRow(0)
        self.list.itemDoubleClicked.connect(lambda *_: self.accept())
        lay.addWidget(self.list)
        self.deps_note = QLabel("Required dependencies are installed automatically.")
        self.deps_note.setObjectName("muted")
        lay.addWidget(self.deps_note)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText("Install")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def selected(self):
        it = self.list.currentItem()
        return it.data(Qt.ItemDataRole.UserRole) if it else None


class ResultCard(QFrame):
    install_clicked = Signal(dict)
    delete_clicked = Signal(dict, list)

    def __init__(self, p: dict):
        super().__init__()
        self.p = p
        self.installed_files: list = []
        self.setObjectName("card")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        icon = QLabel()
        icon.setFixedSize(56, 56)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet("background:#262a33;border-radius:10px;")
        load_image_into(icon, p["icon_url"], 56)
        lay.addWidget(icon)
        text = QVBoxLayout()
        title = QLabel(f"<b style='font-size:15px'>{p['title']}</b>  <span style='color:#8b919c'>by {p['author']}</span>")
        title.setTextFormat(Qt.TextFormat.RichText)
        desc = QLabel(p["description"])
        desc.setWordWrap(True)
        desc.setObjectName("muted")
        meta = QLabel(f"⬇ {fmt_count(p['downloads'])}   ·   {SOURCES[p['source']].name}")
        meta.setObjectName("muted")
        text.addWidget(title)
        text.addWidget(desc)
        text.addWidget(meta)
        lay.addLayout(text, 1)
        btns = QVBoxLayout()
        self.btn = QPushButton("Install")
        self.btn.setObjectName("primary")
        self.btn.setMinimumWidth(84)
        self.btn.clicked.connect(self._clicked)
        page = QPushButton("Page")
        page.clicked.connect(lambda: webbrowser.open(p["url"]))
        btns.addWidget(self.btn)
        btns.addWidget(page)
        btns.addStretch()
        lay.addLayout(btns)


    def _clicked(self):
        if self.installed_files:
            self.delete_clicked.emit(self.p, self.installed_files)
        else:
            self.install_clicked.emit(self.p)

    def set_installed(self, files: list | None):
        """Already in the instance -> the button deletes it instead of installing."""
        self.installed_files = list(files or [])
        installed = bool(self.installed_files)
        self.btn.setText("Delete" if installed else "Install")
        self.btn.setObjectName("danger" if installed else "primary")
        self.btn.setToolTip("Remove it from this instance: " + ", ".join(f.name for f in self.installed_files)
                            if installed else "")
        self.btn.style().unpolish(self.btn)        # re-apply the stylesheet for the new objectName
        self.btn.style().polish(self.btn)


class BrowsePage(QWidget):
    instance_created = Signal(object)

    def __init__(self, runner):
        super().__init__()
        self.runner = runner  # main window: runner.run_job(fn, label, on_done, use_callback)
        self.setObjectName("page")
        self.offset = 0
        self.query_id = 0
        self.installed: dict = {}
        self._installed_gen = 0
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        t = QLabel("Browse")
        t.setObjectName("h1")
        lay.addWidget(t)

        row = QHBoxLayout()
        self.source = QComboBox()
        for sid, s in SOURCES.items():
            self.source.addItem(s.name, sid)
        self.kind = QComboBox()
        for k, label in PROJECT_TYPES.items():
            self.kind.addItem(label, k)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search…")
        self.sort = QComboBox()
        self.sort.addItems(["Relevance", "Downloads", "Followers", "Newest", "Updated"])
        row.addWidget(self.source)
        row.addWidget(self.kind)
        row.addWidget(self.search, 1)
        row.addWidget(self.sort)
        lay.addLayout(row)

        row2 = QHBoxLayout()
        self.target_label = QLabel("Install into:")
        self.target = QComboBox()
        self.target.setMinimumWidth(260)
        self.filter = QCheckBox("Only show compatible with this instance")
        self.filter.setChecked(True)
        row2.addWidget(self.target_label)
        row2.addWidget(self.target)
        row2.addWidget(self.filter)
        row2.addStretch()
        self.count = QLabel("")
        self.count.setObjectName("muted")
        row2.addWidget(self.count)
        lay.addLayout(row2)

        self.results = QListWidget()
        self.results.setSpacing(4)
        self.results.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.results.setStyleSheet("QListWidget { background: transparent; border: none; } "
                                   "QListWidget::item, QListWidget::item:hover, QListWidget::item:selected "
                                   "{ background: transparent; }")
        lay.addWidget(self.results, 1)
        self.more = QPushButton("Load more")
        self.more.clicked.connect(lambda: self.do_search(append=True))
        self.more.hide()
        lay.addWidget(self.more, 0, Qt.AlignmentFlag.AlignHCenter)

        self._timer = QTimer(self, singleShot=True, interval=350)
        self._timer.timeout.connect(self.do_search)
        self.search.textChanged.connect(lambda: self._timer.start())
        for w in (self.source, self.kind, self.sort, self.target):
            w.currentIndexChanged.connect(lambda *_: self.do_search())
        self.filter.toggled.connect(lambda *_: self.do_search())
        self.kind.currentIndexChanged.connect(self._kind_changed)
        self.refresh_instances()

    # --- instance targets
    def refresh_instances(self, select_id=None):
        cur = select_id or self.target.currentData()
        self.target.blockSignals(True)
        self.target.clear()
        for inst in list_instances():
            self.target.addItem(f"{inst.name}  ({inst.describe()})", inst.id)
        idx = self.target.findData(cur)
        if idx >= 0:
            self.target.setCurrentIndex(idx)
        self.target.blockSignals(False)

    def target_instance(self):
        iid = self.target.currentData()
        return next((i for i in list_instances() if i.id == iid), None)

    def open_for(self, inst, kind):
        self.refresh_instances(inst.id)
        idx = self.kind.findData(kind)
        if idx >= 0:
            self.kind.setCurrentIndex(idx)
        self.do_search()

    # --- what's already installed in the target instance
    def refresh_installed(self):
        kind = self.kind.currentData()
        inst = self.target_instance()
        self._installed_gen += 1
        gen = self._installed_gen
        if kind == "modpack" or not inst:          # modpacks always show Install
            self.installed = {}
            self._apply_installed()
            return

        def done(found):
            if gen == self._installed_gen:
                self.installed = found
                self._apply_installed()
        run_task(installed_projects, inst, kind, on_done=done, on_error=lambda m: None)

    def _apply_installed(self):
        for i in range(self.results.count()):
            card = self.results.itemWidget(self.results.item(i))
            if isinstance(card, ResultCard) and card.p["project_type"] != "modpack":
                card.set_installed(self.installed.get(str(card.p["id"])))

    def delete(self, p: dict, files: list):
        inst = self.target_instance()
        if not inst:
            return
        names = "\n".join(f.name for f in files)
        if QMessageBox.question(self, "Delete from instance",
                                f"Delete {p['title']} from {inst.name}?\n\n{names}") != QMessageBox.StandardButton.Yes:
            return
        try:
            delete_project(inst, self.kind.currentData(), files)
        except OSError as e:
            show_error(self, str(e), "Couldn't delete")
            return
        self.installed.pop(str(p["id"]), None)
        self._apply_installed()
        self.runner.notify(f"Deleted {p['title']} from {inst.name}")
        self.refresh_installed()

    def _kind_changed(self):
        is_pack = self.kind.currentData() == "modpack"
        for w in (self.target_label, self.target, self.filter):
            w.setVisible(not is_pack)

    def showEvent(self, e):
        super().showEvent(e)
        if self.results.count() == 0:
            self.do_search()

    # --- searching
    def do_search(self, append=False):
        src = SOURCES[self.source.currentData()]
        kind = self.kind.currentData()
        if not src.available():
            self.results.clear()
            self.more.hide()
            self.count.setText("")
            self._notice("CurseForge needs an API key. Get a free one at console.curseforge.com, "
                         "then paste it in Settings → Integrations.")
            return
        if not append:
            self.offset = 0
            self.refresh_installed()
        gv = loader = None
        inst = self.target_instance()
        if kind != "modpack" and inst and self.filter.isChecked():
            gv = inst.mc_version
            loader = inst.loader if kind == "mod" else None
        self.query_id += 1
        qid = self.query_id
        self.count.setText("Searching…")

        def done(res):
            if qid != self.query_id:
                return
            hits, total = res
            if not append:
                self.results.clear()
            for p in hits:
                card = ResultCard(p)
                card.install_clicked.connect(self.install)
                card.delete_clicked.connect(self.delete)
                if p["project_type"] != "modpack":
                    card.set_installed(self.installed.get(str(p["id"])))
                it = QListWidgetItem()
                it.setSizeHint(QSize(100, card.sizeHint().height() + 4))
                it.setFlags(Qt.ItemFlag.NoItemFlags)
                self.results.addItem(it)
                self.results.setItemWidget(it, card)
            self.offset += len(hits)
            self.count.setText(f"{total:,} results")
            self.more.setVisible(self.offset < total and len(hits) > 0)
            if self.results.count() == 0:
                self._notice("No results.")

        def fail(msg):
            if qid == self.query_id:
                self.count.setText("")
                self._notice(f"Search failed: {msg}")
        run_task(src.search, self.search.text().strip(), kind, gv, loader, self.sort.currentText(),
                 self.offset, PAGE_SIZE, on_done=done, on_error=fail)

    def _notice(self, text):
        self.results.clear()
        lab = QLabel(text)
        lab.setWordWrap(True)
        lab.setObjectName("muted")
        lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
        it = QListWidgetItem()
        it.setSizeHint(QSize(100, 80))
        it.setFlags(Qt.ItemFlag.NoItemFlags)
        self.results.addItem(it)
        self.results.setItemWidget(it, lab)

    # --- installing
    def install(self, p: dict):
        kind = p["project_type"] if p["project_type"] in PROJECT_TYPES else self.kind.currentData()
        src = SOURCES[p["source"]]
        inst = None if kind == "modpack" else self.target_instance()
        if kind != "modpack" and not inst:
            show_error(self, "Create an instance first (Library → New instance).")
            return
        gv = inst.mc_version if inst else None
        loader = inst.loader if inst and kind == "mod" else None
        if inst and kind == "mod" and inst.loader == "vanilla":
            show_error(self, f"'{inst.name}' is vanilla. Create an instance with a mod loader "
                             "(Fabric, Forge, NeoForge, Quilt…) to use mods.")
            return

        def got_versions(vs):
            if not vs:
                where = f" for {inst.describe()}" if inst else ""
                show_error(self, f"No compatible version of {p['title']}{where}.", "Not available")
                return
            dlg = VersionPicker(p["title"], vs, self)
            if kind != "mod":
                dlg.deps_note.hide()
            if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.selected():
                return
            v = dlg.selected()
            if kind == "modpack":
                name, ok = QInputDialog.getText(self, "Instance name", "Name for the new instance:", text=p["title"])
                if not ok:
                    return

                def pack_done(res):
                    new_inst, manual = res
                    if p.get("icon_url"):        # use the modpack's own icon for the instance
                        def save_icon(img, inst=new_inst):
                            if not img.isNull():
                                img.save(str(inst.icon_path), "PNG")
                                self.instance_created.emit(inst)
                        run_task(fetch_image, p["icon_url"], on_done=save_icon, on_error=lambda m: None)
                    self.refresh_instances()
                    self.instance_created.emit(new_inst)
                    if manual:
                        QMessageBox.warning(self, "Some files need manual download",
                                            "These authors don't allow launcher downloads. Download them and put "
                                            "them in the instance's mods folder:\n\n" + "\n".join(manual))
                self.runner.run_job(install_modpack_version, f"Installing {p['title']}", pack_done,
                                    True, v, name=name.strip() or p["title"])
            else:
                self.runner.run_job(
                    lambda callback: install_version(inst, v, kind, True, callback["setStatus"]),
                    f"Installing {p['title']}",
                    lambda files: (self.runner.notify(f"Installed {', '.join(files)} into {inst.name}"),
                                   self.refresh_installed()), True)

        self.runner.notify(f"Loading versions of {p['title']}…")
        run_task(src.versions, p["id"], gv, loader, kind, on_done=got_versions,
                 on_error=lambda m: show_error(self, m))
