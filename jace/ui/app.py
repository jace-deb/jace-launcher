"""Main window: sidebar navigation, pages, and the play bar."""
import subprocess
import sys
import threading
import time

from PySide6.QtCore import QTimer, Signal
from PySide6.QtGui import QFont, QIcon, QPixmap, QTextCursor
from PySide6.QtWidgets import (QApplication, QButtonGroup, QDialog, QFileDialog, QHBoxLayout, QInputDialog, QLabel,
                               QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QStackedWidget,
                               QVBoxLayout, QWidget)

from jace import APP_NAME, APP_VERSION, AUTHOR, desktop, social, macinstall, updater, wininstall
from jace.accounts import accounts
from jace.config import settings
from jace.content import import_modpack_file
from jace.ui.accounts_page import AccountsPage
from jace.ui.browse_page import BrowsePage
from jace.ui.common import STYLE, run_task, show_error
from jace.ui.friends_page import FriendsPage
from jace.ui.social_live import SocialLive
from jace.ui import launcher_link
from jace.ui.calls import CallManager
from jace.instance_icons import icon_image
from jace.instances import list_instances
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
        self.friends_page = FriendsPage()
        self.settings_page = SettingsPage()
        for i, (label, page) in enumerate((("🎮  Library", self.library), ("🧩  Browse", self.browse),
                                           ("👕  Skins && Capes", self.skins), ("👤  Accounts", self.accounts_page),
                                           ("👥  Friends", self.friends_page),
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
        ver = QLabel(f"v{APP_VERSION}  ·  by {AUTHOR}")
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
        self.update_btn = QPushButton()
        self.update_btn.setObjectName("primary")
        self.update_btn.hide()
        self.update_btn.clicked.connect(lambda: self.start_update(self.update_info))
        bl.addWidget(self.update_btn)
        self.update_info = None
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
        self.friends_page.join_requested.connect(self._join_friend)
        self.friends_page.unread_changed.connect(self._unread_changed)
        self.friends_page.signed_in.connect(self._social_signed_in)
        self.playing = None          # (instance, server) while a game launched from here runs
        self._playing_since = None
        self.live = SocialLive(self)
        self.live.message.connect(self._on_social_message)
        self.live.message.connect(self.friends_page.on_message)
        self.live.friends.connect(self._on_social_friends)
        self.live.presence.connect(self.friends_page.on_change)
        self.calls = CallManager(self)
        self.live.call.connect(self.calls.on_live)
        self.calls.error.connect(lambda m: self.notify(f"📞  {m}"))
        self.calls.incoming.connect(self._incoming_call)
        self.friends_page.set_calls(self.calls)
        launcher_link.start(self.calls)
        self._presence_timer = QTimer(self, interval=120_000)
        self._presence_timer.timeout.connect(self._send_presence)
        QTimer.singleShot(1500, self._start_social)
        self.settings_page.check_updates_requested.connect(lambda: self.check_updates(manual=True))
        if settings.get("auto_update_check") is not False and not updater.unsupported_reason():
            QTimer.singleShot(3000, self.check_updates)
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
                self.update_btn.setEnabled(True)
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

    # -- updates
    def check_updates(self, manual=False):
        reason = updater.unsupported_reason()
        if reason and manual:
            QMessageBox.information(self, "Updates", reason)
            return
        if manual:
            self.notify("Checking for updates…")

        def done(info):
            if info:
                self.update_info = info
                self.update_btn.setText(f"⬆  Update to {info['version']}")
                self.update_btn.show()
                self.notify(f"Jace Launcher {info['version']} is available")
                if manual:
                    self.start_update(info)
            elif manual:
                self.notify("Up to date")
                QMessageBox.information(self, "Updates", f"You have the latest version ({updater.current_version()}).")

        def fail(msg):
            if manual:
                show_error(self, f"Couldn't check for updates: {msg}")
        run_task(updater.check, on_done=done, on_error=fail)

    def start_update(self, info):
        if not info or self.busy:
            return
        box = QMessageBox(self)
        box.setWindowTitle("Update Jace Launcher")
        box.setText(f"<b>Update to Jace Launcher {info['version']}?</b><br>"
                    f"You have {updater.current_version()}. The app restarts when the update is ready. "
                    "Your instances, worlds and accounts are kept.")
        if info.get("notes"):
            box.setDetailedText(info["notes"])
        go = box.addButton("Update now", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Later", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is not go:
            return
        self.update_btn.setEnabled(False)

        def done(_):
            self.notify("Restarting…")
            QApplication.quit()
        self.run_job(updater.apply, f"Updating to {info['version']}", done, True, info)

    # -- state
    def _account_changed(self):
        a = accounts.current()
        self.account_btn.setText(f"👤  {a['username']}" if a else "👤  Add account")
        self.browse.refresh_instances()
        if hasattr(self, "live"):           # switching accounts switches Jace Social identity
            self.live.stop()
            self._presence_timer.stop()
            self._unread_changed(0)
            self.friends_page._sign_in_error = ""   # new account: try again straight away
            self.friends_page.update_mode()
            self._start_social()

    # -- Jace Social (friends & chat)
    def _start_social(self):
        s = social.current_session()
        if not s:
            self.friends_page.auto_sign_in()    # signs in on its own, then calls back here
            return
        self.live.start(s.get("realtime") or {}, s.get("inbox", ""))
        self._presence_timer.start()
        self._send_presence()
        self.friends_page.refresh(quiet=True)

    def _social_signed_in(self, s):
        self._start_social()

    def _activity(self):
        if self.playing:
            inst, server = self.playing
            if any(p.name.startswith(("jacefriends", "jace-friends", "jacesocial", "jace_social"))
                   for p in inst.content_dir("mod").glob("*.jar")):
                return None          # the Jace Social mod reports richer status from inside the game
            return {"type": "playing", "instance": inst.name, "version": inst.mc_version, "loader": inst.loader,
                    "modpack": (inst.data.get("modpack") or {}).get("name") if isinstance(inst.data.get("modpack"), dict) else None, "server": server,
                    "started_at": self._playing_since, "app": "jace-launcher"}
        return {"type": "launcher", "app": "jace-launcher"}

    def _send_presence(self):
        if not social.current_session():
            return
        act = self._activity()
        if act is None:
            return
        run_task(social.set_presence, act, on_error=lambda m: None)

    def _unread_changed(self, n):
        self.nav.button(4).setText(f"👥  Friends ({n})" if n else "👥  Friends")

    def _incoming_call(self, name):
        self.notify(f"📞  {name} is calling you")
        QApplication.alert(self)
        if self.friends_page.isHidden() and not self.playing:
            self.go(self.stack.indexOf(self.friends_page))

    def _on_social_message(self, payload):
        if not (self.isVisible() and self.stack.currentWidget() is self.friends_page):
            self.notify(f"💬  New message from {payload.get('name', 'a friend')}")

    def _on_social_friends(self, payload):
        if payload.get("kind") == "request":
            self.notify(f"👥  {payload.get('name', 'Someone')} sent you a friend request")
        elif payload.get("kind") == "accepted":
            self.notify(f"👥  {payload.get('name', 'Someone')} accepted your friend request")
        self.friends_page.on_change(payload)

    def go_offline(self):
        """Called when the launcher quits."""
        if social.current_session() and not self.playing:
            try:
                social.set_presence(None, offline=True)
            except Exception:  # noqa: BLE001
                pass

    def _selection_changed(self, inst):
        self.selected_label.setText(f"<b>{inst.name}</b><br><span style='color:#8b919c'>{inst.describe()}</span>"
                                    if inst else "")
        self.play_btn.setEnabled(inst is not None and self.busy == 0)

    def _join_friend(self, address, version):
        """Join a friend's hosted world / server with an instance of the right version."""
        insts = self.library.instances()
        cur = self.library.current()
        match = [i for i in insts if i.mc_version == version] if version else []
        inst = (cur if cur in match else match[0]) if match else (cur if not version else None)
        if not inst:
            QMessageBox.information(self, "No matching instance",
                                    f"Your friend is playing Minecraft {version}. Create an instance with "
                                    f"{version} (Library → New instance), then click Join again.")
            self.go(0)
            return
        self.notify(f"Joining {address} with {inst.name}…")
        self.play(inst, address)

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
    def play(self, inst, server: str | None = None):
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
            return inst.launch(account, server)

        def started(proc):
            self.notify(f"Playing {inst.name}")
            self.playing = (inst, server)
            self._playing_since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            self._send_presence()
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
        self.playing = None
        self._send_presence()
        if self.isHidden():
            self.show()
        self.notify(f"{inst.name} closed" + (f" (exit code {code})" if code else ""))
        if code not in (0, None):
            con.show()
            con.raise_()


def should_run_setup(argv) -> bool:
    if "--install" in argv:
        return True
    # The downloaded AppImage / .app / .exe must be installed before it can be used
    return bool(desktop.setup_available() and not desktop.running_installed_copy())


def self_test(app) -> int:
    """Used by CI on packaged builds: prove the bundle starts (Qt, WebEngine, all pages,
    bundled assets and the launcher library), then exit. Exit code 0 = OK."""
    import os

    import minecraft_launcher_lib
    from PySide6.QtWebEngineWidgets import QWebEngineView
    results = []
    try:
        w = MainWindow()
        w.show()
        for i in range(w.stack.count()):
            w.go(i)
            app.processEvents()
        view = QWebEngineView()
        view.setHtml("<p>ok</p>")
        app.processEvents()
        assert desktop.ICON_SRC.is_file(), f"missing icon {desktop.ICON_SRC}"
        results.append(f"minecraft-launcher-lib {minecraft_launcher_lib.utils.get_library_version()}")
        results.append("SELF-TEST OK")
        code = 0
    except Exception as e:  # noqa: BLE001
        results.append(f"SELF-TEST FAILED: {e!r}")
        code = 1
    out = os.environ.get("JACE_SELF_TEST_OUT")
    if out:  # windowed Windows builds have no stdout, so CI reads this file
        with open(out, "w") as f:
            f.write("\n".join(results))
    print("\n".join(results))
    return code


def start_installed(installed):
    """Start the freshly installed copy and remove the downloaded one."""
    if desktop.mac_app_bundle():
        macinstall.relaunch_installed(installed, desktop.mac_app_bundle())
    elif wininstall.running_exe():
        wininstall.relaunch(installed, delete_after=wininstall.running_exe())
    else:
        subprocess.Popen([str(installed)], start_new_session=True, env=updater._clean_env())
        downloaded = desktop.running_appimage()
        if downloaded and downloaded.resolve() != installed.resolve():
            downloaded.unlink(missing_ok=True)   # fine on Linux: the running image stays mounted


def quick_launch(argv) -> bool:
    """--launch <instance id> (desktop shortcuts): start that instance with no launcher
    window. Returns False if the main window should open instead (e.g. no account)."""
    import time
    iid = argv[argv.index("--launch") + 1] if argv.index("--launch") + 1 < len(argv) else ""
    inst = next((i for i in list_instances() if i.id == iid), None)
    if not inst:
        show_error(None, f"This shortcut's instance ({iid}) no longer exists.", "Instance not found")
        return True
    acc = accounts.current()
    if not acc:
        QMessageBox.information(None, "Add an account", "Add a Microsoft or offline account first, then try the "
                                "shortcut again.")
        return False

    dlg = QDialog()
    dlg.setWindowTitle(f"Starting {inst.name}")
    dlg.setMinimumWidth(420)
    lay = QHBoxLayout(dlg)
    icon = QLabel()
    icon.setPixmap(QPixmap.fromImage(icon_image(inst, 64)))
    lay.addWidget(icon)
    col = QVBoxLayout()
    col.addWidget(QLabel(f"<b style='font-size:15px'>{inst.name}</b><br>"
                         f"<span style='color:#8b919c'>{inst.describe()} · {acc['username']}</span>"))
    status = QLabel("Getting ready…")
    status.setObjectName("muted")
    bar = QProgressBar()
    bar.setRange(0, 0)
    col.addWidget(status)
    col.addWidget(bar)
    lay.addLayout(col, 1)

    def prepare(callback):
        account = accounts.ensure_fresh(acc)
        inst.install(callback)
        callback["setStatus"]("Starting Minecraft…")
        proc = inst.launch(account, detached=True)
        for _ in range(10):                       # catch an instant crash instead of failing silently
            time.sleep(0.5)
            if proc.poll() is not None and proc.returncode != 0:
                log = inst.game_dir / "logs" / "jace-launch.log"
                tail = log.read_text(errors="replace").splitlines()[-15:] if log.exists() else []
                raise RuntimeError(f"Minecraft closed right away (exit code {proc.returncode}).\n\n"
                                   + "\n".join(tail))
        return proc

    def fail(msg):
        show_error(dlg, msg, f"Couldn't start {inst.name}")
        dlg.reject()

    def prog(v, m):
        if m > 0:
            bar.setRange(0, m)
            bar.setValue(min(v, m))
    run_task(prepare, use_callback=True, on_status=status.setText, on_progress=prog,
             on_done=lambda _: dlg.accept(), on_error=fail)
    dlg.exec()
    return True


def close_splash():
    """Close the PyInstaller splash screen (Windows setup .exe) if there is one."""
    import os
    if "_PYI_SPLASH_IPC" not in os.environ:   # only the Windows setup .exe has a splash
        return
    try:
        import pyi_splash
        pyi_splash.close()
    except Exception:  # noqa: BLE001
        pass


def run_windows_update(argv) -> None:
    """Small progress window shown by the new setup .exe while it updates the app."""
    dlg = QDialog()
    dlg.setWindowTitle("Updating Jace Launcher")
    dlg.setMinimumWidth(420)
    lay = QVBoxLayout(dlg)
    lay.addWidget(QLabel(f"<b>Updating Jace Launcher to {APP_VERSION}</b>"))
    label = QLabel("Starting…")
    label.setObjectName("muted")
    bar = QProgressBar()
    bar.setRange(0, 0)
    lay.addWidget(label)
    lay.addWidget(bar)

    def fail(msg):
        show_error(dlg, msg, "Update failed")
        dlg.reject()
    run_task(lambda callback: desktop.apply_windows_update(argv, callback["setStatus"]), use_callback=True,
             on_status=label.setText, on_done=lambda _: dlg.accept(), on_error=fail)
    dlg.exec()


def main():
    close_splash()
    if desktop.handle_cli(sys.argv[1:]):
        return
    QApplication.setApplicationName(APP_NAME)
    QApplication.setDesktopFileName(desktop.APP_ID)
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    app.setWindowIcon(QIcon(str(desktop.ICON_SRC)))
    argv = sys.argv[1:]
    if "--self-test" in argv:
        sys.exit(self_test(app))
    if "--uninstall-gui" in argv:
        confirm_uninstall()
        return
    if "--apply-update" in argv:
        run_windows_update(argv)
        return
    if should_run_setup(argv):
        wiz = SetupWizard()
        if wiz.exec() != QDialog.DialogCode.Accepted:
            return                       # setup cancelled: nothing runs uninstalled
        settings.set("welcomed", True)
        installed = desktop.installed_path()
        if installed and not desktop.running_installed_copy():
            # we're the downloaded copy: start the installed app (if asked) and quit
            if wiz.launch_after():
                start_installed(installed)
            elif desktop.running_appimage():
                desktop.running_appimage().unlink(missing_ok=True)
            return
        if not wiz.launch_after():
            return
    if "--launch" in argv and quick_launch(argv):
        return
    if not settings.get("welcomed"):
        settings.set("welcomed", True)
        if not accounts.accounts:
            FirstRunDialog().exec()
    w = MainWindow()
    w.show()
    app.aboutToQuit.connect(w.go_offline)
    sys.exit(app.exec())
