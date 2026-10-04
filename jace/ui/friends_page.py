"""Friends list page."""
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout, QFrame, QHBoxLayout, QInputDialog, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout,
                               QWidget)

from jace import friends
from jace.skin_render import render_head
from jace.ui.common import fetch_image, run_task, show_error

STATE_COLORS = {"online": "#3ddc84", "unknown": "#e0b44a", "server-offline": "#e0605a", "no-server": "#6b717c"}


class EditFriendDialog(QDialog):
    def __init__(self, friend: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Edit {friend['name']}")
        self.setMinimumWidth(420)
        f = QFormLayout(self)
        self.nickname = QLineEdit(friend.get("nickname", ""))
        self.nickname.setPlaceholderText("Optional")
        self.server = QLineEdit(friend.get("server", ""))
        self.server.setPlaceholderText("e.g. play.example.net  or  192.168.1.20:25565")
        f.addRow("Nickname", self.nickname)
        f.addRow("Server they play on", self.server)
        hint = QLabel("Jace Launcher checks this server to see if they're online, and Join takes you there.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        f.addRow(hint)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)


class FriendCard(QFrame):
    join = Signal(dict)
    copy_skin = Signal(dict)
    edit = Signal(dict)
    remove = Signal(dict)

    def __init__(self, friend: dict):
        super().__init__()
        self.friend = friend
        self.setObjectName("card")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        self.head = QLabel()
        self.head.setFixedSize(48, 48)
        self.head.setStyleSheet("background:#262a33;border-radius:8px;")
        lay.addWidget(self.head)
        text = QVBoxLayout()
        nick = f"  <span style='color:#8b919c'>({friend['nickname']})</span>" if friend.get("nickname") else ""
        title = QLabel(f"<b style='font-size:15px'>{friend['name']}</b>{nick}")
        self.status = QLabel("Checking…" if friend.get("server") else "No server saved - click Edit to add one")
        self.status.setObjectName("muted")
        self.dot = QLabel("●")
        self.dot.setStyleSheet(f"color:{STATE_COLORS['no-server']};")
        srow = QHBoxLayout()
        srow.addWidget(self.dot)
        srow.addWidget(self.status, 1)
        text.addWidget(title)
        text.addLayout(srow)
        lay.addLayout(text, 1)
        for label, sig, primary in (("Join", self.join, True), ("Copy skin", self.copy_skin, False),
                                    ("Edit", self.edit, False), ("Remove", self.remove, False)):
            b = QPushButton(label)
            if primary:
                b.setObjectName("primary")
                b.setEnabled(bool(friend.get("server")))
                b.setToolTip("Launch the selected instance and join their server")
            if label == "Remove":
                b.setObjectName("danger")
            b.clicked.connect(lambda _=False, s=sig: s.emit(self.friend))
            lay.addWidget(b)

    def set_head(self, img):
        self.head.setPixmap(render_head(img, 48))

    def set_status(self, st: dict):
        self.status.setText(st["text"])
        self.dot.setStyleSheet(f"color:{STATE_COLORS.get(st['state'], '#6b717c')};")


class FriendsPage(QWidget):
    join_requested = Signal(str)          # server address
    copy_skin_requested = Signal(str, bool)

    def __init__(self):
        super().__init__()
        self.setObjectName("page")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        top = QHBoxLayout()
        t = QLabel("Friends")
        t.setObjectName("h1")
        top.addWidget(t)
        top.addStretch()
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        add = QPushButton("+  Add friend")
        add.setObjectName("primary")
        add.clicked.connect(self.add_friend)
        top.addWidget(refresh)
        top.addWidget(add)
        lay.addLayout(top)
        sub = QLabel("Add friends by their Minecraft username. Save the server they play on to see when they're "
                     "online there and join them in one click.")
        sub.setObjectName("muted")
        sub.setWordWrap(True)
        lay.addWidget(sub)

        self.list = QListWidget()
        self.list.setSpacing(4)
        self.list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.list.setStyleSheet("QListWidget { background: transparent; border: none; } "
                                "QListWidget::item, QListWidget::item:hover, QListWidget::item:selected "
                                "{ background: transparent; }")
        lay.addWidget(self.list, 1)
        self.empty = QLabel("No friends yet.\n\nClick  “+ Add friend”  and type their Minecraft username.")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setObjectName("muted")
        self.empty.setStyleSheet("font-size:15px; background:#1a1d23; border:1px solid #262a32; border-radius:9px;")
        lay.addWidget(self.empty, 1)
        self._generation = 0

    def showEvent(self, e):
        super().showEvent(e)
        self.refresh()

    def refresh(self):
        self._generation += 1
        gen = self._generation
        self.list.clear()
        data = sorted(friends.load(), key=lambda f: (f.get("nickname") or f["name"]).lower())
        self.list.setVisible(bool(data))
        self.empty.setVisible(not data)
        for f in data:
            card = FriendCard(f)
            card.join.connect(lambda fr: self.join_requested.emit(fr["server"]))
            card.copy_skin.connect(self._copy_skin)
            card.edit.connect(self._edit)
            card.remove.connect(self._remove)
            it = QListWidgetItem()
            it.setSizeHint(QSize(100, card.sizeHint().height() + 4))
            it.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addItem(it)
            self.list.setItemWidget(it, card)
            self._load_details(card, gen)

    def _load_details(self, card: FriendCard, gen: int):
        f = card.friend

        def head(img):
            if gen == self._generation:
                try:
                    card.set_head(img)
                except RuntimeError:
                    pass

        def fetch_head():
            sk = friends.skin(f["uuid"])
            if not sk:
                raise LookupError("default skin")
            return fetch_image(sk[0])
        run_task(fetch_head, on_done=head, on_error=lambda m: None)

        def got_status(st):
            if gen == self._generation:
                try:
                    card.set_status(st)
                except RuntimeError:
                    pass
        if f.get("server"):
            run_task(friends.status, f, on_done=got_status, on_error=lambda m: None)

        def got_name(name):   # follow username changes
            if name and name != f["name"]:
                friends.update(f["uuid"], name=name)
        run_task(friends.current_name, f["uuid"], on_done=got_name, on_error=lambda m: None)

    def add_friend(self):
        name, ok = QInputDialog.getText(self, "Add friend", "Their Minecraft username:")
        if not ok or not name.strip():
            return

        def done(friend):
            self.refresh()
            if QMessageBox.question(self, "Add their server?",
                                    f"Added {friend['name']}! Do you know which server they play on?") \
                    == QMessageBox.StandardButton.Yes:
                self._edit(friend)
        run_task(friends.add, name, on_done=done, on_error=lambda m: show_error(self, m, "Couldn't add friend"))

    def _edit(self, friend):
        dlg = EditFriendDialog(friend, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            friends.update(friend["uuid"], nickname=dlg.nickname.text().strip(), server=dlg.server.text().strip())
            self.refresh()

    def _remove(self, friend):
        if QMessageBox.question(self, "Remove friend", f"Remove {friend['name']} from your friends?") \
                == QMessageBox.StandardButton.Yes:
            friends.remove(friend["uuid"])
            self.refresh()

    def _copy_skin(self, friend):
        def done(sk):
            if not sk:
                show_error(self, f"{friend['name']} uses a default skin.", "No custom skin")
                return
            self.copy_skin_requested.emit(sk[0], sk[1])
        run_task(friends.skin, friend["uuid"], on_done=done)

