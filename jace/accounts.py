"""Microsoft and offline accounts, plus the Minecraft profile (skin/cape) API."""
import base64
import hashlib
import json
import threading
import time
import urllib.parse
import uuid as uuidlib

from jace.config import ACCOUNTS_FILE, read_json, settings, write_json
from jace.net import session

# --- Microsoft OAuth ---------------------------------------------------------
# By default we use the same public client the official launcher uses with the
# login.live.com desktop redirect, so no Azure registration is needed. If the
# user sets their own Azure client id in Settings, we use the modern
# login.microsoftonline.com flow instead.
LIVE_CLIENT_ID = "00000000402b5328"
LIVE_REDIRECT = "https://login.live.com/oauth20_desktop.srf"
LIVE_SCOPE = "service::user.auth.xboxlive.com::MBI_SSL"
LIVE_AUTHORIZE = "https://login.live.com/oauth20_authorize.srf"
LIVE_TOKEN = "https://login.live.com/oauth20_token.srf"

AZURE_AUTHORIZE = "https://login.microsoftonline.com/consumers/oauth2/v2.0/authorize"
AZURE_TOKEN = "https://login.microsoftonline.com/consumers/oauth2/v2.0/token"
AZURE_SCOPE = "XboxLive.signin offline_access"

MC_SERVICES = "https://api.minecraftservices.com"


class AuthError(Exception):
    pass


def _oauth_config():
    cid = (settings.get("azure_client_id") or "").strip()
    if cid:
        return {"client_id": cid, "authorize": AZURE_AUTHORIZE, "token": AZURE_TOKEN,
                "scope": AZURE_SCOPE, "redirect": "https://login.microsoftonline.com/common/oauth2/nativeclient",
                "ticket_prefix": "d="}
    return {"client_id": LIVE_CLIENT_ID, "authorize": LIVE_AUTHORIZE, "token": LIVE_TOKEN,
            "scope": LIVE_SCOPE, "redirect": LIVE_REDIRECT, "ticket_prefix": ""}


def login_url() -> tuple[str, str]:
    """Return (url_to_open, redirect_prefix_to_watch_for)."""
    c = _oauth_config()
    q = {"client_id": c["client_id"], "response_type": "code", "scope": c["scope"],
         "redirect_uri": c["redirect"], "prompt": "select_account"}
    return f'{c["authorize"]}?{urllib.parse.urlencode(q)}', c["redirect"]


def code_from_redirect(url: str) -> str | None:
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    if "error" in qs:
        raise AuthError(qs.get("error_description", qs["error"])[0])
    return qs.get("code", [None])[0]


def _ms_token(params: dict) -> dict:
    c = _oauth_config()
    data = {"client_id": c["client_id"], "redirect_uri": c["redirect"], "scope": c["scope"], **params}
    r = session.post(c["token"], data=data, timeout=30)
    if r.status_code != 200:
        raise AuthError(f"Microsoft token request failed: {r.text[:300]}")
    return r.json()


def _xbox_to_minecraft(ms_access_token: str) -> dict:
    c = _oauth_config()
    r = session.post("https://user.auth.xboxlive.com/user/authenticate", json={
        "Properties": {"AuthMethod": "RPS", "SiteName": "user.auth.xboxlive.com",
                       "RpsTicket": c["ticket_prefix"] + ms_access_token},
        "RelyingParty": "http://auth.xboxlive.com", "TokenType": "JWT"}, timeout=30)
    if r.status_code != 200:
        raise AuthError(f"Xbox Live authentication failed ({r.status_code})")
    xbl = r.json()
    uhs = xbl["DisplayClaims"]["xui"][0]["uhs"]

    r = session.post("https://xsts.auth.xboxlive.com/xsts/authorize", json={
        "Properties": {"SandboxId": "RETAIL", "UserTokens": [xbl["Token"]]},
        "RelyingParty": "rp://api.minecraftservices.com/", "TokenType": "JWT"}, timeout=30)
    if r.status_code != 200:
        err = r.json().get("XErr") if r.content else None
        reasons = {2148916233: "This Microsoft account has no Xbox profile. Sign in at xbox.com first.",
                   2148916235: "Xbox Live is not available in your country.",
                   2148916238: "This is a child account; an adult must add it to a Family group."}
        raise AuthError(reasons.get(err, f"XSTS authorization failed ({err or r.status_code})"))
    xsts = r.json()

    r = session.post(f"{MC_SERVICES}/authentication/login_with_xbox",
                     json={"identityToken": f"XBL3.0 x={uhs};{xsts['Token']}"}, timeout=30)
    if r.status_code != 200:
        raise AuthError(f"Minecraft login failed ({r.status_code}): {r.text[:200]}")
    mc = r.json()

    profile = get_profile(mc["access_token"])
    if profile is None:
        raise AuthError("This Microsoft account does not own Minecraft: Java Edition.")
    return {"access_token": mc["access_token"], "expires_at": time.time() + mc.get("expires_in", 86400) - 60,
            "uuid": profile["id"], "username": profile["name"], "xuid": xbl["DisplayClaims"]["xui"][0].get("xid", "")}


def complete_microsoft_login(code: str) -> dict:
    tok = _ms_token({"code": code, "grant_type": "authorization_code"})
    acc = _xbox_to_minecraft(tok["access_token"])
    acc.update({"type": "msa", "refresh_token": tok.get("refresh_token", ""),
                "client_id": _oauth_config()["client_id"]})
    return acc


