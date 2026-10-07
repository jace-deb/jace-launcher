"""Voice calls between friends.

WebRTC (aiortc) runs on its own asyncio thread; the microphone and speakers use
Qt Multimedia on the UI thread. Audio goes straight between the two players, or
through Cloudflare's TURN relay when a direct connection isn't possible. Jace
Social only passes the call setup (offer / answer / hang up) between friends.
"""
from __future__ import annotations

import asyncio
import collections
import fractions
import threading

SAMPLE_RATE = 48000
FRAME = 960                      # 20 ms of mono audio
FRAME_BYTES = FRAME * 2          # 16-bit samples


def available() -> str | None:
    """None if calls work here, else why not."""
    try:
        import aiortc  # noqa: F401
        from PySide6.QtMultimedia import QAudioSource  # noqa: F401
    except Exception as e:  # noqa: BLE001
        return f"Voice calls aren't available in this build ({e.__class__.__name__})."
    return None


class Engine:
    """One WebRTC call at a time. Every public method is safe to call from any thread;
    the blocking ones (offer/answer) should run off the UI thread."""

    def __init__(self, on_state):
        self.on_state = on_state                  # called from the asyncio thread: "connected" / "failed" / "closed"
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, name="voice", daemon=True).start()
        self.pc = None
        self.mic_queue: asyncio.Queue | None = None
        self.playback = collections.deque(maxlen=50)   # 1 s of decoded audio for the speakers
        self.muted = False

    def _run(self, coro, timeout=40):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)

    # -- call setup (blocking)
    def make_offer(self, ice: list[dict]) -> str:
        return self._run(self._offer(ice))

    def make_answer(self, offer_sdp: str, ice: list[dict]) -> str:
        return self._run(self._answer(offer_sdp, ice))

    def set_answer(self, answer_sdp: str):
        self._run(self._set_answer(answer_sdp))

    def close(self):
        try:
            self._run(self._close(), timeout=10)
        except Exception:  # noqa: BLE001 - closing is best-effort
            pass

    # -- audio in/out (UI thread)
    def push_mic(self, pcm: bytes):
        """16-bit mono 48 kHz PCM from the microphone, any length."""
        if self.mic_queue is not None:
            self.loop.call_soon_threadsafe(self._feed, pcm)

    def pop_playback(self) -> bytes | None:
        try:
            return self.playback.popleft()
        except IndexError:
            return None

    # -- asyncio side
    async def _new_pc(self, ice):
        from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection

        await self._close()
        servers = [RTCIceServer(urls=s["urls"], username=s.get("username"), credential=s.get("credential")) for s in ice]
        pc = RTCPeerConnection(RTCConfiguration(iceServers=servers))
        self.pc = pc
        self.mic_queue = asyncio.Queue(maxsize=25)
        self._pending = bytearray()
        pc.addTrack(_MicTrack(self))

        @pc.on("track")
        def on_track(track):
            if track.kind == "audio":
                asyncio.ensure_future(self._play(track))

        @pc.on("connectionstatechange")
        async def on_change():
            if pc is not self.pc:
                return
            if pc.connectionState == "connected":
                self.on_state("connected")
            elif pc.connectionState in ("failed", "closed"):
                self.on_state(pc.connectionState)
        return pc

    async def _offer(self, ice):
        pc = await self._new_pc(ice)
        await pc.setLocalDescription(await pc.createOffer())     # waits for ICE gathering
        return pc.localDescription.sdp

    async def _answer(self, offer_sdp, ice):
        from aiortc import RTCSessionDescription

        pc = await self._new_pc(ice)
        await pc.setRemoteDescription(RTCSessionDescription(offer_sdp, "offer"))
        await pc.setLocalDescription(await pc.createAnswer())
        return pc.localDescription.sdp

    async def _set_answer(self, sdp):
        from aiortc import RTCSessionDescription

        if self.pc:
            await self.pc.setRemoteDescription(RTCSessionDescription(sdp, "answer"))

    async def _close(self):
        pc, self.pc = self.pc, None
        self.mic_queue = None
        self.playback.clear()
        if pc:
            await pc.close()

    def _feed(self, pcm: bytes):
        q = self.mic_queue
        if q is None:
            return
        self._pending += pcm
        while len(self._pending) >= FRAME_BYTES:
            chunk = bytes(self._pending[:FRAME_BYTES])
            del self._pending[:FRAME_BYTES]
            if q.full():                       # fall behind? drop the oldest audio, keep latency low
                q.get_nowait()
            q.put_nowait(chunk)

    async def _play(self, track):
        import av

        resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
        try:
            while True:
                frame = await track.recv()
                for out in resampler.resample(frame):
                    self.playback.append(bytes(out.planes[0])[: out.samples * 2])
        except Exception:  # noqa: BLE001 - track ended
            return


def _make_track_base():
    from aiortc import MediaStreamTrack
    return MediaStreamTrack


class _MicTrack(_make_track_base() if available() is None else object):
    """Sends the microphone (or silence while muted) as 20 ms frames."""
    kind = "audio"

    def __init__(self, engine: Engine):
        super().__init__()
        self.engine = engine
        self.pts = 0

    async def recv(self):
        import av

        q = self.engine.mic_queue
        try:
            pcm = await asyncio.wait_for(q.get(), 0.1) if q else None
        except asyncio.TimeoutError:
            pcm = None                          # no microphone audio: send silence so the call stays up
        if pcm is None or self.engine.muted:
            pcm = bytes(FRAME_BYTES)
        frame = av.AudioFrame(format="s16", layout="mono", samples=FRAME)
        frame.planes[0].update(pcm)
        frame.sample_rate = SAMPLE_RATE
        frame.pts = self.pts
        frame.time_base = fractions.Fraction(1, SAMPLE_RATE)
        self.pts += FRAME
        return frame
