"""Live notifications from Jace Social over Supabase Realtime (Phoenix websocket).

We join our own private channel (an unguessable name only we and the server
know) and turn broadcasts into Qt signals. Payloads only say what changed; the
UI then fetches details through the authenticated API.
"""
import json
from urllib.parse import quote

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtWebSockets import QWebSocket


class SocialLive(QObject):
    message = Signal(dict)      # {from, name, id}
    friends = Signal(dict)      # {kind: request|accepted|removed, uuid, name?}
    presence = Signal(dict)     # {uuid}
    call = Signal(dict)         # {id, kind: offer|answer|hangup, call_id, from, name}
    connected = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.ws = QWebSocket()
        self.ws.connected.connect(self._on_open)
        self.ws.disconnected.connect(self._on_close)
        self.ws.textMessageReceived.connect(self._on_text)
        self._heartbeat = QTimer(self, interval=25_000)
        self._heartbeat.timeout.connect(self._beat)
        self._retry = QTimer(self, singleShot=True)
        self._retry.timeout.connect(self._open)
        self._ref = 0
        self._topic = None
        self._url = None
        self._wanted = False

    def start(self, realtime: dict, inbox: str):
        if not realtime or not realtime.get("url") or not realtime.get("key"):
            return
        host = realtime["url"].replace("https://", "wss://").replace("http://", "ws://").rstrip("/")
        self._url = f"{host}/realtime/v1/websocket?apikey={quote(realtime['key'])}&vsn=1.0.0"
        self._topic = f"realtime:{inbox}"
        self._wanted = True
        self._open()

    def stop(self):
        self._wanted = False
        self._heartbeat.stop()
        self._retry.stop()
        self.ws.close()

    def _open(self):
        if self._wanted and self._url:
            self.ws.open(QUrl(self._url))

    def _send(self, topic, event, payload):
        self._ref += 1
        self.ws.sendTextMessage(json.dumps({"topic": topic, "event": event, "payload": payload,
                                            "ref": str(self._ref), "join_ref": "1"}))

    def _on_open(self):
        self._send(self._topic, "phx_join", {"config": {"broadcast": {"ack": False, "self": False},
                                                        "presence": {"key": ""}, "private": False}})
        self._heartbeat.start()
        self.connected.emit(True)

    def _on_close(self):
        self._heartbeat.stop()
        self.connected.emit(False)
        if self._wanted:
            self._retry.start(5_000)        # reconnect

    def _beat(self):
        self._send("phoenix", "heartbeat", {})

    def _on_text(self, text):
        try:
            msg = json.loads(text)
        except ValueError:
            return
        if msg.get("event") != "broadcast":
            return
        inner = msg.get("payload") or {}
        kind, payload = inner.get("event"), inner.get("payload") or {}
        if kind == "message":
            self.message.emit(payload)
        elif kind == "friends":
            self.friends.emit(payload)
        elif kind == "presence":
            self.presence.emit(payload)
        elif kind == "call":
            self.call.emit(payload)
