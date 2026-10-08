"""Voice call state for the launcher UI and for the Jace Social mod (through the link server)."""
from __future__ import annotations

import secrets

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
                "available": voice.available() is None}

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
            sdp = self._get_engine().make_answer(offer, social.ice_servers())
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

    def toggle_mute(self):
        self.muted = not self.muted
        if self._engine:
            self._engine.muted = self.muted
        self.changed.emit()

    # -- live events from Jace Social
    def on_live(self, e: dict):
        kind, call_id = e.get("kind"), e.get("call_id", "")
        if kind == "offer":
            if self.state != "idle":                    # busy: tell them
                run_task(social.call_signal, e.get("from", ""), call_id, "hangup", on_error=lambda m: None)
                return

            def got(sig):
                if self.state != "idle":
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
                self._get_engine().set_answer(social.read_call_signal(e["id"])["sdp"])
            self._timeout.stop()
            self._set("in-call")
            self._start_audio()
            run_task(go, on_error=self._failed)
        elif kind == "hangup":
            self._end(f"{self.peer_name} hung up" if self.state == "in-call" else f"{self.peer_name} didn't pick up"
                      if self.state == "calling" else "")

    # -- internals
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
        self.muted = False
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
