"""Local link between Jace Launcher and the Jace Social mod in a running game.

The launcher listens on 127.0.0.1 (random port) and starts games with
-Djacelauncher.link=PORT:TOKEN. The mod uses it for voice calls:
  GET  /call            -> {state, peer, peer_name, muted, peer_camera, peer_screen}
  POST /call            {uuid, name}  start a call
  POST /call/answer | /call/hangup | /call/mute
  POST /call/watch      open the call in Jace Social (to see their camera / screen)
  POST /call/camera | /call/screen     turn your camera / screen sharing on or off
  POST /voice/join      {channel_id, name, server_id}  join a voice channel or group call
  POST /voice/leave | /voice/mute | /voice/deafen | /voice/camera | /voice/screen | /voice/watch
GET /call also has "voice": the voice room you're in (or null).
Every request needs the X-Jace-Token header, so other programs can't use it.
"""
from __future__ import annotations

import hmac
import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PySide6.QtCore import QObject, Signal, Slot


class _MainThread(QObject):
    """Runs a function on the UI thread and hands the result back to the server thread."""
    run = Signal(object)

    def __init__(self):
        super().__init__()
        self.run.connect(self._run)

    @Slot(object)
    def _run(self, job):
        fn, box, done = job
        try:
            box["result"] = fn()
        except Exception as e:  # noqa: BLE001
            box["error"] = str(e)
        done.set()

    def call(self, fn, timeout=10):
        box, done = {}, threading.Event()
        self.run.emit((fn, box, done))
        if not done.wait(timeout):
            raise TimeoutError("Jace Launcher is busy")
        if "error" in box:
            raise RuntimeError(box["error"])
        return box.get("result")


class LauncherLink:
    def __init__(self, calls, rooms):
        self.calls = calls
        self.rooms = rooms
        self.token = secrets.token_urlsafe(24)
        self.main = _MainThread()
        link = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _reply(self, code, data):
                body = json.dumps(data).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _ok(self):
                if not hmac.compare_digest(self.headers.get("X-Jace-Token", ""), link.token):
                    self._reply(403, {"error": "Wrong token"})
                    return False
                return True

            def do_GET(self):
                if not self._ok():
                    return
                if self.path == "/call":
                    self._reply(200, link.main.call(link.calls.status))
                else:
                    self._reply(404, {"error": "Not found"})

            def do_POST(self):
                if not self._ok():
                    return
                try:
                    n = min(int(self.headers.get("Content-Length") or 0), 10_000)
                    b = json.loads(self.rfile.read(n) or b"{}")
                except ValueError:
                    b = {}
                c, r = link.calls, link.rooms
                actions = {
                    "/call/camera": lambda: c.toggle_video("camera"),
                    "/call/screen": lambda: c.toggle_video("screen"),
                    "/voice/join": lambda: r.join(str(b.get("channel_id", "")), str(b.get("name", "")), str(b.get("server_id", ""))),
                    "/voice/leave": r.leave,
                    "/voice/mute": r.toggle_mute,
                    "/voice/deafen": r.toggle_deafen,
                    "/voice/camera": lambda: r.toggle_video("camera"),
                    "/voice/screen": lambda: r.toggle_video("screen"),
                    "/voice/watch": r.watch,
                    "/call": lambda: c.call(str(b.get("uuid", "")), str(b.get("name", ""))),
                    "/call/answer": c.answer,
                    "/call/hangup": c.hang_up,
                    "/call/mute": c.toggle_mute,
                    "/call/watch": c.watch,
                }
                if self.path not in actions:
                    self._reply(404, {"error": "Not found"})
                    return
                try:
                    problem = link.main.call(actions[self.path])
                    if isinstance(problem, str):          # e.g. "You're already in a call"
                        self._reply(400, {"error": problem})
                    else:
                        self._reply(200, link.main.call(c.status))
                except Exception as e:  # noqa: BLE001
                    self._reply(500, {"error": str(e)})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, name="launcher-link", daemon=True).start()

    @property
    def jvm_arg(self) -> str:
        return f"-Djacelauncher.link={self.server.server_address[1]}:{self.token}"


_link: LauncherLink | None = None


def start(calls, rooms) -> LauncherLink:
    global _link
    if _link is None:
        _link = LauncherLink(calls, rooms)
    return _link


def jvm_args() -> list[str]:
    """Extra JVM arguments for games started by this launcher."""
    return [_link.jvm_arg] if _link else []