def offline_uuid(name: str) -> str:
    """Same UUID the vanilla server assigns to offline players."""
    h = bytearray(hashlib.md5(f"OfflinePlayer:{name}".encode()).digest())
    h[6] = (h[6] & 0x0F) | 0x30
    h[8] = (h[8] & 0x3F) | 0x80
    return uuidlib.UUID(bytes=bytes(h)).hex


# --- Account store -------------------------------------------------------------

class AccountStore:
    _lock = threading.RLock()

    def __init__(self):
        data = read_json(ACCOUNTS_FILE, {})
        self.accounts: list[dict] = data.get("accounts", [])
        self.selected: str | None = data.get("selected")

    def save(self):
        with self._lock:
            write_json(ACCOUNTS_FILE, {"accounts": self.accounts, "selected": self.selected})

    def add(self, acc: dict):
        with self._lock:
            self.accounts = [a for a in self.accounts if a["uuid"] != acc["uuid"]]
            self.accounts.append(acc)
            self.selected = acc["uuid"]
            self.save()

    def add_offline(self, name: str) -> dict:
        acc = {"type": "offline", "username": name, "uuid": offline_uuid(name)}
        self.add(acc)
        return acc

    def remove(self, uid: str):
        with self._lock:
            self.accounts = [a for a in self.accounts if a["uuid"] != uid]
            if self.selected == uid:
                self.selected = self.accounts[0]["uuid"] if self.accounts else None
            self.save()

    def select(self, uid: str):
        self.selected = uid
        self.save()

    def current(self) -> dict | None:
        for a in self.accounts:
            if a["uuid"] == self.selected:
                return a
        return self.accounts[0] if self.accounts else None

    def ensure_fresh(self, acc: dict) -> dict:
        """Refresh a Microsoft account's token if it expired. Blocking."""
        if acc.get("type") != "msa" or acc.get("expires_at", 0) > time.time():
            return acc
        if not acc.get("refresh_token"):
            raise AuthError("Session expired - please sign in again.")
        if acc.get("client_id") and acc["client_id"] != _oauth_config()["client_id"]:
            raise AuthError("Microsoft client id changed - please sign in again.")
        tok = _ms_token({"refresh_token": acc["refresh_token"], "grant_type": "refresh_token"})
        fresh = _xbox_to_minecraft(tok["access_token"])
        with self._lock:
            acc.update(fresh)
            acc["refresh_token"] = tok.get("refresh_token", acc["refresh_token"])
            self.save()
        return acc


accounts = AccountStore()


# --- Profile / skins / capes -------------------------------------------------

def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def get_profile(token: str) -> dict | None:
    r = session.get(f"{MC_SERVICES}/minecraft/profile", headers=_auth(token), timeout=30)
    if r.status_code == 404:
        return None
    if r.status_code != 200:
        raise AuthError(f"Could not load profile ({r.status_code})")
    return r.json()


def _profile_call(method, path, token, **kw) -> dict:
    r = session.request(method, f"{MC_SERVICES}{path}", headers=_auth(token), timeout=60, **kw)
    if r.status_code == 429:
        raise AuthError("Rate limited by Mojang - wait a minute and try again.")
    if r.status_code not in (200, 204):
        try:
            msg = r.json().get("errorMessage") or r.text
        except ValueError:
            msg = r.text
        raise AuthError(f"Request failed ({r.status_code}): {msg[:200]}")
    return r.json() if r.content else {}


def upload_skin(token: str, png_bytes: bytes, slim: bool) -> dict:
    return _profile_call("POST", "/minecraft/profile/skins", token,
                         data={"variant": "slim" if slim else "classic"},
                         files={"file": ("skin.png", png_bytes, "image/png")})


def set_skin_url(token: str, url: str, slim: bool) -> dict:
    return _profile_call("POST", "/minecraft/profile/skins", token,
                         json={"variant": "slim" if slim else "classic", "url": url})


def reset_skin(token: str) -> dict:
    return _profile_call("DELETE", "/minecraft/profile/skins/active", token)


def set_cape(token: str, cape_id: str | None) -> dict:
    if cape_id:
        return _profile_call("PUT", "/minecraft/profile/capes/active", token, json={"capeId": cape_id})
    return _profile_call("DELETE", "/minecraft/profile/capes/active", token)


def _https(url):
    return url.replace("http://", "https://", 1) if url else url


def lookup_player_skin(name: str) -> tuple[str, bool, str | None]:
    """Find any player's current skin by username -> (skin_url, slim, cape_url)."""
    r = session.get(f"https://api.mojang.com/users/profiles/minecraft/{urllib.parse.quote(name)}", timeout=20)
    if r.status_code != 200:
        raise AuthError(f"Player '{name}' not found")
    return skin_for_uuid(r.json()["id"], name)


def skin_for_uuid(pid: str, name: str = "") -> tuple[str, bool, str | None]:
    """Public skin lookup by profile UUID via Mojang's session server."""
    prof = session.get(f"https://sessionserver.mojang.com/session/minecraft/profile/{pid}", timeout=20).json()
    for p in prof.get("properties", []):
        if p["name"] == "textures":
            tex = json.loads(base64.b64decode(p["value"]))["textures"]
            skin = tex.get("SKIN")
            if not skin:
                break
            slim = skin.get("metadata", {}).get("model") == "slim"
            cape = tex.get("CAPE", {}).get("url")
            return _https(skin["url"]), slim, _https(cape)
    raise AuthError(f"'{name or pid}' uses the default skin")

