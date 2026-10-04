"""Accounts page and the Microsoft sign-in dialog."""
import re
import webbrowser

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout, QWidget)

from jace import accounts as acc_mod
from jace.accounts import accounts
from jace.skin_render import render_head
from jace.ui.common import fetch_image, run_task, show_error

try:
    import shiboken6
    from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
    from PySide6.QtWebEngineWidgets import QWebEngineView
    HAVE_WEBENGINE = True
except ImportError:  # pragma: no cover
    HAVE_WEBENGINE = False


class MicrosoftLoginDialog(QDialog):
    """Shows the Microsoft login page and captures the redirect containing ?code=."""
    got_code = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Sign in with Microsoft")
        self.resize(520, 680)
        self.url, self.redirect = acc_mod.login_url()
        self.code = None
        lay = QVBoxLayout(self)
        if HAVE_WEBENGINE:
            # private profile so each sign-in starts clean (lets users pick another account)
            # (no Qt parent: we delete page -> view -> profile ourselves in done())
            self.profile = QWebEngineProfile()
            self.view = QWebEngineView(self)
            self.page = QWebEnginePage(self.profile)
            self.view.setPage(self.page)
            self.view.urlChanged.connect(self._url_changed)
            self.view.setUrl(QUrl(self.url))
            lay.addWidget(self.view)
        else:
            self._build_fallback(lay)

    def done(self, result):
        # The page must be destroyed before its profile, or Qt warns
        # "Release of profile requested but WebEnginePage still not deleted".
        if HAVE_WEBENGINE and getattr(self, "page", None) is not None:
            self.view.urlChanged.disconnect(self._url_changed)
            self.view.setPage(None)
            shiboken6.delete(self.page)
            shiboken6.delete(self.view)
            shiboken6.delete(self.profile)
            self.page = None
        super().done(result)

    def _build_fallback(self, lay):
        lay.addWidget(QLabel("1. Click below to open the Microsoft sign-in page in your browser.\n"
                             "2. After signing in you'll land on a blank page.\n"
                             "3. Copy that page's full address and paste it here."))
        b = QPushButton("Open sign-in page")
        b.clicked.connect(lambda: webbrowser.open(self.url))
        lay.addWidget(b)
        self.paste = QLineEdit()
        self.paste.setPlaceholderText("Paste the redirected URL here")
        lay.addWidget(self.paste)
        ok = QPushButton("Continue")
        ok.setObjectName("primary")
        ok.clicked.connect(lambda: self._url_changed(QUrl(self.paste.text().strip())))
        lay.addWidget(ok)
        lay.addStretch()

    def _url_changed(self, url: QUrl):
        s = url.toString()
        if not s.startswith(self.redirect):
            return
        try:
            code = acc_mod.code_from_redirect(s)
        except acc_mod.AuthError as e:
            show_error(self, str(e))
            QTimer.singleShot(0, self.reject)
            return
        if code and self.code is None:
            self.code = code
            # close after this signal returns: done() deletes the view that emitted it
            QTimer.singleShot(0, self.accept)


class AccountsPage(QWidget):
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("page")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        title = QLabel("Accounts")
        title.setObjectName("h1")
        lay.addWidget(title)
        sub = QLabel("Sign in with Microsoft to play online and change your skin & cape. "
                     "Offline accounts work for singleplayer and offline-mode servers.")
        sub.setObjectName("muted")
        sub.setWordWrap(True)
        lay.addWidget(sub)

        self.list = QListWidget()
        self.list.setIconSize(self.list.iconSize() * 2)
        self.list.itemDoubleClicked.connect(self._select)
        lay.addWidget(self.list, 1)

        row = QHBoxLayout()
        ms = QPushButton("Add Microsoft account")
        ms.setObjectName("primary")
        ms.clicked.connect(self.add_microsoft)
        off = QPushButton("Add offline account")
        off.clicked.connect(self.add_offline)
        use = QPushButton("Use selected")
        use.clicked.connect(lambda: self._select(self.list.currentItem()))
        rm = QPushButton("Remove")
        rm.setObjectName("danger")
        rm.clicked.connect(self.remove)
        for b in (ms, off):
            row.addWidget(b)
        row.addStretch()
        row.addWidget(use)
        row.addWidget(rm)
        lay.addLayout(row)
        self.status = QLabel("")
        self.status.setObjectName("muted")
        lay.addWidget(self.status)
        self.refresh()

    def refresh(self):
        self.list.clear()
        cur = accounts.current()
        for a in accounts.accounts:
            kind = "Microsoft" if a["type"] == "msa" else "Offline"
            mark = "   ✓ active" if cur and a["uuid"] == cur["uuid"] else ""
            it = QListWidgetItem(f"{a['username']}\n{kind}{mark}")
            it.setData(Qt.ItemDataRole.UserRole, a["uuid"])
            self.list.addItem(it)
            self._load_head(it, a)
        if not accounts.accounts:
            self.list.addItem(QListWidgetItem("No accounts yet - add one below."))

    def _load_head(self, item, a):
        if a["type"] != "msa":
            return

        def fetch():
            return fetch_image(acc_mod.skin_for_uuid(a["uuid"])[0])

        def done(img):
            try:
                item.setIcon(render_head(img, 48))
            except RuntimeError:
                pass
        run_task(fetch, on_done=done, on_error=lambda m: None)

    def _select(self, item):
        if not item or not item.data(Qt.ItemDataRole.UserRole):
            return
        accounts.select(item.data(Qt.ItemDataRole.UserRole))
        self.refresh()
        self.changed.emit()

    def remove(self):
        it = self.list.currentItem()
        if not it or not it.data(Qt.ItemDataRole.UserRole):
            return
        if QMessageBox.question(self, "Remove account", f"Remove {it.text().splitlines()[0]}?") == QMessageBox.StandardButton.Yes:
            accounts.remove(it.data(Qt.ItemDataRole.UserRole))
            self.refresh()
            self.changed.emit()

    def add_offline(self):
        name, ok = QInputDialog.getText(self, "Offline account", "Username (3-16 letters, numbers or _):")
        if not ok:
            return
        name = name.strip()
        if not re.fullmatch(r"[A-Za-z0-9_]{3,16}", name):
            show_error(self, "Usernames must be 3-16 characters: letters, numbers and underscores.")
            return
        accounts.add_offline(name)
        self.refresh()
        self.changed.emit()

    def add_microsoft(self):
        dlg = MicrosoftLoginDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.code:
            return
        self.status.setText("Signing in to Xbox Live and Minecraft...")

        def done(acc):
            accounts.add(acc)
            self.status.setText(f"Signed in as {acc['username']}")
            self.refresh()
            self.changed.emit()

        def fail(msg):
            self.status.setText("")
            show_error(self, msg, "Sign-in failed")
        run_task(acc_mod.complete_microsoft_login, dlg.code, on_done=done, on_error=fail)
