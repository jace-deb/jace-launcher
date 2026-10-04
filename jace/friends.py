"""Friends list: stored locally, keyed by Minecraft UUID so name changes are followed.

There's no Jace Launcher server, so "online" means: the friend's saved server
answers a status ping and lists them among its players. Many servers share a
sample of online player names in that ping; big networks often hide it.
"""
import json
import socket
import struct
import time

from jace.accounts import AuthError, skin_for_uuid
from jace.config import DATA_DIR, read_json, write_json
from jace.net import get_json, session

FRIENDS_FILE = DATA_DIR / "friends.json"


def load() -> list[dict]:
    return read_json(FRIENDS_FILE, [])


def save(friends: list[dict]):
    write_json(FRIENDS_FILE, friends)


def lookup(name: str) -> dict:
    """Minecraft username -> {uuid, name}. Raises AuthError if there's no such player."""
    r = session.get(f"https://api.mojang.com/users/profiles/minecraft/{name}", timeout=20)
    if r.status_code != 200:
        raise AuthError(f"No Minecraft player called '{name}'")
    d = r.json()
    return {"uuid": d["id"], "name": d["name"]}


def current_name(uuid: str) -> str | None:
    r = session.get(f"https://sessionserver.mojang.com/session/minecraft/profile/{uuid}", timeout=20)
    return r.json().get("name") if r.status_code == 200 else None


def add(name: str) -> dict:
    found = lookup(name.strip())
    friends = load()
    if any(f["uuid"] == found["uuid"] for f in friends):
        raise AuthError(f"{found['name']} is already on your friends list")
    friend = {**found, "nickname": "", "server": "", "added": time.time()}
    friends.append(friend)
    save(friends)
    return friend


def update(uuid: str, **fields):
    friends = load()
    for f in friends:
        if f["uuid"] == uuid:
            f.update(fields)
    save(friends)


def remove(uuid: str):
    save([f for f in load() if f["uuid"] != uuid])


def skin(uuid: str):
    """(skin_url, slim, cape_url) or None if they use a default skin."""
    try:
        return skin_for_uuid(uuid)
    except AuthError:
        return None


# --- Minecraft server list ping ---------------------------------------------------

def _varint(n: int) -> bytes:
    out = b""
    n &= 0xFFFFFFFF
    while True:
        b = n & 0x7F
        n >>= 7
        out += bytes([b | (0x80 if n else 0)])
        if not n:
            return out


def _read_varint(sock) -> int:
    n = shift = 0
    while True:
        b = sock.recv(1)
        if not b:
            raise ConnectionError("server closed the connection")
        n |= (b[0] & 0x7F) << shift
        if not b[0] & 0x80:
            return n
        shift += 7
        if shift > 35:
            raise ConnectionError("bad response")


def _recv_exact(sock, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("server closed the connection")
        buf += chunk
    return buf


def split_address(address: str) -> tuple[str, int | None]:
    address = address.strip()
    if address.count(":") == 1:
        host, port = address.split(":")
        return host, int(port)
    return address, None


def resolve(address: str) -> tuple[str, int]:
    """Apply Minecraft's SRV record (_minecraft._tcp) like the game does."""
    host, port = split_address(address)
    if port is not None:
        return host, port
    try:
        data = get_json("https://dns.google/resolve", params={"name": f"_minecraft._tcp.{host}", "type": "SRV"})
        for ans in data.get("Answer", []):
            if ans.get("type") == 33:
                _prio, _weight, srv_port, target = ans["data"].split()
                return target.rstrip("."), int(srv_port)
    except Exception:  # noqa: BLE001 - no SRV record or DNS lookup failed
        pass
    return host, 25565


def ping(address: str, timeout=5.0) -> dict:
    """Server status: {online, max, names, version, motd, latency_ms}."""
    host, port = resolve(address)
    start = time.time()
    with socket.create_connection((host, port), timeout=timeout) as s:
        s.settimeout(timeout)
        h = host.encode()
        handshake = _varint(0) + _varint(767) + _varint(len(h)) + h + struct.pack(">H", port) + _varint(1)
        s.sendall(_varint(len(handshake)) + handshake)
        s.sendall(_varint(1) + _varint(0))
        _read_varint(s)                     # packet length
        if _read_varint(s) != 0:
            raise ConnectionError("unexpected response")
        data = json.loads(_recv_exact(s, _read_varint(s)))
    latency = int((time.time() - start) * 1000)
    players = data.get("players", {})
    motd = data.get("description", "")
    if isinstance(motd, dict):
        motd = motd.get("text", "") + "".join(e.get("text", "") for e in motd.get("extra", []) if isinstance(e, dict))
    return {"online": players.get("online", 0), "max": players.get("max", 0),
            "names": {p.get("name", "").lower() for p in players.get("sample", []) or []},
            "ids": {p.get("id", "").replace("-", "") for p in players.get("sample", []) or []},
            "version": data.get("version", {}).get("name", ""), "motd": motd, "latency_ms": latency}


def status(friend: dict) -> dict:
    """{state: online|unknown|server-offline|no-server, text} for one friend."""
    if not friend.get("server"):
        return {"state": "no-server", "text": "No server saved"}
    try:
        st = ping(friend["server"])
    except (OSError, ValueError, ConnectionError):
        return {"state": "server-offline", "text": f"{friend['server']} is offline"}
    seen = friend["name"].lower() in st["names"] or friend["uuid"] in st["ids"]
    counts = f"{st['online']}/{st['max']} players"
    if seen:
        return {"state": "online", "text": f"Online on {friend['server']}  ·  {counts}"}
    hidden = st["online"] > 0 and not st["names"]
    return {"state": "unknown",
            "text": f"{friend['server']} is up ({counts})" + (" - player list hidden" if hidden else
                                                              " - not seen online")}
