"""Voice calls and voice rooms (server voice channels and group calls), with camera and
screen sharing.

WebRTC (aiortc) runs on its own asyncio thread; the microphone, speakers, camera and screen
capture use Qt Multimedia on the UI thread. Each person we talk to has their own connection
(a "peer", keyed by any string: "call" for a direct call, their uuid in a room). Media goes
straight between players, or through Cloudflare's TURN relay when a direct connection isn't
possible. Jace Social only passes the connection setup between them.

Descriptions we send carry Jace Social's tags (see server/lib/media.ts in jace-social):
which of our streams is the camera and which the screen, and "noyield": aiortc can't take
back an offer, so when both sides change something at once, the other side gives way.
We don't show other people's video (Jace Social does: see "Watch"), so we decline it.
"""
from __future__ import annotations

import array
import asyncio
import collections
import fractions
import threading
import time
import uuid

SAMPLE_RATE = 48000
FRAME = 960                      # 20 ms of mono audio
FRAME_BYTES = FRAME * 2          # 16-bit samples

STREAMS_TAG = "a=x-jace-streams:"
MOVE_TAG = "a=x-jace-move"
NO_YIELD_TAG = "a=x-jace-noyield"


def available() -> str | None:
    """None if calls work here, else why not."""
    try:
        import aiortc  # noqa: F401
        from PySide6.QtMultimedia import QAudioSource  # noqa: F401
    except Exception as e:  # noqa: BLE001
        return f"Voice calls aren't available in this build ({e.__class__.__name__})."
    return None


def stream_kinds(sdp: str) -> dict[str, str]:
    """{"camera": stream id, "screen": stream id} from the other side's description."""
    kinds = {}
    for line in sdp.splitlines():
        if line.startswith(STREAMS_TAG):
            for part in line[len(STREAMS_TAG):].split(","):
                k, _, v = part.partition("=")
                if k in ("camera", "screen") and v.strip():
                    kinds[k] = v.strip()
    return kinds


def strip_tags(sdp: str) -> str:
    return "".join(line for line in sdp.splitlines(keepends=True) if not line.startswith("a=x-jace-"))


class FrameSource:
    """The newest camera or screen picture, handed from the UI thread to the encoder:
    (width, height, RGBA bytes). Width is a multiple of 16 so rows need no padding."""

    def __init__(self, fps: int):
        self.fps = fps
        self.latest: tuple[int, int, bytes] | None = None


class _Peer:
    def __init__(self, pc):
        self.pc = pc
        self.playback = collections.deque(maxlen=25)   # 0.5 s of their decoded audio
        self.kinds: dict[str, str] = {}                 # their camera / screen stream ids
        self.lock = asyncio.Lock()                      # one description at a time
        self.listening = False


