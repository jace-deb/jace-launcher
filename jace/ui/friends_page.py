"""Friends page: synced friends list, friend requests, chat and joining friends' worlds."""
import html
from datetime import datetime

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMessageBox, QPushButton, QSplitter, QTextBrowser, QVBoxLayout, QWidget)

from jace import friends as local_friends
from jace import social
from jace.config import settings
from jace.skin_render import render_head
from jace.ui.common import fetch_image, run_task, show_error

COLORS = {"online": "#3ddc84", "hosting": "#b07cf0", "playing": "#4f8fd6", "offline": "#6b717c"}
_heads: dict = {}


def _state(f: dict) -> str:
    if not f.get("online"):
        return "offline"
    t = (f.get("activity") or {}).get("type")
    return t if t in ("hosting", "playing") else "online"


def _load_head(label: QLabel, uuid: str, size=40):
    if uuid in _heads:
        label.setPixmap(render_head(_heads[uuid], size))
        return

    def fetch():
        sk = local_friends.skin(uuid)
        if not sk:
            raise LookupError("default skin")
        return fetch_image(sk[0])

    def done(img):
        _heads[uuid] = img
        try:
            label.setPixmap(render_head(img, size))
        except RuntimeError:
            pass
    run_task(fetch, on_done=done, on_error=lambda m: None)


class FriendRow(QFrame):
    def __init__(self, f: dict, kind: str, page: "FriendsPage"):
        super().__init__()
        self.f, self.kind = f, kind
        self.setObjectName("card")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        head = QLabel()
        head.setFixedSize(40, 40)
        head.setStyleSheet("background:#262a33;border-radius:6px;")
        _load_head(head, f["uuid"])
        lay.addWidget(head)
        col = QVBoxLayout()
        unread = f.get("unread", 0)
        badge = (f"  <span style='background:#3ddc84;color:#0c1410;border-radius:8px;padding:0 6px;"
                 f"font-weight:700'>&nbsp;{unread}&nbsp;</span>") if unread else ""
        col.addWidget(QLabel(f"<b>{html.escape(f['name'])}</b>{badge}"))
        state = _state(f)
        line = {"incoming": "Wants to be friends", "outgoing": "Request sent"}.get(kind, social.describe_activity(f))
        status = QLabel(f"<span style='color:{COLORS[state]}'>●</span> {html.escape(line)}")
        status.setObjectName("muted")
        col.addWidget(status)
        lay.addLayout(col, 1)
        if kind == "incoming":
            ok = QPushButton("Accept")
            ok.setObjectName("primary")
            ok.clicked.connect(lambda: page.respond(f, True))
            no = QPushButton("Decline")
            no.clicked.connect(lambda: page.respond(f, False))
            lay.addWidget(ok)
            lay.addWidget(no)
        elif kind == "outgoing":
            cancel = QPushButton("Cancel")
            cancel.clicked.connect(lambda: page.remove(f, confirm=False))
            lay.addWidget(cancel)


