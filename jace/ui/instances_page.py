"""Library of instances, the new-instance dialog and the instance editor."""
import shutil
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu, QMessageBox,
                               QPushButton, QSpinBox, QTabWidget, QVBoxLayout, QWidget)

from jace import content, shortcuts, sync
from jace.config import settings
from jace.instance_icons import icon_image
from jace.instances import Instance, create_instance, list_instances
from jace.loaders import LOADERS, mojang_versions
from jace.ui.common import run_task, show_error
from jace.ui.settings_page import open_folder, total_ram_mb

def instance_icon(inst: Instance, size=72) -> QIcon:
    return QIcon(QPixmap.fromImage(icon_image(inst, size * 2)))


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


class AddonsDialog(QDialog):
    """One-click server mods (LuckPerms, WorldEdit, ...) for worlds hosted with the Jace Social mod."""

    def __init__(self, inst: Instance, parent=None):
        super().__init__(parent)
        self.inst = inst
        self.setWindowTitle("Server add-ons")
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        intro = QLabel("These run on worlds you host for friends with the Jace Social mod's <b>Host world</b> button.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self.status = QLabel("")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        for addon in content.SERVER_ADDONS:
            row = QHBoxLayout()
            text = QLabel(f"<b>{addon['title']}</b><br><span style='color:#8b919c'>{addon['description']}</span>")
            text.setWordWrap(True)
            row.addWidget(text, 1)
            btn = QPushButton()
            btn.setMinimumWidth(96)
            self._set(btn, content.addon_installed(inst, addon))
            btn.clicked.connect(lambda _=False, a=addon, b=btn: self._install(a, b))
            row.addWidget(btn)
            lay.addLayout(row)
        lay.addWidget(self.status)
        close = QPushButton("Done")
        close.clicked.connect(self.accept)
        lay.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)

    @staticmethod
    def _set(btn, installed):
        btn.setText("Installed" if installed else "Install")
        btn.setObjectName("" if installed else "primary")
        btn.setEnabled(not installed)
        btn.style().polish(btn)

    def _install(self, addon, btn):
        btn.setEnabled(False)
        btn.setText("Installing…")

        def done(files):
            self._set(btn, True)
            self.status.setText(f"Installed {', '.join(files)}")

        def fail(msg):
            self._set(btn, False)
            self.status.setText(msg)
        run_task(content.install_addon, self.inst, addon, on_done=done, on_error=fail)


class ContentTab(QWidget):
    """List of mods / resource packs / shaders for one instance."""

    def __init__(self, inst: Instance, kind: str, browse_cb):
        super().__init__()
        self.inst, self.kind = inst, kind
        self.updates: dict[str, dict] = {}
        lay = QVBoxLayout(self)
        if kind == "mod":
            top = QHBoxLayout()
            self.mod_status = QLabel("")
            self.mod_status.setObjectName("muted")
            self.mod_status.setWordWrap(True)
            top.addWidget(self.mod_status, 1)
            self.check_btn = QPushButton("Check for updates")
            self.check_btn.clicked.connect(self.check_updates)
            self.update_all_btn = QPushButton("Update all")
            self.update_all_btn.setObjectName("primary")
            self.update_all_btn.clicked.connect(self.update_all)
            self.update_all_btn.hide()
            top.addWidget(self.check_btn)
            top.addWidget(self.update_all_btn)
            lay.addLayout(top)
        self.list = QListWidget()
        self.list.itemChanged.connect(self._toggled)
        lay.addWidget(self.list)
        row = QHBoxLayout()
        b = QPushButton("Browse && download")
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
        if kind == "mod" and inst.loader in ("fabric", "quilt", "forge", "neoforge"):
            addons = QPushButton("Server add-ons...")
            addons.setToolTip("LuckPerms, WorldEdit and more for worlds you host for friends")
            addons.clicked.connect(lambda: (AddonsDialog(inst, self).exec(), self.refresh()))
            row.addWidget(addons)
        row.addStretch()
        row.addWidget(rm)
        lay.addLayout(row)
        self.refresh()

    def refresh(self):
        self.list.blockSignals(True)
        self.list.clear()
        for p in self.inst.list_content(self.kind):
            disabled = p.name.endswith(".disabled")
            name = p.name.removesuffix(".disabled")
            upd = self.updates.get(name)
            it = QListWidgetItem(name + (f"     ⬆ update: {upd['latest']['version_number']}" if upd else ""))
            if upd:
                it.setForeground(QColor("#3ddc84"))
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
        if files and self.kind == "mod":
            self.fix_dependencies()          # hand-added mods get their dependencies too

    # -- mod updates & dependencies
    def _busy(self, on: bool, text=""):
        self.check_btn.setEnabled(not on)
        self.update_all_btn.setEnabled(not on)
        if text:
            self.mod_status.setText(text)

    def fix_dependencies(self):
        self._busy(True, "Checking dependencies…")

        def done(files):
            self._busy(False, f"Installed missing dependencies: {', '.join(files)}" if files
                       else "All dependencies are installed.")
            self.refresh()

        def fail(msg):
            self._busy(False, f"Couldn't check dependencies: {msg}")
        run_task(content.install_missing_dependencies, self.inst, on_done=done, on_error=fail)

    def check_updates(self):
        self._busy(True, "Checking for updates and missing dependencies…")

        def work():
            info = content.identify_mods(self.inst)
            deps = content.install_missing_dependencies(self.inst)
            return content.check_mod_updates(self.inst), deps, info

        def done(res):
            updates, deps, info = res
            self.updates = {u["filename"]: u for u in updates}
            unknown = sum(1 for i in info.values() if not i["source"])
            parts = [f"{len(updates)} update(s) available." if updates else "All mods are up to date."]
            if deps:
                parts.append(f"Installed missing dependencies: {', '.join(deps)}.")
            if unknown:
                parts.append(f"{unknown} mod(s) aren't on Modrinth or Jace Store, so they can't be checked.")
            self._busy(False, " ".join(parts))
            self.update_all_btn.setText(f"Update all ({len(updates)})")
            self.update_all_btn.setVisible(bool(updates))
            self.refresh()

        def fail(msg):
            self._busy(False, f"Couldn't check for updates: {msg}")
        run_task(work, on_done=done, on_error=fail)

    def update_all(self):
        updates = list(self.updates.values())
        if not updates:
            return
        self._busy(True, f"Updating {len(updates)} mod(s)…")

        def done(files):
            self.updates = {}
            self.update_all_btn.hide()
            self._busy(False, f"Updated: {', '.join(files)}")
            self.refresh()

        def fail(msg):
            self._busy(False, f"Update failed: {msg}")
            self.refresh()
        run_task(content.update_mods, self.inst, updates, on_done=done, on_error=fail)

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


