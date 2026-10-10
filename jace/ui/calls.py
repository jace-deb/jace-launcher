"""Voice call state for the launcher UI and for the Jace Social mod (through the link server)."""
from __future__ import annotations

import secrets
from urllib.parse import quote

from PySide6.QtCore import QObject, QTimer, Signal

from jace import social, voice
from jace.ui.common import run_task


class CallManager(QObject):
    changed = Signal()                 # state / peer / muted changed
    error = Signal(str)
    incoming = Signal(str)             # peer name, when a friend starts ringing us

    def __init__(self, parent=None):
        super().__init__(parent)
        self.state = "idle"            # idle | calling | ringing | in-call
        self.peer = ""
        self.peer_name = ""
        self.call_id = ""
        self.muted = False
        self.peer_camera = self.peer_screen = False   # they turned on their camera / are sharing their screen
        self._offer_sdp = ""
        self._engine: voice.Engine | None = None
        self._source = self._sink = self._mic = self._speaker = None
        self._timeout = QTimer(self, singleShot=True, interval=45_000)
        self._timeout.timeout.connect(lambda: self.hang_up("No answer"))
        self._pump = QTimer(self, interval=20)
        self._pump.timeout.connect(self._play)
        self._engine_state.connect(self._on_engine_state)

    _engine_state = Signal(str)

    # -- public
    def status(self) -> dict:
        return {"state": self.state, "peer": self.peer, "peer_name": self.peer_name, "muted": self.muted,
                "peer_camera": self.peer_camera, "peer_screen": self.peer_screen, "available": voice.available() is None}

    def call(self, uuid: str, name: str):
        """Start a call; returns why not (also shown in the launcher), or None."""
        why = voice.available() or ("You're already in a call" if self.state != "idle" else None)
        if why:
            self.error.emit(why)
            return why
        self._set("calling", uuid, name)
        self.call_id = secrets.token_urlsafe(12)
        call_id = self.call_id

        def work():
            sdp = self._get_engine().make_offer(social.ice_servers())
            social.call_signal(uuid, call_id, "offer", sdp)

        run_task(work, on_done=lambda _: self._timeout.start(), on_error=self._failed)

    def answer(self):
        if self.state != "ringing":
            return
        peer, call_id, offer = self.peer, self.call_id, self._offer_sdp

        def work():
            sdp = self._get_engine().make_answer(_strip_tags(offer), social.ice_servers())
            social.call_signal(peer, call_id, "answer", sdp)

        self._set("in-call")
        self._start_audio()
        run_task(work, on_error=self._failed)

    def hang_up(self, reason: str = ""):
        if self.state == "idle":
            return
        peer, call_id = self.peer, self.call_id
        run_task(social.call_signal, peer, call_id, "hangup", on_error=lambda m: None)
        self._end(reason)

    def watch(self):
        """Video only works in Jace Social: open this call there. The web app takes the call over
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
        if self._engine:
            self._engine.muted = self.muted
        self.changed.emit()

    # -- live events from Jace Social
    def on_live(self, e: dict):
        kind, call_id = e.get("kind"), e.get("call_id", "")
        if kind == "offer":
            def got(sig):
                moving = MOVE_TAG in sig["sdp"]           # someone moving a call between their own devices
                if self.state == "in-call" and call_id == self.call_id and sig["sender"] == self.peer:
                    self._take_over(sig["sdp"])           # ...namely the one they're in with us
                    return
                if moving:
                    return
                if self.state != "idle":                  # busy: tell them
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
                self._get_engine().set_answer(_strip_tags(social.read_call_signal(e["id"])["sdp"]))
            self._timeout.stop()
            self._set("in-call")
            self._start_audio()
            run_task(go, on_error=self._failed)
        elif kind == "answer" and self.state == "in-call":
            self._end("Moved the call to Jace Social")    # one of our other devices took the call over
        elif kind == "renegotiate" and self.state == "in-call":
            def again():
                sdp = social.read_call_signal(e["id"])["sdp"]
                kinds = _stream_kinds(sdp)
                answer = self._get_engine().reanswer(_strip_tags(sdp))
                social.call_signal(self.peer, call_id, "reanswer", answer)
                return kinds

            def done(kinds):
                if call_id == self.call_id and (self.peer_camera, self.peer_screen) != ("camera" in kinds, "screen" in kinds):
                    self.peer_camera, self.peer_screen = "camera" in kinds, "screen" in kinds
                    self.changed.emit()
            run_task(again, on_done=done, on_error=lambda m: None)
        elif kind == "hangup":
            self._end(f"{self.peer_name} hung up" if self.state == "in-call" else f"{self.peer_name} didn't pick up"
                      if self.state == "calling" else "")

    # -- internals
    def _take_over(self, offer_sdp: str):
        """The other side moved the call to another device: answer it there instead (new connection)."""
        peer, call_id = self.peer, self.call_id
        self.peer_camera = self.peer_screen = False

        def work():
            kinds = _stream_kinds(offer_sdp)
            sdp = self._get_engine().make_answer(_strip_tags(offer_sdp), social.ice_servers())
            social.call_signal(peer, call_id, "answer", sdp)
            return kinds

        def done(kinds):
            if call_id == self.call_id:
                self.peer_camera, self.peer_screen = "camera" in kinds, "screen" in kinds
                self.changed.emit()
        run_task(work, on_done=done, on_error=self._failed)

    def _get_engine(self) -> voice.Engine:
        if self._engine is None:
            self._engine = voice.Engine(self._engine_state.emit)
        self._engine.muted = self.muted
        return self._engine

    def _on_engine_state(self, s: str):
        if s == "failed" and self.state != "idle":
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
        self._stop_audio()
        if self._engine:
            eng = self._engine
            run_task(eng.close, on_error=lambda m: None)
        self.state, self.peer, self.peer_name, self.call_id, self._offer_sdp = "idle", "", "", "", ""
        self.muted = self.peer_camera = self.peer_screen = False
        self.changed.emit()
        if reason:
            self.error.emit(reason)

    def _start_audio(self):
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

    def _stop_audio(self):
        self._pump.stop()
        for dev in (self._source, self._sink):
            if dev:
                dev.stop()
        self._source = self._sink = self._mic = self._speaker = None

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


# Jace Social tags its call descriptions (see server/lib/media.ts): which video is the camera and
# which the screen share, and whether an offer moves an existing call to another device.
STREAMS_TAG = "a=x-jace-streams:"
MOVE_TAG = "a=x-jace-move"


def _stream_kinds(sdp: str) -> set[str]:
    kinds = set()
    for line in sdp.splitlines():
        if line.startswith(STREAMS_TAG):
            kinds |= {part.split("=")[0] for part in line[len(STREAMS_TAG):].split(",") if "=" in part}
    return kinds


def _strip_tags(sdp: str) -> str:
    return "".join(line for line in sdp.splitlines(keepends=True) if not line.startswith("a=x-jace-"))