class Engine:
    """Every public method is safe to call from any thread; the blocking ones (offer/answer)
    should run off the UI thread."""

    def __init__(self, on_state):
        self.on_state = on_state            # on_state(key, "connected" | "failed" | "closed"), from the asyncio thread
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, name="voice", daemon=True).start()
        self.peers: dict[str, _Peer] = {}
        self.mic_queue: asyncio.Queue | None = None
        self._pending = bytearray()
        self._mic = None
        self._relay = None
        self.muted = False
        self.deafened = False
        # our camera / screen: {"track": the track every peer gets a copy of, "stream": its stream id}
        self.video: dict[str, dict] = {}

    def _run(self, coro, timeout=40):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)

    # -- connection setup (blocking)
    def make_offer(self, key: str, ice: list[dict], extra: str = "") -> str:
        """An offer to `key` (a new connection, or our changes on an existing one).
        Raises Busy while an earlier offer to them still waits for its answer."""
        return self._run(self._offer(key, ice, extra))

    def make_answer(self, key: str, offer_sdp: str, ice: list[dict], fresh: bool = False) -> str:
        """Answer their offer (a new connection if there's none, or `fresh` to start over).
        Raises Busy if our own offer is out: they give way to it and send theirs again."""
        return self._run(self._answer(key, offer_sdp, ice, fresh))

    def set_answer(self, key: str, answer_sdp: str):
        self._run(self._set_answer(key, answer_sdp))

    def their_kinds(self, key: str) -> dict[str, str]:
        p = self.peers.get(key)
        return dict(p.kinds) if p else {}

    def drop(self, key: str):
        try:
            self._run(self._drop(key), timeout=10)
        except Exception:  # noqa: BLE001 - best-effort
            pass

    def close(self):
        """Hang up on everyone, stop sending video and end the engine's thread."""
        try:
            self._run(self._close(), timeout=10)
        except Exception:  # noqa: BLE001 - closing is best-effort
            pass
        self.loop.call_soon_threadsafe(self.loop.stop)

    # -- camera / screen
    def set_video(self, kind: str, source: FrameSource | None):
        """Start ("camera" / "screen") or stop (source None) sending video to everyone.
        Then send each peer a new offer (make_offer) so they hear about it."""
        self._run(self._set_video(kind, source), timeout=10)

    def sending(self, kind: str) -> bool:
        return kind in self.video

    # -- audio in/out (UI thread)
    def push_mic(self, pcm: bytes):
        """16-bit mono 48 kHz PCM from the microphone, any length."""
        if self.mic_queue is not None:
            self.loop.call_soon_threadsafe(self._feed, pcm)

    def pop_playback(self) -> bytes | None:
        """The next 20 ms for the speakers: everyone's audio mixed (None if nobody said anything)."""
        frames = []
        for p in list(self.peers.values()):
            try:
                frames.append(p.playback.popleft())
            except IndexError:
                pass
        if not frames or self.deafened:
            return None
        if len(frames) == 1:
            return frames[0]
        mix = array.array("h", frames[0])
        for f in frames[1:]:
            for i, v in enumerate(array.array("h", f)):
                s = mix[i] + v
                mix[i] = 32767 if s > 32767 else -32768 if s < -32768 else s
        return mix.tobytes()

    # -- asyncio side
    def _tag(self, sdp: str, extra: str = "") -> str:
        sdp = sdp.rstrip("\r\n") + "\r\n" + NO_YIELD_TAG + "\r\n"
        parts = [f"{k}={v['stream']}" for k, v in self.video.items()]
        if parts:
            sdp += STREAMS_TAG + ",".join(parts) + "\r\n"
        return sdp + extra

    async def _peer(self, key: str, ice) -> _Peer:
        if key in self.peers:
            return self.peers[key]
        from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection
        from aiortc.contrib.media import MediaRelay

        if self.mic_queue is None:
            self.mic_queue = asyncio.Queue(maxsize=25)
            self._pending = bytearray()
            self._mic = _MicTrack(self)
            self._relay = MediaRelay()
        servers = [RTCIceServer(urls=s["urls"], username=s.get("username"), credential=s.get("credential")) for s in ice or []]
        pc = RTCPeerConnection(RTCConfiguration(iceServers=servers))
        peer = _Peer(pc)
        self.peers[key] = peer
        pc.addTrack(self._relay.subscribe(self._mic, buffered=False))
        for v in self.video.values():
            self._send_video(pc, v)

        @pc.on("track")
        def on_track(track):
            if track.kind == "audio" and not peer.listening:
                peer.listening = True                   # their voice (not their screen's sound)
                asyncio.ensure_future(self._play(peer, track))

        @pc.on("connectionstatechange")
        async def on_change():
            if self.peers.get(key) is peer and pc.connectionState in ("connected", "failed", "closed"):
                self.on_state(key, pc.connectionState)
        return peer

    def _send_video(self, pc, v: dict):
        sender = pc.addTrack(self._relay.subscribe(v["track"], buffered=False))
        sender._stream_id = v["stream"]                 # its own stream, so they can tell camera from screen

    @staticmethod
    def _decline_unused(pc):
        """Say no to what we don't send on (their video, their screen's sound): we can't show
        it, so it isn't sent at all. Our microphone always has a track, so voice stays."""
        for t in pc.getTransceivers():
            if t.sender.track is None:
                t.direction = "inactive"

    async def _offer(self, key, ice, extra):
        peer = await self._peer(key, ice)
        async with peer.lock:
            pc = peer.pc
            if pc.signalingState != "stable":
                raise Busy("an offer is already out")
            self._decline_unused(pc)
            await pc.setLocalDescription(await _create_offer(pc))   # waits for ICE gathering
            return self._tag(pc.localDescription.sdp, extra)

    async def _answer(self, key, offer_sdp, ice, fresh):
        from aiortc import RTCSessionDescription

        if fresh and key in self.peers:
            await self._drop(key)
        peer = await self._peer(key, ice)
        async with peer.lock:
            pc = peer.pc
            if pc.signalingState == "have-local-offer":
                raise Busy("both sides changed something at once")
            peer.kinds = stream_kinds(offer_sdp)
            await pc.setRemoteDescription(RTCSessionDescription(strip_tags(offer_sdp), "offer"))
            self._decline_unused(pc)
            await pc.setLocalDescription(await pc.createAnswer())
            return self._tag(pc.localDescription.sdp)

    async def _set_answer(self, key, sdp):
        from aiortc import RTCSessionDescription

        peer = self.peers.get(key)
        if peer and peer.pc.signalingState == "have-local-offer":
            peer.kinds = stream_kinds(sdp)
            await peer.pc.setRemoteDescription(RTCSessionDescription(strip_tags(sdp), "answer"))

    async def _set_video(self, kind, source):
        old = self.video.pop(kind, None)
        if old:
            old["track"].stop()
            for p in self.peers.values():
                for t in p.pc.getTransceivers():
                    if t.sender.track is not None and t.sender._stream_id == old["stream"]:
                        t.sender.replaceTrack(None)
                        t.direction = "inactive"
        if source is not None:
            v = {"track": _VideoTrack(source), "stream": f"{kind}-{uuid.uuid4()}"}
            self.video[kind] = v
            for p in self.peers.values():
                self._send_video(p.pc, v)

    async def _drop(self, key):
        peer = self.peers.pop(key, None)
        if peer:
            await peer.pc.close()

    async def _close(self):
        for key in list(self.peers):
            await self._drop(key)
        for v in self.video.values():
            v["track"].stop()
        self.video.clear()
        self.mic_queue = None
        if self._mic:
            self._mic.stop()
        self._mic = self._relay = None

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

    async def _play(self, peer: _Peer, track):
        import av

        resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
        buf = bytearray()
        try:
            while True:
                frame = await track.recv()
                for out in resampler.resample(frame):
                    buf += bytes(out.planes[0])[: out.samples * 2]
                while len(buf) >= FRAME_BYTES:          # 20 ms pieces, so everyone's audio lines up for mixing
                    peer.playback.append(bytes(buf[:FRAME_BYTES]))
                    del buf[:FRAME_BYTES]
        except Exception:  # noqa: BLE001 - track ended
            return


