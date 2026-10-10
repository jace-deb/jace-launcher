"""Voice calls and voice rooms for the launcher UI and for the Jace Social mod (through the
link server): one-to-one calls (CallManager) and server voice channels / group calls
(RoomManager). Both share one Media: the call engine, microphone, speakers, camera and
screen capture. You're in one call or one room at a time."""
from __future__ import annotations

import re
import secrets
from urllib.parse import quote

from PySide6.QtCore import QObject, QTimer, Signal

from jace import social, voice
from jace.ui.common import run_task


class Media(QObject):
    """The call engine plus everything on this computer it uses."""
    peer_state = Signal(str, str)      # key, "connected" / "failed" / "closed"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._engine: voice.Engine | None = None
        self._source = self._sink = self._mic = self._speaker = None
        self._captures = {}
        self._pump = QTimer(self, interval=20)
        self._pump.timeout.connect(self._play)
        self._state.connect(self.peer_state)

    _state = Signal(str, str)

    @property
    def engine(self) -> voice.Engine:
        if self._engine is None:
            self._engine = voice.Engine(self._state.emit)
        return self._engine

    def video_on(self, kind: str) -> bool:
        return kind in self._captures

    def set_video(self, kind: str, on: bool) -> str | None:
        """Turn the camera / screen sharing on or off for everyone we're connected to
        (they still need a new offer to hear about it). Returns why it didn't work."""
        if on == self.video_on(kind):
            return None
        if not on:
            self._captures.pop(kind).stop()
            self.engine.set_video(kind, None)
            return None
        from jace.ui.capture import Capture
        try:
            cap = Capture(kind, self)
            cap.start()
        except Exception as e:  # noqa: BLE001
            return f"Couldn't turn on your {'camera' if kind == 'camera' else 'screen sharing'}: {e}"
        self._captures[kind] = cap
        self.engine.set_video(kind, cap.source)
        return None

    def start_audio(self):
        if self._sink:
            return
        from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QAudioSource, QMediaDevices

        fmt = QAudioFormat()
        fmt.setSampleRate(voice.SAMPLE_RATE)
        fmt.setChannelCount(1)
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        try:
            self._source = QAudioSource(QMediaDevices.defaultAudioInput(), fmt, self)
            self._mic = self._source.start()
            if self._mic:
                self._mic.readyRead.connect(self._read_mic)
        except Exception:  # noqa: BLE001 - no microphone: you can still listen
            self._mic = None
        self._sink = QAudioSink(QMediaDevices.defaultAudioOutput(), fmt, self)
        self._sink.setBufferSize(voice.FRAME_BYTES * 8)
        self._speaker = self._sink.start()
        self._pump.start()

    def reset(self):
        """Hang up on everyone; stop the microphone, speakers, camera and screen sharing."""
        self._pump.stop()
        for dev in (self._source, self._sink):
            if dev:
                dev.stop()
        self._source = self._sink = self._mic = self._speaker = None
        for cap in self._captures.values():
            cap.stop()
        self._captures.clear()
        if self._engine:
            eng, self._engine = self._engine, None     # the next call or room gets a fresh one
            run_task(eng.close, on_error=lambda m: None)

    def _read_mic(self):
        if self._mic and self._engine:
            data = bytes(self._mic.readAll())
            if data:
                self._engine.push_mic(data)

    def _play(self):
        if not (self._engine and self._speaker and self._sink):
            return
        while self._sink.bytesFree() >= voice.FRAME_BYTES:
            pcm = self._engine.pop_playback()
            if pcm is None:
                break
            self._speaker.write(pcm)


def _video_error(kind):
    return "You can't share your screen here" if kind == "screen" else "You can't turn on your camera here"