class ChatPanel(QWidget):
    def __init__(self, page: "FriendsPage"):
        super().__init__()
        self.page = page
        self.friend: dict | None = None
        self.my_uuid = ""
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        self.title = QLabel("")
        self.title.setTextFormat(Qt.TextFormat.RichText)
        top.addWidget(self.title, 1)
        self.join_btn = QPushButton("Join")
        self.join_btn.setObjectName("primary")
        self.join_btn.clicked.connect(lambda: self.friend and page.join(self.friend))
        self.remove_btn = QPushButton("Remove friend")
        self.remove_btn.setObjectName("danger")
        self.remove_btn.clicked.connect(lambda: self.friend and page.remove(self.friend))
        self.call_btn = QPushButton("📞  Call")
        self.call_btn.clicked.connect(lambda: self.friend and page.calls and
                                      page.calls.call(self.friend["uuid"], self.friend["name"]))
        top.addWidget(self.join_btn)
        top.addWidget(self.call_btn)
        top.addWidget(self.remove_btn)
        lay.addLayout(top)
        self.log = QTextBrowser()
        self.log.setOpenExternalLinks(True)
        lay.addWidget(self.log, 1)
        row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setMaxLength(500)
        self.input.setPlaceholderText("Message…")
        self.input.returnPressed.connect(self.send)
        self.send_btn = QPushButton("Send")
        self.send_btn.setObjectName("primary")
        self.send_btn.clicked.connect(self.send)
        row.addWidget(self.input, 1)
        row.addWidget(self.send_btn)
        lay.addLayout(row)
        self.show_friend(None)

    def show_friend(self, f: dict | None):
        self.friend = f
        enabled = f is not None
        for w in (self.input, self.send_btn, self.remove_btn, self.call_btn):
            w.setEnabled(enabled)
        if not f:
            self.title.setText("<span style='color:#8b919c'>Pick a friend to chat</span>")
            self.join_btn.hide()
            self.log.setHtml("")
            return
        self.title.setText(f"<b style='font-size:16px'>{html.escape(f['name'])}</b><br>"
                           f"<span style='color:{COLORS[_state(f)]}'>●</span> "
                           f"<span style='color:#8b919c'>{html.escape(social.describe_activity(f))}</span>")
        addr = social.join_address(f)
        self.join_btn.setVisible(bool(addr))
        self.join_btn.setToolTip(f"Join {addr}" if addr else "")
        self.reload()

    def reload(self):
        f = self.friend
        if not f:
            return
        uuid = f["uuid"]

        def done(msgs):
            if self.friend and self.friend["uuid"] == uuid:
                self.render(msgs)
                if any(m["sender"] == uuid and not m.get("read_at") for m in msgs):
                    run_task(social.mark_read, uuid, on_done=lambda _: self.page.refresh(quiet=True),
                             on_error=lambda m: None)
        run_task(social.messages, uuid, on_done=done, on_error=lambda m: self.log.setHtml(
            f"<p style='color:#e0605a'>{html.escape(m)}</p>"))

    def render(self, msgs: list[dict]):
        parts = []
        for m in msgs:
            mine = m["sender"] == self.my_uuid
            who = "You" if mine else html.escape(self.friend["name"])
            when = datetime.fromisoformat(m["created_at"].replace("Z", "+00:00")).astimezone().strftime("%b %d %H:%M")
            color = "#3ddc84" if mine else "#4f8fd6"
            parts.append(f"<p style='margin:6px 0'><b style='color:{color}'>{who}</b> "
                         f"<span style='color:#6b717c;font-size:11px'>{when}</span><br>"
                         f"{html.escape(m['body'])}</p>")
        self.log.setHtml("".join(parts) or "<p style='color:#8b919c'>No messages yet - say hi!</p>")
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())

    def send(self):
        text = self.input.text().strip()
        if not text or not self.friend:
            return
        self.input.clear()
        self.send_btn.setEnabled(False)

        def done(_):
            self.send_btn.setEnabled(True)
            self.reload()

        def fail(msg):
            self.send_btn.setEnabled(True)
            self.input.setText(text)
            show_error(self, msg, "Message not sent")
        run_task(social.send_message, self.friend["uuid"], text, on_done=done, on_error=fail)