class SyncTab(QWidget):
    """Choose which folders this instance shares with other instances."""

    def __init__(self, inst: Instance):
        super().__init__()
        self.inst = inst
        lay = QVBoxLayout(self)
        intro = QLabel("Synced folders are shared with every instance that syncs them - add a resource pack "
                       "once and it's everywhere. Change where they're stored (e.g. a Dropbox folder, to sync "
                       "between computers) in Settings → Synced folders.")
        intro.setWordWrap(True)
        intro.setObjectName("muted")
        lay.addWidget(intro)
        self.boxes = {}
        for folder, label in sync.FOLDERS.items():
            cb = QCheckBox(label)
            cb.setChecked(sync.is_synced(inst, folder))
            cb.toggled.connect(lambda on, f=folder, c=cb: self._toggle(f, on, c))
            self.boxes[folder] = cb
            lay.addWidget(cb)
        warn = QLabel("⚠ Worlds: opening a world in an older Minecraft version than it was last played in can "
                      "damage it. Only sync worlds between instances of the same version.")
        warn.setWordWrap(True)
        warn.setStyleSheet("color:#e0b44a;")
        lay.addWidget(warn)
        self.where = QLabel()
        self.where.setObjectName("muted")
        self.where.setWordWrap(True)
        lay.addWidget(self.where)
        lay.addStretch()
        self._update_where()

    def _update_where(self):
        self.where.setText(f"Shared folder: {sync.shared_root()}")

    def _toggle(self, folder, on, cb):
        label = sync.FOLDERS[folder].lower()
        try:
            if on:
                local = self.inst.game_dir / folder
                n = len(list(local.iterdir())) if local.is_dir() and not sync.is_synced(self.inst, folder) else 0
                if n and QMessageBox.question(
                        self, "Sync folder", f"This instance has {n} item(s) in {label}. They'll be moved into the "
                        "shared folder so all synced instances can use them (nothing is overwritten - "
                        "clashing names get the instance name added).\n\nContinue?") != QMessageBox.StandardButton.Yes:
                    cb.blockSignals(True)
                    cb.setChecked(False)
                    cb.blockSignals(False)
                    return
                sync.enable(self.inst, folder)
            else:
                n = sync.disable(self.inst, folder)
                if n:
                    QMessageBox.information(self, "Stopped syncing", f"This instance kept its own copy of the "
                                            f"{n} shared item(s) in {label}.")
        except OSError as e:
            show_error(self, str(e), "Couldn't change syncing")
            cb.blockSignals(True)
            cb.setChecked(sync.is_synced(self.inst, folder))
            cb.blockSignals(False)


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

        icon_row = QHBoxLayout()
        self.icon_preview = QLabel()
        self.icon_preview.setFixedSize(64, 64)
        icon_row.addWidget(self.icon_preview)
        for label, slot in (("Choose image…", self._choose_icon), ("Icon builder…", self._build_icon),
                            ("Reset", self._reset_icon)):
            b = QPushButton(label)
            b.clicked.connect(slot)
            icon_row.addWidget(b)
        icon_row.addStretch()
        f.addRow("Icon", icon_row)
        self._update_icon_preview()

        size_row = QHBoxLayout()
        self.win_w = QSpinBox()
        self.win_w.setRange(0, 7680)
        self.win_w.setSpecialValueText("Global")
        self.win_w.setValue(int(inst.data.get("window_width") or 0))
        self.win_h = QSpinBox()
        self.win_h.setRange(0, 4320)
        self.win_h.setSpecialValueText("Global")
        self.win_h.setValue(int(inst.data.get("window_height") or 0))
        size_row.addWidget(self.win_w)
        size_row.addWidget(QLabel("×"))
        size_row.addWidget(self.win_h)
        for label, (ww, hh) in (("720p", (1280, 720)), ("1080p", (1920, 1080)), ("Global", (0, 0))):
            b = QPushButton(label)
            b.clicked.connect(lambda _=False, ww=ww, hh=hh: (self.win_w.setValue(ww), self.win_h.setValue(hh)))
            size_row.addWidget(b)
        size_row.addStretch()
        f.addRow("Window size", size_row)
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
        sc_row = QHBoxLayout()
        sc = QPushButton("Create shortcut")
        sc.setToolTip(f"Desktop and {shortcuts.menu_name()} shortcut that starts this instance in one click")
        sc.clicked.connect(self._make_shortcut)
        sc_row.addWidget(sc)
        self.rm_sc = QPushButton("Remove shortcut")
        self.rm_sc.clicked.connect(self._remove_shortcut)
        self.rm_sc.setEnabled(shortcuts.has_shortcuts(inst))
        sc_row.addWidget(self.rm_sc)
        sc_row.addStretch()
        f.addRow("Shortcut", sc_row)
        repair = QPushButton("Reinstall game files")
        repair.clicked.connect(self._repair)
        f.addRow("", repair)
        save = QPushButton("Save")
        save.setObjectName("primary")
        save.clicked.connect(self._save)
        f.addRow("", save)
        tabs.addTab(SyncTab(inst), "Sync")
        tabs.addTab(w, "Settings")

    def _browse(self, cb):
        def go(inst, kind):
            self.accept()
            cb(inst, kind)
        return go

    def _save(self):
        self.inst.data.update({"name": self.name.text().strip() or self.inst.name, "memory_mb": self.mem.value(),
                               "java_path": self.java.text().strip(), "jvm_args": self.jvm.text().strip(),
                               "window_width": self.win_w.value(), "window_height": self.win_h.value()})
        self.inst.save()
        if shortcuts.has_shortcuts(self.inst):     # keep shortcut name/icon in sync
            shortcuts.remove(self.inst)
            shortcuts.create(self.inst)
        self.accept()

    # -- icon
    def _update_icon_preview(self):
        self.icon_preview.setPixmap(QPixmap.fromImage(icon_image(self.inst, 64)))

    def _set_icon(self, img: QImage):
        img.scaled(256, 256, Qt.AspectRatioMode.KeepAspectRatio,
                   Qt.TransformationMode.SmoothTransformation).save(str(self.inst.icon_path), "PNG")
        self._update_icon_preview()

    def _choose_icon(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose an icon", "", "Images (*.png *.jpg *.jpeg *.webp *.bmp *.gif)")
        if path:
            img = QImage(path)
            if img.isNull():
                show_error(self, "That image couldn't be opened.")
                return
            side = min(img.width(), img.height())   # center-crop to a square
            self._set_icon(img.copy((img.width() - side) // 2, (img.height() - side) // 2, side, side))

    def _build_icon(self):
        from jace.ui.icon_builder import IconBuilderDialog
        dlg = IconBuilderDialog("".join(w[0] for w in self.inst.name.split()[:2]), self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._set_icon(dlg.result_image())

    def _reset_icon(self):
        self.inst.icon_path.unlink(missing_ok=True)
        self._update_icon_preview()

    # -- shortcuts
    def _make_shortcut(self):
        try:
            made = shortcuts.create(self.inst)
        except Exception as e:  # noqa: BLE001
            show_error(self, str(e), "Couldn't create shortcut")
            return
        self.rm_sc.setEnabled(True)
        QMessageBox.information(self, "Shortcut created",
                                f"Double-click “{self.inst.name}” on your desktop or in the {shortcuts.menu_name()} "
                                "to start it straight away.\n\n" + "\n".join(str(p) for p in made))

    def _remove_shortcut(self):
        shortcuts.remove(self.inst)
        self.inst.save()
        self.rm_sc.setEnabled(False)

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
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._context_menu)
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

    def _context_menu(self, pos):
        if not self.list.itemAt(pos):
            return
        inst = self.current()
        menu = QMenu(self)
        menu.addAction("Play", lambda: self.play_requested.emit(inst))
        menu.addAction("Edit / Mods", self.edit)
        menu.addAction(f"Create desktop && {shortcuts.menu_name()} shortcut", lambda: self._quick_shortcut(inst))
        menu.addAction("Open folder", lambda: open_folder(inst.game_dir))
        menu.addSeparator()
        menu.addAction("Delete", self.delete)
        menu.exec(self.list.viewport().mapToGlobal(pos))

    def _quick_shortcut(self, inst):
        try:
            shortcuts.create(inst)
        except Exception as e:  # noqa: BLE001
            show_error(self, str(e), "Couldn't create shortcut")
            return
        QMessageBox.information(self, "Shortcut created", f"“{inst.name}” is on your desktop and in the "
                                f"{shortcuts.menu_name()}. Double-click it to play straight away.")

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