class CallManager(QObject):
    changed = Signal()                 # state / peer / muted / video changed
    error = Signal(str)
    incoming = Signal(str)             # peer name, when a friend starts ringing us

    KEY = "call"

    def __init__(self, media: Media, parent=None):
        super().__init__(parent)
        self.media = media
        self.room: RoomManager | None = None          # set by RoomManager (one at a time)
        self.state = "idle"            # idle | calling | ringing | in-call
        self.peer = ""
        self.peer_name = ""
        self.call_id = ""
        self.muted = False
        self.peer_camera = self.peer_screen = False   # they turned on their camera / are sharing their screen
        self._offer_sdp = ""
        self._pending = False                          # a change of ours waits for the answer to the last one
        self._timeout = QTimer(self, singleShot=True, interval=45_000)
        self._timeout.timeout.connect(lambda: self.hang_up("No answer"))
        media.peer_state.connect(self._on_engine_state)

    # -- public
    def status(self) -> dict:
        return {"state": self.state, "peer": self.peer, "peer_name": self.peer_name, "muted": self.muted,
                "camera": self.media.video_on("camera") and self.state == "in-call",
                "sharing": self.media.video_on("screen") and self.state == "in-call",
                "peer_camera": self.peer_camera, "peer_screen": self.peer_screen, "available": voice.available() is None,
                "voice": self.room.status() if self.room else None}

    def call(self, uuid: str, name: str):
        """Start a call; returns why not (also shown in the launcher), or None."""
        why = voice.available() or ("You're already in a call" if self.state != "idle" else None) \
            or ("Leave the voice channel first" if self.room and self.room.channel_id else None)
        if why:
            self.error.emit(why)
            return why
        self._set("calling", uuid, name)
        self.call_id = secrets.token_urlsafe(12)
        call_id = self.call_id
        eng = self.media.engine

        def work():
            sdp = eng.make_offer(self.KEY, social.ice_servers())
            social.call_signal(uuid, call_id, "offer", sdp)

        run_task(work, on_done=lambda _: self._timeout.start(), on_error=self._failed)

    def answer(self):
        if self.state != "ringing":
            return
        peer, call_id, offer = self.peer, self.call_id, self._offer_sdp
        eng = self.media.engine

        def work():
            sdp = eng.make_answer(self.KEY, offer, social.ice_servers(), fresh=True)
            social.call_signal(peer, call_id, "answer", sdp)
            return eng.their_kinds(self.KEY)

        self._set("in-call")
        self.media.start_audio()
        run_task(work, on_done=self._kinds, on_error=self._failed)

    def hang_up(self, reason: str = ""):
        if self.state == "idle":
            return
        peer, call_id = self.peer, self.call_id
        run_task(social.call_signal, peer, call_id, "hangup", on_error=lambda m: None)
        self._end(reason)

    def watch(self):
        """Video only shows in Jace Social: open this call there. The web app takes the call over
        (same call id, the other side doesn't ring) and we drop out once it's connected."""
        if self.state != "in-call":
            return "You're not in a call"
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl(f"{social.base_url()}/app#move_call={self.call_id}&peer={self.peer}"
                                      f"&name={quote(self.peer_name)}"))
        return None

    def toggle_mute(self):
        self.muted = not self.muted
        self.media.engine.muted = self.muted
        self.changed.emit()

    def toggle_video(self, kind: str):
        """Camera ("camera") or screen sharing ("screen") on or off in the call."""
        if self.state != "in-call":
            return "You're not in a call"
        why = self.media.set_video(kind, not self.media.video_on(kind))
        if why:
            self.error.emit(why)
            return why
        self.changed.emit()
        self._renegotiate()
        return None

    # -- live events from Jace Social
    def on_live(self, e: dict):
        kind, call_id = e.get("kind"), e.get("call_id", "")
        eng = self.media.engine
        if kind == "offer":
            def got(sig):
                moving = voice.MOVE_TAG in sig["sdp"]     # someone moving a call between their own devices
                if self.state == "in-call" and call_id == self.call_id and sig["sender"] == self.peer:
                    self._take_over(sig["sdp"])           # ...namely the one they're in with us
                    return
                if moving:
                    return
                if self.state != "idle" or (self.room and self.room.channel_id):   # busy: tell them
                    run_task(social.call_signal, sig["sender"], call_id, "hangup", on_error=lambda m: None)
                    return
                self.call_id, self._offer_sdp = call_id, sig["sdp"]
                self._set("ringing", sig["sender"], sig.get("name") or e.get("name", ""))
                self._timeout.start()
                self.incoming.emit(self.peer_name)
            run_task(social.read_call_signal, e["id"], on_done=got, on_error=lambda m: None)
        elif call_id != self.call_id:
            return
        elif kind == "answer" and self.state == "calling":
            def go():
                eng.set_answer(self.KEY, social.read_call_signal(e["id"])["sdp"])
                return eng.their_kinds(self.KEY)
            self._timeout.stop()
            self._set("in-call")
            self.media.start_audio()
            run_task(go, on_done=self._kinds, on_error=self._failed)
        elif kind == "answer" and self.state == "in-call":
            self._end("Moved the call to Jace Social")    # one of our other devices took the call over
        elif kind == "renegotiate" and self.state == "in-call":
            # they turned their camera or screen on or off (or answer a change of ours, see reanswer)
            def again():
                sdp = social.read_call_signal(e["id"])["sdp"]
                try:
                    answer = eng.make_answer(self.KEY, sdp, social.ice_servers())
                except voice.Busy:
                    return None                           # our offer is out: they answer it, then send theirs again
                social.call_signal(self.peer, call_id, "reanswer", answer)
                return eng.their_kinds(self.KEY)
            run_task(again, on_done=self._kinds, on_error=lambda m: None)
        elif kind == "reanswer" and self.state == "in-call":
            def done():
                eng.set_answer(self.KEY, social.read_call_signal(e["id"])["sdp"])
                return eng.their_kinds(self.KEY)

            def after(kinds):
                self._kinds(kinds)
                if self._pending:
                    self._pending = False
                    self._renegotiate()
            run_task(done, on_done=after, on_error=lambda m: None)
        elif kind == "hangup":
            self._end(f"{self.peer_name} hung up" if self.state == "in-call" else f"{self.peer_name} didn't pick up"
                      if self.state == "calling" else "")

    # -- internals
    def _renegotiate(self):
        """Tell them about our camera / screen (a new offer; "reanswer" comes back)."""
        peer, call_id, eng = self.peer, self.call_id, self.media.engine

        def work():
            try:
                sdp = eng.make_offer(self.KEY, social.ice_servers())
            except voice.Busy:
                return False
            social.call_signal(peer, call_id, "renegotiate", sdp)
            return True

        def done(sent):
            if not sent:
                self._pending = True                      # after the answer to the one that's out
        run_task(work, on_done=done, on_error=lambda m: self.error.emit(m))

    def _kinds(self, kinds):
        if kinds is None or self.state != "in-call":
            return
        cam, screen = "camera" in kinds, "screen" in kinds
        if (cam, screen) != (self.peer_camera, self.peer_screen):
            self.peer_camera, self.peer_screen = cam, screen
            self.changed.emit()

    def _take_over(self, offer_sdp: str):
        """The other side moved the call to another device: answer it there instead (new connection)."""
        peer, call_id, eng = self.peer, self.call_id, self.media.engine
        self.peer_camera = self.peer_screen = False

        def work():
            sdp = eng.make_answer(self.KEY, offer_sdp, social.ice_servers(), fresh=True)
            social.call_signal(peer, call_id, "answer", sdp)
            return eng.their_kinds(self.KEY)

        run_task(work, on_done=lambda k: call_id == self.call_id and self._kinds(k), on_error=self._failed)

    def _on_engine_state(self, key: str, s: str):
        if key == self.KEY and s == "failed" and self.state != "idle":
            self._end("Couldn't connect the call")

    def _failed(self, msg: str):
        self._end(msg)

    def _set(self, state, peer=None, name=None):
        self.state = state
        if peer is not None:
            self.peer, self.peer_name = peer, name or ""
        self.changed.emit()

    def _end(self, reason=""):
        self._timeout.stop()
        self.media.reset()
        self.state, self.peer, self.peer_name, self.call_id, self._offer_sdp = "idle", "", "", "", ""
        self.muted = self.peer_camera = self.peer_screen = self._pending = False
        self.changed.emit()
        if reason:
            self.error.emit(reason)