class FriendsPage(QWidget):
    join_requested = Signal(str, str)        # address, minecraft version
    unread_changed = Signal(int)
    signed_in = Signal(dict)                 # session (to start live notifications)

    def __init__(self):
        super().__init__()
        self.setObjectName("page")
        self.data = {"friends": [], "incoming": [], "outgoing": []}
        self._signing_in = False          # Jace Social signs in automatically with your Minecraft account
        self._sign_in_error = ""
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        top = QHBoxLayout()
        t = QLabel("Friends")
        t.setObjectName("h1")
        top.addWidget(t)
        self.who = QLabel("")
        self.who.setObjectName("muted")
        top.addWidget(self.who)
        top.addStretch()
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(lambda: self.refresh())
        self.add_btn = QPushButton("+  Add friend")
        self.add_btn.setObjectName("primary")
        self.add_btn.clicked.connect(self.add_friend)
        top.addWidget(self.refresh_btn)
        top.addWidget(self.add_btn)
        outer.addLayout(top)

        # voice call bar (hidden unless there's a call)
        self.calls = None
        self.call_bar = QFrame()
        self.call_bar.setObjectName("card")
        cb = QHBoxLayout(self.call_bar)
        cb.setContentsMargins(16, 10, 16, 10)
        self.call_text = QLabel("")
        cb.addWidget(self.call_text, 1)
        self.answer_btn = QPushButton("Answer")
        self.answer_btn.setObjectName("primary")
        self.mute_btn = QPushButton("Mute")
        self.hangup_btn = QPushButton("Hang up")
        self.hangup_btn.setObjectName("danger")
        for w in (self.answer_btn, self.mute_btn, self.hangup_btn):
            cb.addWidget(w)
        self.call_bar.hide()
        outer.addWidget(self.call_bar)

        # signed-out panel
        self.signin = QFrame()
        self.signin.setObjectName("card")
        sl = QVBoxLayout(self.signin)
        sl.setContentsMargins(24, 24, 24, 24)
        self.signin_text = QLabel()
        self.signin_text.setWordWrap(True)
        self.signin_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sl.addStretch()
        sl.addWidget(self.signin_text)
        sl.addStretch()
        outer.addWidget(self.signin, 1)

        # signed-in view
        self.split = QSplitter()
        self.list = QListWidget()
        self.list.setSpacing(3)
        self.list.setMinimumWidth(320)
        self.list.setStyleSheet("QListWidget { background: transparent; border: none; } "
                                "QListWidget::item { background: transparent; } "
                                "QListWidget::item:selected { background: #23332a; border-radius: 12px; }")
        self.list.currentItemChanged.connect(self._selected)
        self.chat = ChatPanel(self)
        self.split.addWidget(self.list)
        self.split.addWidget(self.chat)
        self.split.setSizes([360, 640])
        outer.addWidget(self.split, 1)
        self._poll = QTimer(self, interval=60_000)      # fallback refresh if live updates drop
        self._poll.timeout.connect(lambda: self.refresh(quiet=True))
        self.update_mode()

    # --- voice calls
    def set_calls(self, calls):
        self.calls = calls
        self.answer_btn.clicked.connect(calls.answer)
        self.mute_btn.clicked.connect(calls.toggle_mute)
        self.hangup_btn.clicked.connect(lambda: calls.hang_up())
        calls.changed.connect(self._call_changed)

    def _call_changed(self):
        c = self.calls
        name = html.escape(c.peer_name or "a friend")
        text = {"calling": f"📞  Calling <b>{name}</b>…", "ringing": f"📞  <b>{name}</b> is calling you",
                "in-call": f"🔊  In a call with <b>{name}</b>" + (" (muted)" if c.muted else "")}.get(c.state, "")
        self.call_text.setText(text)
        self.call_bar.setVisible(c.state != "idle")
        self.answer_btn.setVisible(c.state == "ringing")
        self.mute_btn.setVisible(c.state == "in-call")
        self.mute_btn.setText("Unmute" if c.muted else "Mute")
        self.hangup_btn.setText("Decline" if c.state == "ringing" else "Hang up")
        self.chat.call_btn.setEnabled(c.state == "idle" and self.chat.friend is not None)

    # --- state
    def update_mode(self):
        s = social.current_session()
        why = social.can_sign_in()
        self.signin.setVisible(s is None)
        self.split.setVisible(s is not None)
        self.add_btn.setEnabled(s is not None)
        self.refresh_btn.setEnabled(s is not None)
        if s:
            self.who.setText(f"  signed in as {s['name']}")
            self.chat.my_uuid = s["uuid"]
            self._poll.start()
        else:
            self.who.setText("")
            self._poll.stop()
            if self._signing_in:
                note = "<p style='color:#8b919c'>Signing in to Jace Social…</p>"
            elif self._sign_in_error:
                note = (f"<p style='color:#e0b44a'>Couldn't sign in: {html.escape(self._sign_in_error)}</p>"
                        "<p style='color:#8b919c'>It'll try again next time you open Friends.</p>")
            else:
                note = f"<p style='color:#e0b44a'>{html.escape(why)}</p>" if why else ""
            self.signin_text.setText(
                "<p style='font-size:16px'><b>Friends & chat, everywhere</b></p>"
                "<p>Your friends list is synced to your Minecraft account, so it follows you to any computer "
                "and into the game with the <b>Jace Social</b> mod, the web and the desktop app. Chat with friends and join the worlds "
                "they're hosting in one click.</p>" + note)

    def showEvent(self, e):
        super().showEvent(e)
        self.update_mode()
        if social.current_session():
            self.refresh()
        else:
            self.auto_sign_in()

    def auto_sign_in(self):
        """Sign in to Jace Social with the selected Microsoft account, quietly.
        Called at startup, when the account changes and when Friends opens."""
        if self._signing_in or social.current_session() or social.can_sign_in():
            return
        self._signing_in = True
        self._sign_in_error = ""
        self.update_mode()

        def done(s):
            self._signing_in = False
            self.update_mode()
            self.signed_in.emit(s)
            self.refresh()
            self._offer_migration()

        def fail(msg):
            self._signing_in = False
            self._sign_in_error = msg
            self.update_mode()
        run_task(social.sign_in, on_done=done, on_error=fail)

    def _offer_migration(self):
        """Old local-only friends list -> send them friend requests once."""
        if settings.get("friends_migrated"):
            return
        old = local_friends.load()
        settings.set("friends_migrated", True)
        if not old or QMessageBox.question(
                self, "Bring your friends along?", f"You have {len(old)} friend(s) saved on this computer. "
                "Send them friend requests so they're on your synced list?") != QMessageBox.StandardButton.Yes:
            return

        def work():
            sent = 0
            for f in old:
                try:
                    social.add_friend(f["name"])
                    sent += 1
                except social.SocialError:
                    pass
            return sent
        run_task(work, on_done=lambda n: (self.refresh(), self.who.setText(f"  sent {n} friend request(s)")))

    def refresh(self, quiet=False):
        if not social.current_session():
            return

        def done(d):
            self.data = d
            self._fill()
            self.unread_changed.emit(sum(f.get("unread", 0) for f in d["friends"]))

        def fail(msg):
            if not quiet:
                show_error(self, msg, "Couldn't load friends")
        run_task(social.friends, on_done=done, on_error=fail)

    def _fill(self):
        keep = self.chat.friend["uuid"] if self.chat.friend else None
        self.list.blockSignals(True)
        self.list.clear()

        def header(text):
            it = QListWidgetItem(text)
            it.setFlags(Qt.ItemFlag.NoItemFlags)
            it.setForeground(Qt.GlobalColor.gray)
            self.list.addItem(it)

        def row(f, kind):
            w = FriendRow(f, kind, self)
            it = QListWidgetItem()
            it.setSizeHint(QSize(100, w.sizeHint().height() + 2))
            it.setData(Qt.ItemDataRole.UserRole, (kind, f))
            if kind != "friend":
                it.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.list.addItem(it)
            self.list.setItemWidget(it, w)
            return it

        if self.data["incoming"]:
            header(f"FRIEND REQUESTS ({len(self.data['incoming'])})")
            for f in self.data["incoming"]:
                row(f, "incoming")
        order = {"hosting": 0, "playing": 1, "online": 2, "offline": 3}
        fr = sorted(self.data["friends"], key=lambda f: (order[_state(f)], f["name"].lower()))
        online = sum(1 for f in fr if f.get("online"))
        header(f"FRIENDS ({online} online)" if fr else "FRIENDS")
        selected = None
        for f in fr:
            it = row(f, "friend")
            if f["uuid"] == keep:
                selected = (it, f)
        if not fr:
            header("   No friends yet - click “+ Add friend”")
        if self.data["outgoing"]:
            header("SENT REQUESTS")
            for f in self.data["outgoing"]:
                row(f, "outgoing")
        self.list.blockSignals(False)
        if selected:
            self.list.setCurrentItem(selected[0])
            self.chat.friend = selected[1]
            self.chat.show_friend(selected[1])

    def _selected(self, it, _prev=None):
        data = it.data(Qt.ItemDataRole.UserRole) if it else None
        if data and data[0] == "friend":
            self.chat.show_friend(data[1])

    # --- actions
    def add_friend(self):
        name, ok = QInputDialog.getText(self, "Add friend", "Their Minecraft username:")
        if not ok or not name.strip():
            return

        def done(r):
            f = r["friend"]
            if r["status"] == "accepted":
                msg = f"You and {f['name']} are now friends!"
            elif f.get("uses_jace"):
                msg = f"Friend request sent to {f['name']}."
            else:
                msg = (f"Friend request sent to {f['name']}. They haven't used Jace Launcher yet - "
                       "they'll see it when they sign in.")
            QMessageBox.information(self, "Add friend", msg)
            self.refresh()
        run_task(social.add_friend, name, on_done=done, on_error=lambda m: show_error(self, m, "Couldn't add friend"))

    def respond(self, f, accept):
        run_task(social.respond, f["uuid"], accept, on_done=lambda _: self.refresh(),
                 on_error=lambda m: show_error(self, m))

    def remove(self, f, confirm=True):
        if confirm and QMessageBox.question(self, "Remove friend", f"Remove {f['name']} from your friends?") \
                != QMessageBox.StandardButton.Yes:
            return
        if self.chat.friend and self.chat.friend["uuid"] == f["uuid"]:
            self.chat.show_friend(None)
        run_task(social.remove_friend, f["uuid"], on_done=lambda _: self.refresh(),
                 on_error=lambda m: show_error(self, m))

    def join(self, f):
        addr = social.join_address(f)
        if addr:
            self.join_requested.emit(addr, (f.get("activity") or {}).get("version") or "")

    # --- live events (wired up by the main window)
    def on_message(self, payload):
        if self.chat.friend and self.chat.friend["uuid"] == payload.get("from") and self.isVisible():
            self.chat.reload()
        else:
            self.refresh(quiet=True)

    def on_change(self, _payload=None):
        self.refresh(quiet=True)
