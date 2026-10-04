"""Library of instances, the new-instance dialog and the instance editor."""
import shutil
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
                               QPushButton, QSpinBox, QTabWidget, QVBoxLayout, QWidget)

from jace.config import settings
from jace.instances import Instance, create_instance, list_instances
from jace.loaders import LOADERS, mojang_versions
from jace.ui.common import run_task, show_error
from jace.ui.settings_page import open_folder, total_ram_mb

LOADER_COLORS = {"vanilla": "#5b8c3a", "fabric": "#c6a875", "quilt": "#9c5bd6", "forge": "#df7a3a",
                 "neoforge": "#e0a046", "legacyfabric": "#4f8fd6"}


def instance_icon(inst: Instance, size=72) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(LOADER_COLORS.get(inst.loader, "#555")))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(0, 0, size, size, 14, 14)
    p.setPen(QColor("#ffffff"))
    f = QFont()
    f.setBold(True)
    f.setPixelSize(size // 3)
    p.setFont(f)
    initials = "".join(w[0] for w in inst.name.split()[:2]).upper() or "?"
    p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, initials)
    p.end()
    return QIcon(pm)


def sort_versions(versions: list[str]) -> list[str]:
    """Order game versions newest-first using Mojang's manifest order."""
    order = {v["id"]: i for i, v in enumerate(mojang_versions())}
    return sorted(set(versions), key=lambda v: order.get(v, 10 ** 6))


class NewInstanceDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New instance")
        self.setMinimumWidth(460)
        f = QFormLayout(self)
        self.name = QLineEdit()
        self.name.setPlaceholderText("My world")
        f.addRow("Name", self.name)
        self.loader = QComboBox()
        for lid, l in LOADERS.items():
            self.loader.addItem(l.name, lid)
        f.addRow("Mod loader", self.loader)
        self.version = QComboBox()
        f.addRow("Minecraft version", self.version)
        filt = QHBoxLayout()
        self.snapshots = QCheckBox("Snapshots")
        self.old = QCheckBox("Beta / Alpha")
        self.snapshots.setChecked(bool(settings.get("show_snapshots")))
        self.old.setChecked(bool(settings.get("show_old_versions")))
        filt.addWidget(self.snapshots)
        filt.addWidget(self.old)
        filt.addStretch()
        f.addRow("Show", filt)
        self.loader_version = QComboBox()
        f.addRow("Loader version", self.loader_version)
        self.info = QLabel("")
        self.info.setObjectName("muted")
        f.addRow(self.info)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Create")
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setObjectName("primary")
        self.buttons.accepted.connect(self._accept)
        self.buttons.rejected.connect(self.reject)
        f.addRow(self.buttons)

        self.loader.currentIndexChanged.connect(self._load_versions)
        self.snapshots.toggled.connect(self._load_versions)
        self.old.toggled.connect(self._load_versions)
        self.version.currentIndexChanged.connect(self._load_loader_versions)
        self._load_versions()

    def _lid(self):
        return self.loader.currentData()

    def _load_versions(self):
        lid = self._lid()
        self.info.setText("Loading versions...")
        self.version.clear()
        self.loader_version.clear()
        snaps, old = self.snapshots.isChecked(), self.old.isChecked()
        settings.update({"show_snapshots": snaps, "show_old_versions": old})

        def fetch():
            types = {v["id"]: v["type"] for v in mojang_versions()}
            vs = sort_versions(LOADERS[lid].game_versions(include_unstable=True))
            out = []
            for v in vs:
                t = types.get(v, "snapshot")
                if t == "snapshot" and not snaps:
                    continue
                if t in ("old_beta", "old_alpha") and not old:
                    continue
                out.append((v, t))
            return lid, out

        def done(res):
            got_lid, vs = res
            if got_lid != self._lid():
                return
            self.version.blockSignals(True)
            for v, t in vs:
                label = v if t == "release" else f"{v}  ({t.replace('old_', '')})"
                self.version.addItem(label, v)
            self.version.blockSignals(False)
            self.info.setText("" if vs else "No versions available with these filters.")
            self._load_loader_versions()
        run_task(fetch, on_done=done, on_error=lambda m: self.info.setText(f"Couldn't load versions: {m}"))

    def _load_loader_versions(self):
        lid, mc = self._lid(), self.version.currentData()
        self.loader_version.clear()
        loader = LOADERS[lid]
        self.loader_version.setEnabled(loader.needs_loader_version)
        if not loader.needs_loader_version or not mc:
            return
        self.info.setText(f"Loading {loader.name} versions...")

        def done(vs):
            if self._lid() != lid or self.version.currentData() != mc:
                return
            self.loader_version.addItems(vs)
            self.info.setText("" if vs else f"{loader.name} doesn't support {mc}.")
        run_task(loader.loader_versions, mc, on_done=done, on_error=lambda m: self.info.setText(m))

    def _accept(self):
        mc = self.version.currentData()
        if not mc:
            return
        loader = LOADERS[self._lid()]
        lver = self.loader_version.currentText()
        if loader.needs_loader_version and not lver:
            show_error(self, "Pick a loader version.")
            return
        name = self.name.text().strip() or (f"{loader.name} {mc}" if loader.id != "vanilla" else mc)
        self.result_instance = create_instance(name, mc, loader.id, lver)
        self.accept()


