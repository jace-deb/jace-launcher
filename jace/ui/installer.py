"""Setup wizard shown the first time the AppImage runs (or with --install)."""
import shutil
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPlainTextEdit, QPushButton, QVBoxLayout, QWizard, QWizardPage)

from jace import APP_VERSION, desktop
from jace.accounts import accounts
from jace.config import settings
from jace.ui.accounts_page import AccountsPage
from jace.ui.common import run_task


IS_MAC = sys.platform == "darwin"


def _muted(text):
    lab = QLabel(text)
    lab.setObjectName("muted")
    lab.setWordWrap(True)
    return lab


class WelcomePage(QWizardPage):
    def __init__(self, upgrade: bool):
        super().__init__()
        self.setTitle("Update Jace Launcher" if upgrade else "Welcome to Jace Launcher")
        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(QPixmap(str(desktop.ICON_SRC)).scaled(
            96, 96, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        row.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        text = QLabel(
            f"<p style='font-size:15px'>This will set up <b>Jace Launcher {APP_VERSION}</b> on your computer.</p>"
            "<p>The next steps will:</p>"
            "<ul><li>sign in to your Minecraft accounts</li>"
            "<li>choose where to install Jace Launcher</li>"
            + ("<li>add it to the Dock, Launchpad and your desktop</li>"
               "<li>stop macOS from warning that the app is \"damaged\"</li></ul>" if IS_MAC else
               "<li>add it to your applications menu and desktop</li>"
               "<li>register it with GNOME Software and other app centers</li></ul>")
            + ("<p>A version is already installed; it will be replaced. Your instances, worlds and accounts "
               "are kept.</p>" if upgrade else ""))
        text.setWordWrap(True)
        row.addWidget(text, 1)
        lay.addLayout(row)
        lay.addStretch()
        self.never = QCheckBox("Don't show this setup again (just run the launcher)")
        lay.addWidget(self.never)


class AccountsStepPage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("Add your accounts")
        self.setSubTitle("Sign in with Microsoft to play online and use the skin & cape changer, or add an "
                         "offline account. You can skip this and add accounts later.")
        lay = QVBoxLayout(self)
        self.page = AccountsPage()
        self.page.layout().setContentsMargins(0, 0, 0, 0)
        # the wizard already shows a title; hide the page's own heading and blurb
        for i in range(2):
            self.page.layout().itemAt(i).widget().hide()
        lay.addWidget(self.page)


class LocationPage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("Choose install location and shortcuts")
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Install Jace Launcher to:"))
        row = QHBoxLayout()
        current = desktop.installed_path()
        self.path = QLineEdit(str(current.parent if current else desktop.default_install_dir()))
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        row.addWidget(self.path, 1)
        row.addWidget(browse)
        lay.addLayout(row)
        self.space = _muted("")
        lay.addWidget(self.space)
        self.path.textChanged.connect(self._update_space)
        self._update_space()
        lay.addSpacing(12)

        self.options = {}
        for key, label, default in desktop.install_options():
            cb = QCheckBox(label)
            cb.setChecked(default)
            self.options[key] = cb
            lay.addWidget(cb)
        if IS_MAC:
            lay.addWidget(_muted(
                "Mac apps normally live in Applications. macOS may ask permission to let Jace Launcher update "
                "the Dock or your Desktop - click OK."))
        else:
            lay.addWidget(_muted(
                "App centers list apps using AppStream info; this adds Jace Launcher's description, icon and "
                "keywords so app centers that read local metadata can recognise it."))
        lay.addStretch()

    def chosen_options(self) -> dict:
        return {k: cb.isChecked() for k, cb in self.options.items()}

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Install location", self.path.text())
        if d:
            self.path.setText(d)

    def _update_space(self):
        p = Path(self.path.text()).expanduser()
        while not p.exists() and p != p.parent:
            p = p.parent
        try:
            free = shutil.disk_usage(p).free / 1024 ** 3
            self.space.setText(f"{free:.1f} GB free there. The launcher needs about 0.3 GB; games and mods are "
                               "stored separately in ~/.jacelauncher.")
        except OSError:
            self.space.setText("")

    def validatePage(self):
        if not self.path.text().strip():
            QMessageBox.warning(self, "Choose a folder", "Pick a folder to install Jace Launcher into.")
            return False
        p = Path(self.path.text()).expanduser()
        try:
            p.mkdir(parents=True, exist_ok=True)
            probe = p / ".jace-write-test"
            probe.write_text("")
            probe.unlink()
        except OSError as e:
            QMessageBox.warning(self, "Can't install there", f"That folder isn't writable:\n{e}")
            return False
        return True


class InstallPage(QWizardPage):
    def __init__(self, loc: LocationPage):
        super().__init__()
        self.loc = loc
        self.setTitle("Installing")
        lay = QVBoxLayout(self)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        lay.addWidget(self.log)
        self.finished_ok = False
        self.result_path = None

    def initializePage(self):
        self.finished_ok = False
        self.log.clear()
        self.wizard().button(QWizard.WizardButton.BackButton).setEnabled(False)
        loc = self.loc

        def work(callback):
            return desktop.install_app(Path(loc.path.text()).expanduser(), loc.chosen_options(),
                                       status=callback["setStatus"])

        def done(path):
            self.result_path = path
            self.finished_ok = True
            self.log.appendPlainText(f"\nJace Launcher is installed at {path}")
            self.completeChanged.emit()
            self.wizard().next()

        def fail(msg):
            self.log.appendPlainText(f"\nInstall failed: {msg}")
            self.wizard().button(QWizard.WizardButton.BackButton).setEnabled(True)
        run_task(work, use_callback=True, on_done=done, on_error=fail, on_status=self.log.appendPlainText)

    def isComplete(self):
        return self.finished_ok


class FinishPage(QWizardPage):
    def __init__(self, install: InstallPage):
        super().__init__()
        self.install = install
        self.setTitle("All set!")
        lay = QVBoxLayout(self)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        lay.addWidget(self.summary)
        lay.addStretch()
        self.launch = QCheckBox("Start Jace Launcher now")
        self.launch.setChecked(True)
        lay.addWidget(self.launch)

    def initializePage(self):
        parts = desktop.install_record().get("parts", [])
        lines = [f"Installed to <b>{self.install.result_path}</b>"]
        lines += [f"✓ {desktop.PART_DESCRIPTIONS[p]}" for p in parts if p in desktop.PART_DESCRIPTIONS]
        if "desktop" in parts and not IS_MAC:
            lines.append("(on GNOME you may need the Desktop Icons extension to see desktop shortcuts)")
        a = accounts.current()
        lines.append(f"✓ Signed in as <b>{a['username']}</b>" if a else "No account yet. Add one from the Accounts tab.")
        if IS_MAC:
            lines.append("<br>You can eject the Jace Launcher disk image now. To uninstall later, use "
                         "Settings → Delete Jace Launcher.")
        else:
            lines.append("<br>To uninstall later, right-click Jace Launcher in the applications menu → "
                         "<i>Uninstall Jace Launcher</i>, or use Settings → Delete Jace Launcher.")
        self.summary.setText("<br>".join(lines))


class SetupWizard(QWizard):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Jace Launcher Setup")
        self.setWizardStyle(QWizard.WizardStyle.ClassicStyle)
        self.setStyleSheet("QWizard, QWizardPage { background: #16181d; }"
                           "QWizard QLabel#qt_wizard_title { font-size: 19px; font-weight: 700; }")
        self.setOption(QWizard.WizardOption.NoBackButtonOnLastPage)
        self.resize(720, 560)
        self.welcome = WelcomePage(desktop.is_installed())
        self.accounts_page = AccountsStepPage()
        self.loc = LocationPage()
        self.install_page = InstallPage(self.loc)
        self.finish = FinishPage(self.install_page)
        for p in (self.welcome, self.accounts_page, self.loc, self.install_page, self.finish):
            self.addPage(p)
        self.setButtonText(QWizard.WizardButton.CommitButton, "Install")
        self.loc.setCommitPage(True)

    def reject(self):
        if self.welcome.never.isChecked():
            settings.set("skip_install_prompt", True)
        super().reject()

    def launch_after(self) -> bool:
        return self.finish.launch.isChecked()


class FirstRunDialog(QDialog):
    """Welcome + add-your-accounts step for builds without the AppImage wizard
    (Windows and macOS, whose own installers handle location and shortcuts)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Welcome to Jace Launcher")
        self.resize(680, 520)
        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(QPixmap(str(desktop.ICON_SRC)).scaled(
            64, 64, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        row.addWidget(icon)
        row.addWidget(QLabel("<p style='font-size:17px'><b>Welcome to Jace Launcher!</b></p>"
                             "<p>Add your Minecraft accounts to get started. Sign in with Microsoft to play online "
                             "and change your skin & cape, or add an offline account.</p>"), 1)
        lay.addLayout(row)
        page = AccountsPage()
        page.layout().setContentsMargins(0, 0, 0, 0)
        for i in range(2):
            page.layout().itemAt(i).widget().hide()
        lay.addWidget(page, 1)
        buttons = QHBoxLayout()
        skip = QPushButton("Skip for now")
        skip.clicked.connect(self.accept)
        go = QPushButton("Continue")
        go.setObjectName("primary")
        go.clicked.connect(self.accept)
        buttons.addStretch()
        buttons.addWidget(skip)
        buttons.addWidget(go)
        lay.addLayout(buttons)


def confirm_uninstall(parent=None) -> bool:
    """Ask, then delete Jace Launcher (and optionally all user data). Returns True if deleted."""
    from jace.config import DATA_DIR
    from jace.instances import list_instances

    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle("Delete Jace Launcher")
    box.setText("<b>Delete Jace Launcher?</b>")
    box.setInformativeText("This removes:<ul>" + "".join(f"<li>{r}</li>" for r in desktop.removal_summary())
                           + "</ul>")
    purge = QCheckBox("Also delete my instances, worlds, skins and accounts")
    purge.setToolTip(str(DATA_DIR))
    box.setCheckBox(purge)
    delete = box.addButton("Delete", QMessageBox.ButtonRole.DestructiveRole)
    box.addButton(QMessageBox.StandardButton.Cancel)
    box.exec()
    if box.clickedButton() is not delete:
        return False

    if purge.isChecked():
        n = len(list_instances())
        if QMessageBox.warning(
                parent, "Delete all data?",
                f"This permanently deletes {n} instance(s) including all worlds, plus your skin library and "
                "saved accounts. It can't be undone.\n\nDelete everything?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return False

    desktop.delete_app(remove_data=purge.isChecked())
    QMessageBox.information(parent, "Deleted", "Jace Launcher has been deleted. The app will now close.")
    QApplication.quit()
    return True