class RoomManager(QObject):
    """A server voice channel or a group chat's call: everyone connects to everyone (like the
    web app, see server/lib/voice.ts in jace-social). Peers are keyed by their uuid."""
    changed = Signal()
    error = Signal(str)

    def __init__(self, media: Media, calls: CallManager, parent=None):
        super().__init__(parent)
        self.media = media
        self.calls = calls
        calls.room = self
        self.channel_id = ""
        self.channel_name = ""
        self.server_id = ""
        self.participants: list[dict] = []
        self.muted = self.deafened = False
        self.can_video = True
        self.connecting = False
        self.me = ""
        self._ice: list[dict] = []
        self._pending: set[str] = set()                # peers with a change waiting for their answer
        self._beat = QTimer(self, interval=20_000)
        self._beat.timeout.connect(lambda: self._send_state({}))
        media.peer_state.connect(self._on_engine_state)

    # -- public
    def status(self) -> dict | None:
        if not self.channel_id:
            return None
        eng = self.media.engine
        people = []
        for p in self.participants:
            kinds = eng.their_kinds(p["uuid"]) if p["uuid"] != self.me else {}
            people.append({"uuid": p["uuid"], "name": (p.get("person") or {}).get("name") or "Someone",
                           "muted": bool(p.get("muted")), "deafened": bool(p.get("deafened")),
                           "camera": "camera" in kinds if p["uuid"] != self.me else self.media.video_on("camera"),
                           "screen": ("screen" in kinds or bool(p.get("streaming"))) if p["uuid"] != self.me
                           else self.media.video_on("screen"),
                           "me": p["uuid"] == self.me})
        return {"channel_id": self.channel_id, "channel_name": self.channel_name, "server_id": self.server_id,
                "connecting": self.connecting, "muted": self.muted, "deafened": self.deafened,
                "camera": self.media.video_on("camera"), "sharing": self.media.video_on("screen"),
                "can_video": self.can_video, "participants": people}

    def join(self, channel_id: str, name: str = "", server_id: str = ""):
        if not re.fullmatch(r"[0-9A-Za-z-]{8,64}", channel_id) or not re.fullmatch(r"[0-9A-Za-z-]{0,64}", server_id):
            return "That isn't a voice channel"
        why = voice.available() or ("Hang up your call first" if self.calls.state != "idle" else None)
        if why:
            self.error.emit(why)
            return why
        if self.channel_id == channel_id:
            return None
        if self.channel_id:
            self.leave()
        s = social.current_session()
        if not s:
            return "Sign in to Jace Social first"
        self.me = s["uuid"]
        self.channel_id, self.channel_name, self.server_id = channel_id, name or "Voice", server_id or ""
        self.connecting = True
        self.participants = []
        self.changed.emit()

        def work():
            return social.ice_servers(), social.voice_room(channel_id, "join")

        def joined(res):
            if self.channel_id != channel_id:
                return
            self._ice, room = res
            self.connecting = False
            self.participants = room.get("participants", [])
            self.can_video = room.get("can_stream", True) is not False
            self.muted = not room.get("can_speak", True)
            self.media.engine.muted = self.muted
            self.media.start_audio()
            self._beat.start()
            self.changed.emit()
            for p in self.participants:                 # the one who joins connects to everyone already here
                if p["uuid"] != self.me:
                    self._offer(p["uuid"])

        def failed(msg):
            if self.channel_id == channel_id:
                self._reset()
                self.error.emit(msg)
        run_task(work, on_done=joined, on_error=failed)
        return None

    def leave(self):
        if not self.channel_id:
            return None
        channel = self.channel_id
        self._reset()
        run_task(social.voice_room, channel, "leave", on_error=lambda m: None)
        return None

    def toggle_mute(self):
        if not self.channel_id:
            return "You're not in a voice channel"
        self.muted = not self.muted
        self.media.engine.muted = self.muted
        self._send_state({"muted": self.muted})
        self.changed.emit()
        return None

    def toggle_deafen(self):
        if not self.channel_id:
            return "You're not in a voice channel"
        self.deafened = not self.deafened
        self.media.engine.deafened = self.deafened
        self._send_state({"deafened": self.deafened})
        self.changed.emit()
        return None

    def toggle_video(self, kind: str):
        if not self.channel_id or self.connecting:
            return "You're not in a voice channel"
        if not self.can_video:
            return _video_error(kind)
        on = not self.media.video_on(kind)
        why = self.media.set_video(kind, on)
        if why:
            self.error.emit(why)
            return why
        if kind == "screen":
            self._send_state({"streaming": on})
        for uuid in self.media.engine.peers:
            self._offer(uuid)
        self.changed.emit()
        return None

    def watch(self):
        """Video only shows in Jace Social: leave here and join the same room there."""
        if not self.channel_id:
            return "You're not in a voice channel"
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        url = (f"{social.base_url()}/app#join_voice={self.channel_id}&server={self.server_id}"
               f"&name={quote(self.channel_name)}")
        self.leave()
        QDesktopServices.openUrl(QUrl(url))
        return None

    # -- live events from Jace Social
    def on_voice(self, e: dict):
        """Who's in a room changed."""
        if not self.channel_id or e.get("channel_id") != self.channel_id or self.connecting:
            return
        channel = self.channel_id

        def got(room):
            if self.channel_id != channel:
                return
            people = room.get("participants", [])
            if not any(p["uuid"] == self.me for p in people):
                self._reset()                               # kicked, or timed out
                self.error.emit("You left the voice channel")
                return
            here = {p["uuid"] for p in people}
            for uuid in list(self.media.engine.peers):
                if uuid not in here:
                    self.media.engine.drop(uuid)
            self.participants = people
            self.changed.emit()
        run_task(social.voice_room, channel, on_done=got, on_error=lambda m: None)

    def on_signal(self, e: dict):
        """An offer or answer from someone in the room."""
        if not self.channel_id or e.get("channel_id") != self.channel_id:
            return
        channel, who, eng = self.channel_id, e.get("from", ""), self.media.engine

        def work():
            sig = social.read_voice_signal(e["id"])
            if sig["kind"] == "offer":
                new = who not in eng.peers
                try:
                    sdp = eng.make_answer(who, sig["sdp"], self._ice)
                except voice.Busy:
                    return None                         # our offer is out: they answer it, then send theirs again
                social.voice_signal(channel, who, "answer", sdp)
                return "offered-new" if new else "answered"
            eng.set_answer(who, sig["sdp"])
            return "got-answer"

        def done(what):
            if self.channel_id != channel:
                return
            if what == "offered-new" and eng.video:
                QTimer.singleShot(300, lambda: self._offer(who))   # their offer had no room for our video
            elif what == "got-answer" and who in self._pending:
                self._pending.discard(who)
                self._offer(who)
            self.changed.emit()                         # their camera / screen may have changed
        run_task(work, on_done=done, on_error=lambda m: None)

    # -- internals
    def _offer(self, uuid: str):
        channel, eng = self.channel_id, self.media.engine

        def work():
            try:
                sdp = eng.make_offer(uuid, self._ice)
            except voice.Busy:
                return False
            social.voice_signal(channel, uuid, "offer", sdp)
            return True

        def done(sent):
            if not sent:
                self._pending.add(uuid)
        run_task(work, on_done=done, on_error=lambda m: None)

    def _on_engine_state(self, key: str, s: str):
        if self.channel_id and key != CallManager.KEY and s == "failed":
            self.media.engine.drop(key)                 # try once more
            self._offer(key)

    def _send_state(self, patch: dict):
        if self.channel_id:
            run_task(social.voice_room, self.channel_id, "state", **patch, on_error=lambda m: self.error.emit(m))

    def _reset(self):
        self._beat.stop()
        self.media.reset()
        self.channel_id = self.channel_name = self.server_id = ""
        self.participants = []
        self.muted = self.deafened = self.connecting = False
        self._pending.clear()
        self.changed.emit()