class ContentTab(QWidget):
    """List of mods / resource packs / shaders for one instance."""

    def __init__(self, inst: Instance, kind: str, browse_cb):
        super().__init__()
        self.inst, self.kind = inst, kind
        lay = QVBoxLayout(self)
        self.list = QListWidget()
        self.list.itemChanged.connect(self._toggled)
        lay.addWidget(self.list)
        row = QHBoxLayout()
        b = QPushButton("Browse & download")
        b.setObjectName("primary")
        b.clicked.connect(lambda: browse_cb(inst, kind))
        add = QPushButton("Add files...")
        add.clicked.connect(self._add)
        rm = QPushButton("Delete")
        rm.setObjectName("danger")
        rm.clicked.connect(self._delete)
        op = QPushButton("Open folder")
        op.clicked.connect(lambda: open_folder(inst.content_dir(kind)))
        for w in (b, add, op):
            row.addWidget(w)
        row.addStretch()
        row.addWidget(rm)
        lay.addLayout(row)
        self.refresh()

    def refresh(self):
        self.list.blockSignals(True)
        self.list.clear()
        for p in self.inst.list_content(self.kind):
            disabled = p.name.endswith(".disabled")
            it = QListWidgetItem(p.name.removesuffix(".disabled"))
            it.setData(Qt.ItemDataRole.UserRole, str(p))
            if self.kind == "mod":
                it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                it.setCheckState(Qt.CheckState.Unchecked if disabled else Qt.CheckState.Checked)
            self.list.addItem(it)
        if self.list.count() == 0:
            self.list.addItem("Nothing installed yet.")
        self.list.blockSignals(False)

    def _toggled(self, it):
        path = it.data(Qt.ItemDataRole.UserRole)
        if not path:
            return
        p = Path(path)
        enable = it.checkState() == Qt.CheckState.Checked
        target = p.with_name(p.name.removesuffix(".disabled") + ("" if enable else ".disabled"))
        if target != p:
            p.rename(target)
        self.refresh()

    def _add(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Add files")
        for f in files:
            shutil.copy2(f, self.inst.content_dir(self.kind))
        self.refresh()

    def _delete(self):
        it = self.list.currentItem()
        if not it or not it.data(Qt.ItemDataRole.UserRole):
            return
        p = Path(it.data(Qt.ItemDataRole.UserRole))
        if QMessageBox.question(self, "Delete", f"Delete {p.name}?") == QMessageBox.StandardButton.Yes:
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()
            self.refresh()


class InstanceDialog(QDialog):
    def __init__(self, inst: Instance, browse_cb, parent=None):
        super().__init__(parent)
        self.inst = inst
        self.setWindowTitle(f"Edit {inst.name}")
        self.resize(700, 520)
        lay = QVBoxLayout(self)
        head = QLabel(f"<b style='font-size:17px'>{inst.name}</b><br><span style='color:#8b919c'>{inst.describe()}</span>")
        lay.addWidget(head)
        tabs = QTabWidget()
        lay.addWidget(tabs)
        if inst.loader != "vanilla":
            tabs.addTab(ContentTab(inst, "mod", self._browse(browse_cb)), "Mods")
        tabs.addTab(ContentTab(inst, "resourcepack", self._browse(browse_cb)), "Resource packs")
        tabs.addTab(ContentTab(inst, "shader", self._browse(browse_cb)), "Shaders")

        w = QWidget()
        f = QFormLayout(w)
        self.name = QLineEdit(inst.name)
        f.addRow("Name", self.name)
        self.mem = QSpinBox()
        self.mem.setRange(0, max(1024, total_ram_mb()))
        self.mem.setSingleStep(512)
        self.mem.setSpecialValueText("Use global setting")
        self.mem.setSuffix(" MB")
        self.mem.setValue(int(inst.data.get("memory_mb") or 0))
        f.addRow("Memory", self.mem)
        self.java = QLineEdit(inst.data.get("java_path", ""))
        self.java.setPlaceholderText("Use global setting")
        f.addRow("Java executable", self.java)
        self.jvm = QLineEdit(inst.data.get("jvm_args", ""))
        self.jvm.setPlaceholderText("Use global setting")
        f.addRow("JVM arguments", self.jvm)
        repair = QPushButton("Reinstall game files")
        repair.clicked.connect(self._repair)
        f.addRow("", repair)
        save = QPushButton("Save")
        save.setObjectName("primary")
        save.clicked.connect(self._save)
        f.addRow("", save)
        tabs.addTab(w, "Settings")

    def _browse(self, cb):
        def go(inst, kind):
            self.accept()
            cb(inst, kind)
        return go

    def _save(self):
        self.inst.data.update({"name": self.name.text().strip() or self.inst.name, "memory_mb": self.mem.value(),
                               "java_path": self.java.text().strip(), "jvm_args": self.jvm.text().strip()})
        self.inst.save()
        self.accept()

    def _repair(self):
        self.inst.data.pop("version_id", None)
        self.inst.save()
        QMessageBox.information(self, "Reinstall", "Game files will be re-downloaded next time you press Play.")


class InstancesPage(QWidget):
    play_requested = Signal(object)
    browse_requested = Signal(object, str)
    selection_changed = Signal(object)
    import_requested = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("page")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        top = QHBoxLayout()
        t = QLabel("Library")
        t.setObjectName("h1")
        top.addWidget(t)
        top.addStretch()
        imp = QPushButton("Import modpack")
        imp.clicked.connect(self.import_requested.emit)
        new = QPushButton("+  New instance")
        new.setObjectName("primary")
        new.clicked.connect(self.new_instance)
        top.addWidget(imp)
        top.addWidget(new)
        lay.addLayout(top)

        self.list = QListWidget()
        self.list.setViewMode(QListWidget.ViewMode.IconMode)
        self.list.setIconSize(QSize(72, 72))
        self.list.setGridSize(QSize(150, 140))
        self.list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.list.setMovement(QListWidget.Movement.Static)
        self.list.setWordWrap(True)
        self.list.setSpacing(6)
        self.list.itemDoubleClicked.connect(lambda it: self.play_requested.emit(self.current()))
        self.list.currentItemChanged.connect(lambda *_: self.selection_changed.emit(self.current()))
        lay.addWidget(self.list, 1)
        self.empty = QLabel("No instances yet.\n\nClick  “+ New instance”  to pick a Minecraft version and mod loader,\n"
                            "or grab a modpack from the Browse tab.")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setObjectName("muted")
        self.empty.setStyleSheet("font-size:15px; background:#1a1d23; border:1px solid #262a32; border-radius:9px;")
        lay.addWidget(self.empty, 1)

        row = QHBoxLayout()
        self.edit_btn = QPushButton("Edit / Mods")
        self.edit_btn.clicked.connect(self.edit)
        self.folder_btn = QPushButton("Open folder")
        self.folder_btn.clicked.connect(lambda: self.current() and open_folder(self.current().game_dir))
        self.del_btn = QPushButton("Delete")
        self.del_btn.setObjectName("danger")
        self.del_btn.clicked.connect(self.delete)
        row.addWidget(self.edit_btn)
        row.addWidget(self.folder_btn)
        row.addStretch()
        row.addWidget(self.del_btn)
        lay.addLayout(row)
        self.refresh()

    def refresh(self, select_id=None):
        cur = self.current()
        select_id = select_id or (cur.id if cur else None)
        self.list.clear()
        self._instances = list_instances()
        for inst in self._instances:
            it = QListWidgetItem(instance_icon(inst), f"{inst.name}\n{inst.describe()}")
            it.setData(Qt.ItemDataRole.UserRole, inst.id)
            it.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
            it.setToolTip(inst.describe())
            self.list.addItem(it)
            if inst.id == select_id:
                self.list.setCurrentItem(it)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)
        self.list.setVisible(bool(self._instances))
        self.empty.setVisible(not self._instances)
        self.selection_changed.emit(self.current())

    def instances(self):
        return self._instances

    def current(self) -> Instance | None:
        it = self.list.currentItem()
        if not it:
            return None
        iid = it.data(Qt.ItemDataRole.UserRole)
        return next((i for i in self._instances if i.id == iid), None)

    def new_instance(self):
        dlg = NewInstanceDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.refresh(dlg.result_instance.id)

    def edit(self):
        inst = self.current()
        if inst:
            InstanceDialog(inst, self.browse_requested.emit, self).exec()
            self.refresh()

    def delete(self):
        inst = self.current()
        if inst and QMessageBox.question(
                self, "Delete instance", f"Delete '{inst.name}' and all its worlds, mods and settings?\n"
                "This cannot be undone.") == QMessageBox.StandardButton.Yes:
            inst.delete()
            self.refresh()
