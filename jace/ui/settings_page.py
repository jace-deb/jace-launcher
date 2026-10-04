"""Global launcher settings."""
import os
import subprocess
import sys

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QScrollArea, QSizePolicy, QSpinBox, QVBoxLayout, QWidget)

from jace import desktop
from jace.config import DATA_DIR, settings
from jace.ui.common import run_task


def total_ram_mb() -> int:
    if sys.platform == "win32":
        import ctypes

        class MemStatus(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        st = MemStatus()
        st.dwLength = ctypes.sizeof(st)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
            return st.ullTotalPhys // (1024 * 1024)
        return 16384
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") // (1024 * 1024)
    except (ValueError, OSError, AttributeError):
        return 16384


def open_folder(path):
    path = str(path)
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


class SettingsPage(QWidget):
    check_updates_requested = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("page")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        title = QLabel("Settings")
        title.setObjectName("h1")
        outer.addWidget(title)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("page")
        lay = QVBoxLayout(body)
        scroll.setWidget(body)
        outer.addWidget(scroll)

        # --- Java & memory
        g = QGroupBox("Java && memory")
        f = QFormLayout(g)
        self.mem = QSpinBox()
        self.mem.setRange(512, max(1024, total_ram_mb()))
        self.mem.setSingleStep(512)
        self.mem.setSuffix(" MB")
        self.mem.setValue(int(settings.get("memory_mb")))
        f.addRow("Maximum memory", self.mem)
        f.addRow("", self._muted(f"Your computer has about {total_ram_mb() // 1024} GB of RAM."))

        jrow = QHBoxLayout()
        self.java = QComboBox()
        self.java.setEditable(True)
        self.java.addItem("")
        self.java.setCurrentText(settings.get("java_path"))
        self.java.lineEdit().setPlaceholderText("Automatic (Mojang's Java runtime per version - recommended)")
        browse = QPushButton("Browse")
        browse.clicked.connect(self._browse_java)
        detect = QPushButton("Detect")
        detect.clicked.connect(self._detect_java)
        jrow.addWidget(self.java, 1)
        jrow.addWidget(browse)
        jrow.addWidget(detect)
        f.addRow("Java executable", jrow)
        self.jvm = QLineEdit(settings.get("jvm_args"))
        self.jvm.setPlaceholderText("-XX:+UseG1GC ...")
        f.addRow("Extra JVM arguments", self.jvm)
        lay.addWidget(g)

        # --- Game window
        g = QGroupBox("Game")
        f = QFormLayout(g)
        res = QHBoxLayout()
        self.w = QSpinBox()
        self.w.setRange(320, 7680)
        self.w.setValue(int(settings.get("window_width")))
        self.h = QSpinBox()
        self.h.setRange(240, 4320)
        self.h.setValue(int(settings.get("window_height")))
        res.addWidget(self.w)
        res.addWidget(QLabel("×"))
        res.addWidget(self.h)
        res.addStretch()
        f.addRow("Window size", res)
        self.close_on_launch = QCheckBox("Hide the launcher while the game runs")
        self.close_on_launch.setChecked(bool(settings.get("close_on_launch")))
        f.addRow("", self.close_on_launch)
        lay.addWidget(g)

        # --- APIs
        g = QGroupBox("Integrations")
        f = QFormLayout(g)
        self.cf_key = QLineEdit(settings.get("curseforge_api_key"))
        self.cf_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.cf_key.setPlaceholderText("Paste your CurseForge API key")
        f.addRow("CurseForge API key", self.cf_key)
        f.addRow("", self._muted("Modrinth works out of the box. CurseForge requires a free key from "
                                 "console.curseforge.com."))
        self.azure = QLineEdit(settings.get("azure_client_id"))
        self.azure.setPlaceholderText("Optional - leave empty to use the default sign-in")
        f.addRow("Azure client ID", self.azure)
        f.addRow("", self._muted("Only needed if you registered your own Azure app for Microsoft login."))
        lay.addWidget(g)

        # --- Updates
        g = QGroupBox("Updates")
        f = QHBoxLayout(g)
        from jace import updater
        why = updater.unsupported_reason()
        f.addWidget(self._muted(f"You have Jace Launcher {updater.current_version()}." + (f"  {why}" if why else "")), 1)
        auto = QCheckBox("Check on startup")
        auto.setChecked(settings.get("auto_update_check") is not False)
        auto.toggled.connect(lambda on: settings.set("auto_update_check", on))
        auto.setEnabled(why is None)
        f.addWidget(auto)
        cb = QPushButton("Check for updates")
        cb.clicked.connect(self.check_updates_requested.emit)
        f.addWidget(cb)
        lay.addWidget(g)

        # --- Storage
        g = QGroupBox("Storage")
        f = QHBoxLayout(g)
        f.addWidget(self._path_label(str(DATA_DIR)), 1)
        ob = QPushButton("Open folder")
        ob.clicked.connect(lambda: open_folder(DATA_DIR))
        f.addWidget(ob)
        lay.addWidget(g)

        # --- Desktop integration (only meaningful when running as an AppImage)
        if desktop.setup_available() or desktop.is_installed():
            g = QGroupBox("Desktop integration")
            f = QHBoxLayout(g)
            self.integ = self._path_label("")
            f.addWidget(self.integ, 1)
            if desktop.setup_available():
                ib = QPushButton("Run setup…")
                ib.clicked.connect(self._install_app)
                f.addWidget(ib)
            self._update_integ()
            lay.addWidget(g)

        save = QPushButton("Save settings")
        save.setObjectName("primary")
        save.clicked.connect(self.save)
        self.saved = self._muted("")
        row = QHBoxLayout()
        row.addWidget(self.saved)
        row.addStretch()
        row.addWidget(save)
        lay.addLayout(row)

        # --- Delete the app (always available)
        g = QGroupBox("Delete Jace Launcher")
        f = QHBoxLayout(g)
        f.addWidget(self._muted("Remove Jace Launcher from this computer. You'll be asked whether to keep "
                                "your worlds and accounts."), 1)
        db = QPushButton("Delete Jace Launcher…")
        db.setObjectName("danger")
        db.clicked.connect(self._uninstall_app)
        f.addWidget(db)
        lay.addWidget(g)
        lay.addStretch()

    def _path_label(self, text):
        """A label for long paths that shrinks (clipping) instead of widening the page."""
        lab = QLabel(text)
        lab.setToolTip(text)
        lab.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        return lab

    def _muted(self, text):
        lab = QLabel(text)
        lab.setObjectName("muted")
        lab.setWordWrap(True)
        return lab

    def _update_integ(self):
        p = desktop.installed_path()
        self.integ.setText(f"Installed at {p}" if p else "Not installed yet.")
        self.integ.setToolTip(str(p or ""))

    def _install_app(self):
        from jace.ui.installer import SetupWizard
        SetupWizard(self).exec()
        self._update_integ()

    def _uninstall_app(self):
        from jace.ui.installer import confirm_uninstall
        if confirm_uninstall(self):
            self._update_integ()

    def _browse_java(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose java executable")
        if path:
            self.java.setCurrentText(path)

    def _detect_java(self):
        import minecraft_launcher_lib as mll

        def done(infos):
            self.java.clear()
            self.java.addItem("")
            for i in infos:
                self.java.addItem(i["java_path"])
            self.saved.setText(f"Found {len(infos)} Java installation(s)." if infos else "No system Java found - "
                               "that's fine, the launcher downloads the right Java automatically.")
        run_task(mll.java_utils.find_system_java_versions_information, on_done=done)

    def save(self):
        settings.update({
            "memory_mb": self.mem.value(), "java_path": self.java.currentText().strip(),
            "jvm_args": self.jvm.text().strip(), "window_width": self.w.value(), "window_height": self.h.value(),
            "close_on_launch": self.close_on_launch.isChecked(),
            "curseforge_api_key": self.cf_key.text().strip(), "azure_client_id": self.azure.text().strip(),
        })
        self.saved.setText("Saved ✓")
