"""Main window: sidebar navigation, pages, and the play bar."""
import sys
import threading

from PySide6.QtCore import Signal
from PySide6.QtGui import QFont, QIcon, QTextCursor
from PySide6.QtWidgets import (QApplication, QButtonGroup, QDialog, QFileDialog, QHBoxLayout, QInputDialog, QLabel,
                               QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QStackedWidget,
                               QVBoxLayout, QWidget)

from jace import APP_NAME, APP_VERSION, desktop
from jace.accounts import accounts
from jace.config import settings
from jace.content import import_modpack_file
from jace.ui.accounts_page import AccountsPage
from jace.ui.browse_page import BrowsePage
from jace.ui.common import STYLE, run_task, show_error
from jace.ui.installer import FirstRunDialog, SetupWizard, confirm_uninstall
from jace.ui.instances_page import InstancesPage
from jace.ui.settings_page import SettingsPage
from jace.ui.skins_page import SkinsPage


class GameConsole(QDialog):
    line = Signal(str)
    exited = Signal(int)

    def __init__(self, title, proc, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Game log - {title}")
        self.resize(820, 480)
        self.proc = proc
        lay = QVBoxLayout(self)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setMaximumBlockCount(5000)
        f = QFont("monospace")
        f.setStyleHint(QFont.StyleHint.Monospace)
        self.text.setFont(f)
        lay.addWidget(self.text)
        row = QHBoxLayout()
        self.state = QLabel("Running")
        self.state.setObjectName("muted")
        kill = QPushButton("Force stop")
        kill.setObjectName("danger")
        kill.clicked.connect(lambda: self.proc.poll() is None and self.proc.kill())
        row.addWidget(self.state)
        row.addStretch()
        row.addWidget(kill)
        lay.addLayout(row)
        self.line.connect(self._append)
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self):
        for ln in self.proc.stdout:
            self.line.emit(ln.rstrip("\n"))
        self.exited.emit(self.proc.wait())

    def _append(self, s):
        self.text.appendPlainText(s)
        self.text.moveCursor(QTextCursor.MoveOperation.End)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME}")
        self.resize(1180, 760)
        self.busy = 0
        self.consoles = []

        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        main = QHBoxLayout()
        main.setSpacing(0)
        outer.addLayout(main, 1)

        # sidebar
        side = QWidget()
        side.setObjectName("sidebar")
        side.setFixedWidth(210)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 0, 0, 12)
        brand = QLabel("⛏ Jace Launcher")
        brand.setObjectName("brand")
        sl.addWidget(brand)
        self.stack = QStackedWidget()
        self.nav = QButtonGroup(self)

        self.library = InstancesPage()
        self.browse = BrowsePage(self)
        self.skins = SkinsPage(self)
        self.accounts_page = AccountsPage()
        self.settings_page = SettingsPage()
        for i, (label, page) in enumerate((("🎮  Library", self.library), ("🧩  Browse", self.browse),
                                           ("👕  Skins && Capes", self.skins), ("👤  Accounts", self.accounts_page),
                                           ("⚙  Settings", self.settings_page))):
            b = QPushButton(label)
            b.setObjectName("nav")
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, i=i: self.stack.setCurrentIndex(i))
            self.nav.addButton(b, i)
            sl.addWidget(b)
            self.stack.addWidget(page)
        self.nav.button(0).setChecked(True)
        sl.addStretch()
        ver = QLabel(f"v{APP_VERSION}")
        ver.setObjectName("muted")
        ver.setContentsMargins(18, 0, 0, 0)
        sl.addWidget(ver)
        main.addWidget(side)
        main.addWidget(self.stack, 1)

        # bottom play bar
        bar = QWidget()
        bar.setObjectName("bottombar")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(18, 12, 18, 12)
        self.account_btn = QPushButton()
        self.account_btn.clicked.connect(lambda: self.go(3))
        bl.addWidget(self.account_btn)
        info = QVBoxLayout()
        self.status = QLabel("Ready")
        self.status.setObjectName("muted")
        self.progress = QProgressBar()
        self.progress.setFixedHeight(8)
        self.progress.setTextVisible(False)
        self.progress.hide()
        info.addWidget(self.status)
        info.addWidget(self.progress)
        bl.addLayout(info, 1)
        self.selected_label = QLabel("")
        bl.addWidget(self.selected_label)
        self.play_btn = QPushButton("PLAY")
        self.play_btn.setObjectName("play")
        self.play_btn.clicked.connect(lambda: self.play(self.library.current()))
        bl.addWidget(self.play_btn)
        outer.addWidget(bar)

        # wiring
        self.library.play_requested.connect(self.play)
        self.library.selection_changed.connect(self._selection_changed)
        self.library.browse_requested.connect(self._browse_for)
        self.library.import_requested.connect(self.import_modpack)
        self.browse.instance_created.connect(self._instance_created)
        self.accounts_page.changed.connect(self._account_changed)
        self._account_changed()
        self._selection_changed(self.library.current())

    def go(self, index):
        self.nav.button(index).setChecked(True)
        self.stack.setCurrentIndex(index)

    # -- shared job runner used by every page
    def notify(self, text):
        self.status.setText(text)

    def run_job(self, fn, label, on_done=None, use_callback=False, *args, **kwargs):
        self.busy += 1
        self.status.setText(label + "…")
        self.progress.setRange(0, 0)
        self.progress.show()
        self.play_btn.setEnabled(False)

        def finish():
            self.busy -= 1
            if self.busy == 0:
                self.progress.hide()
                self.play_btn.setEnabled(self.library.current() is not None)

        def done(res):
            finish()
            self.status.setText("Done")
            if on_done:
                on_done(res)

        def fail(msg):
            finish()
            self.status.setText("Failed")
            show_error(self, msg, f"{label} failed")

        def prog(v, m):
            if m > 0:
                self.progress.setRange(0, m)
                self.progress.setValue(min(v, m))

        run_task(fn, *args, on_done=done, on_error=fail, on_status=self.status.setText,
                 on_progress=prog, use_callback=use_callback, **kwargs)

    # -- state
    def _account_changed(self):
        a = accounts.current()
        self.account_btn.setText(f"👤  {a['username']}" if a else "👤  Add account")
        self.browse.refresh_instances()

    def _selection_changed(self, inst):
        self.selected_label.setText(f"<b>{inst.name}</b><br><span style='color:#8b919c'>{inst.describe()}</span>"
                                    if inst else "")
        self.play_btn.setEnabled(inst is not None and self.busy == 0)

    def _browse_for(self, inst, kind):
        self.go(1)
        self.browse.open_for(inst, kind)

    def _instance_created(self, inst):
        self.library.refresh(inst.id)
        self.go(0)
        self.notify(f"Installed {inst.name} - press Play!")

    def import_modpack(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import modpack", "",
                                              "Modpacks (*.mrpack *.zip);;All files (*)")
        if not path:
            return
        name, ok = QInputDialog.getText(self, "Instance name", "Name for the new instance (blank = pack name):")
        if not ok:
            return

        def done(res):
            inst, manual = res
            self.browse.refresh_instances()
            self._instance_created(inst)
            if manual:
                QMessageBox.warning(self, "Some files need manual download",
                                    "Download these and put them in the instance's mods folder:\n\n" + "\n".join(manual))
        self.run_job(import_modpack_file, "Importing modpack", done, True, path, name=name.strip() or None)

    # -- launching
    def play(self, inst):
        if inst is None or self.busy:
            return
        acc = accounts.current()
        if not acc:
            QMessageBox.information(self, "No account", "Add a Microsoft or offline account first.")
            self.go(3)
            return

        def prepare(callback):
            account = accounts.ensure_fresh(acc)
            inst.install(callback)
            callback["setStatus"]("Starting Minecraft…")
            return inst.launch(account)

        def started(proc):
            self.notify(f"Playing {inst.name}")
            self.library.refresh(inst.id)
            con = GameConsole(inst.name, proc, self)
            self.consoles.append(con)
            con.exited.connect(lambda code: self._game_exited(con, inst, code))
            if settings.get("close_on_launch"):
                self.hide()
            else:
                con.show()
        self.run_job(prepare, f"Preparing {inst.name}", started, True)

    def _game_exited(self, con, inst, code):
        con.state.setText(f"Exited with code {code}")
        if self.isHidden():
            self.show()
        self.notify(f"{inst.name} closed" + (f" (exit code {code})" if code else ""))
        if code not in (0, None):
            con.show()
            con.raise_()


def should_run_setup(argv) -> bool:
    if "--install" in argv:
        return True
    return bool(desktop.running_appimage() and not desktop.running_installed_copy()
                and not settings.get("skip_install_prompt"))


def main():
    if desktop.handle_cli(sys.argv[1:]):
        return
    QApplication.setApplicationName(APP_NAME)
    QApplication.setDesktopFileName(desktop.APP_ID)
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    app.setWindowIcon(QIcon(str(desktop.ICON_SRC)))
    argv = sys.argv[1:]
    if "--uninstall-gui" in argv:
        confirm_uninstall()
        return
    if should_run_setup(argv):
        wiz = SetupWizard()
        finished = wiz.exec() == QDialog.DialogCode.Accepted
        if "--install" in argv and not (finished and wiz.launch_after()):
            return
        settings.set("welcomed", True)
        if finished and not wiz.launch_after():
            return
    elif not settings.get("welcomed"):
        settings.set("welcomed", True)
        if not accounts.accounts:
            FirstRunDialog().exec()
    w = MainWindow()
    w.show()
    sys.exit(app.exec())
