"""Jace Social client: synced friends, chat and hosted worlds (server code in social/).

Sign-in works like joining a Minecraft server: the server hands out a one-time
id, we tell Mojang's session server we "joined" it with our Minecraft token, and
the server asks Mojang to confirm. Only the real account owner can do that, and
the Minecraft token never leaves this computer except to Mojang.
"""
import time

from jace.accounts import accounts
from jace.config import DATA_DIR, read_json, settings, write_json
from jace.net import session

DEFAULT_URL = "https://jace-social.vercel.app"
SESSIONS_FILE = DATA_DIR / "social.json"


class SocialError(Exception):
    pass


def base_url() -> str:
    return (settings.get("social_url") or DEFAULT_URL).rstrip("/")


def _sessions() -> dict:
    return read_json(SESSIONS_FILE, {})


def current_session() -> dict | None:
    """Saved Jace Social session for the selected Minecraft account, if any."""
    acc = accounts.current()
    if not acc or acc.get("type") != "msa":
        return None
    s = _sessions().get(acc["uuid"])
    if s and s.get("expires_at", "") > time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()):
        return s
    return None


def can_sign_in() -> str | None:
    """None if the selected account can use Jace Social, else why not."""
    acc = accounts.current()
    if not acc:
        return "Add a Microsoft account to use friends and chat."
    if acc.get("type") != "msa":
        return "Friends and chat need a Microsoft account (offline accounts can't be verified)."
    return None


def sign_in() -> dict:
    """Verify the selected Microsoft account with Jace Social. Blocking."""
    why = can_sign_in()
    if why:
        raise SocialError(why)
    acc = accounts.ensure_fresh(accounts.current())
    start = _call("POST", "/api/v1/auth/start", auth=False)
    r = session.post("https://sessionserver.mojang.com/session/minecraft/join", timeout=20, json={
        "accessToken": acc["access_token"], "selectedProfile": acc["uuid"], "serverId": start["server_id"]})
    if r.status_code not in (200, 204):
        raise SocialError("Mojang didn't accept the sign-in. Try signing out and back in to your Microsoft account.")
    s = _call("POST", "/api/v1/auth/finish", {"name": acc["username"], "server_id": start["server_id"]}, auth=False)
    all_s = _sessions()
    all_s[acc["uuid"]] = s
    write_json(SESSIONS_FILE, all_s)
    return s


def sign_out():
    s = current_session()
    if s:
        try:
            _call("POST", "/api/v1/auth/signout", {})
        except Exception:  # noqa: BLE001 - signing out locally is what matters
            pass
        all_s = _sessions()
        all_s.pop(s["uuid"], None)
        write_json(SESSIONS_FILE, all_s)


def _call(method: str, path: str, data=None, auth=True, params=None, _retry=True):
    headers = {}
    if auth:
        s = current_session()
        if not s:
            s = sign_in()
        headers["Authorization"] = f"Bearer {s['token']}"
    try:
        r = session.request(method, base_url() + path, json=data, params=params, headers=headers, timeout=20)
    except Exception as e:  # noqa: BLE001
        raise SocialError(f"Can't reach Jace Social ({e.__class__.__name__}). Check your internet connection.") from e
    if r.status_code == 401 and auth and _retry:      # session expired: sign in again once
        acc = accounts.current()
        if acc:
            all_s = _sessions()
            all_s.pop(acc["uuid"], None)
            write_json(SESSIONS_FILE, all_s)
        return _call(method, path, data, auth, params, _retry=False)
    try:
        body = r.json()
    except ValueError:
        body = {}
    if not r.ok:
        raise SocialError(body.get("error") or f"Jace Social error ({r.status_code})")
    return body


# --- API ---------------------------------------------------------------------------

def friends() -> dict:
    return _call("GET", "/api/v1/friends")


def add_friend(name: str) -> dict:
    return _call("POST", "/api/v1/friends", {"name": name.strip()})


def respond(uuid: str, accept: bool):
    return _call("POST", "/api/v1/friends/respond", {"uuid": uuid, "accept": accept})


def remove_friend(uuid: str):
    return _call("DELETE", "/api/v1/friends", params={"uuid": uuid})


def messages(with_uuid: str, before: int | None = None) -> list[dict]:
    params = {"with": with_uuid}
    if before:
        params["before"] = before
    return _call("GET", "/api/v1/messages", params=params)["messages"]


def send_message(to: str, text: str) -> dict:
    return _call("POST", "/api/v1/messages", {"to": to, "body": text})["message"]


def mark_read(with_uuid: str):
    return _call("POST", "/api/v1/messages/read", {"with": with_uuid})


def set_presence(activity: dict | None, offline=False):
    return _call("POST", "/api/v1/presence", {"activity": activity, "offline": offline})


def describe_activity(f: dict) -> str:
    """One-line status for a friend."""
    if not f.get("online"):
        if not f.get("uses_jace"):
            return "Hasn't joined Jace Launcher yet"
        return "Offline"
    a = f.get("activity") or {}
    if a.get("type") == "hosting":
        return f"Hosting “{a.get('world') or 'a world'}” · {a.get('version', '')}".strip(" ·")
    if a.get("type") == "playing":
        where = f" on {a['server']}" if a.get("server") else ""
        return f"Playing {a.get('version', 'Minecraft')}{where}"
    return "Online"


def join_address(f: dict) -> str | None:
    a = (f.get("activity") or {}) if f.get("online") else {}
    if a.get("type") == "hosting":
        return a.get("address")
    if a.get("type") == "playing":
        return a.get("server")
    return None