_offer_lock: asyncio.Lock | None = None


async def _create_offer(pc):
    """pc.createOffer(), keeping the header extension ids already agreed on. aiortc numbers
    them its own way in every offer; after answering a browser (which numbered them first)
    that changes ids mid-call, and the browser rejects the offer."""
    global _offer_lock
    import aiortc.rtcpeerconnection as rpc
    from aiortc.rtcrtpparameters import RTCRtpHeaderExtensionParameters

    agreed = {x.uri: x.id for t in pc.getTransceivers() if t.currentDirection for x in (t._headerExtensions or [])}
    if not agreed:
        return await pc.createOffer()
    if _offer_lock is None:
        _offer_lock = asyncio.Lock()
    async with _offer_lock:
        default = rpc.HEADER_EXTENSIONS
        free = (i for i in range(1, 15) if i not in agreed.values())
        ids = {**{x.uri: next(free) for exts in default.values() for x in exts if x.uri not in agreed}, **agreed}
        rpc.HEADER_EXTENSIONS = {kind: [RTCRtpHeaderExtensionParameters(id=ids[x.uri], uri=x.uri) for x in exts]
                                 for kind, exts in default.items()}
        try:
            task = asyncio.ensure_future(pc.createOffer())
            await asyncio.sleep(0)          # createOffer reads HEADER_EXTENSIONS before its first await
        finally:
            rpc.HEADER_EXTENSIONS = default
        return await task


class Busy(RuntimeError):
    """An offer is already out on this connection; try again after its answer."""


def _track_base(kind):
    if available() is not None:
        return object
    from aiortc import MediaStreamTrack
    return MediaStreamTrack


class _MicTrack(_track_base("audio")):
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
        if pcm is None or self.engine.muted or self.engine.deafened:
            pcm = bytes(FRAME_BYTES)
        frame = av.AudioFrame(format="s16", layout="mono", samples=FRAME)
        frame.planes[0].update(pcm)
        frame.sample_rate = SAMPLE_RATE
        frame.pts = self.pts
        frame.time_base = fractions.Fraction(1, SAMPLE_RATE)
        self.pts += FRAME
        return frame


class _VideoTrack(_track_base("video")):
    """Sends the newest picture from a FrameSource, `fps` times a second."""
    kind = "video"

    def __init__(self, source: FrameSource):
        super().__init__()
        self.source = source
        self._start = None
        self._n = 0

    async def recv(self):
        import av

        if self._start is None:
            self._start = time.monotonic()
        self._n += 1
        wait = self._start + self._n / self.source.fps - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        latest = self.source.latest
        w, h, data = latest if latest else (320, 176, bytes(320 * 176 * 4))     # nothing yet: black
        frame = av.VideoFrame(w, h, "rgba")
        frame.planes[0].update(data)
        frame = frame.reformat(format="yuv420p")
        frame.pts = int(self._n * 90000 / self.source.fps)          # 90 kHz video clock
        frame.time_base = fractions.Fraction(1, 90000)
        return frame
