"""Minecraft Bedrock on Linux through BedrockOnLinux (github.com/Wyze3306/BedrockOnLinux, MIT).

BedrockOnLinux runs the Windows (GDK) Minecraft Bedrock under GDK-Proton: real Xbox sign-in,
Friends, servers and Realms. The game is downloaded from the Microsoft Store with the user's own
account, which must own Minecraft. Jace Launcher drives its command line:

- `versions` lists the builds, `setup --mc release --version X` downloads and selects one,
  `store-login` links the Microsoft account the Store download needs (its own sign-in window),
  `play` starts the game and `import` adds packs and worlds.
- Each Jace Bedrock instance is its own BOL_HOME (like BedrockOnLinux's own profiles): its own
  Wine prefix, so its own worlds, settings and Xbox sign-in. The big shared parts (game builds,
  Proton, the Store sign-in) are links to BedrockOnLinux's main folder, so they download once.
"""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from jace.config import DATA_DIR
from jace.net import download, get_json

REPO = "Wyze3306/BedrockOnLinux"
FLATPAK_ID = "io.github.wyze3306.BedrockOnLinux"
OWN = DATA_DIR / "bedrock-on-linux" / "BedrockOnLinux.AppImage"
HOME = Path.home()
MAIN_DATA = Path(os.environ.get("XDG_DATA_HOME") or HOME / ".local" / "share") / "bedrock-on-linux"
# the parts of a BedrockOnLinux home every profile shares (bol/profiles.py _SHARED_DIRS)
# + xodus-home: the Microsoft Store sign-in and device registration (one per PC, not per instance:
# Microsoft allows 10 devices per account)
SHARED_DIRS = ("games", "proton", "umu", "cache", "xodus", "xodus-home", "xodus-xcurl", "xodus-webview")
ROAMING = Path("compatdata/pfx/drive_c/users/steamuser/AppData/Roaming/Minecraft Bedrock")
SHARED_MOJANG = ROAMING / "Users" / "Shared" / "games" / "com.mojang"
PER_ACCOUNT = {"minecraftWorlds", "world_templates", "custom_skins"}   # the rest is in Users/Shared


class BolError(Exception):
    pass


def _env(home: Path | None = None) -> dict:
    from jace.bedrock import _clean_env
    env = _clean_env()
    env["APPIMAGELAUNCHER_DISABLE"] = "1"         # see desktop.NO_AIL
    if home is not None:
        env["BOL_HOME"] = str(home)
    return env


def command() -> list[str] | None:
    """How to run BedrockOnLinux here: our own copy, one you downloaded (AppImageLauncher keeps them
    in ~/Applications), a .deb/.rpm install, or the Flatpak."""
    if OWN.is_file():
        return [str(OWN)]
    for d in (HOME / "Applications", HOME / ".local" / "bin", HOME / "Downloads"):
        found = sorted(d.glob("BedrockOnLinux*.AppImage"), key=lambda p: p.stat().st_mtime, reverse=True) \
            if d.is_dir() else []
        if found and os.access(found[0], os.X_OK):
            return [str(found[0])]
    if exe := shutil.which("bedrock-on-linux"):
        return [exe]
    if shutil.which("flatpak") and subprocess.run(["flatpak", "info", FLATPAK_ID], capture_output=True,
                                                  env=_env()).returncode == 0:
        return ["flatpak", "run", FLATPAK_ID]
    return None


def installed() -> bool:
    return command() is not None


def install(status=print):
    """Download the latest BedrockOnLinux AppImage (checked against its release's SHA256SUMS).
    It keeps itself up to date after that."""
    import hashlib
    try:
        rel = get_json(f"https://api.github.com/repos/{REPO}/releases/latest")
    except Exception as e:  # noqa: BLE001
        raise BolError("Couldn't reach GitHub to download BedrockOnLinux. Check your internet connection.") from e
    assets = {a["name"]: a["browser_download_url"] for a in rel.get("assets", [])}
    app = next((n for n in assets if re.fullmatch(r"BedrockOnLinux-.*-x86_64\.AppImage", n)), None)
    sums = next((n for n in assets if n.endswith("SHA256SUMS")), None)
    if not app or not sums:
        raise BolError("BedrockOnLinux's latest release has no AppImage")
    from jace.net import session
    want = next((ln.split()[0] for ln in session.get(assets[sums], timeout=30).text.splitlines()
                 if ln.strip().endswith(app)), None)
    status(f"Downloading BedrockOnLinux {rel.get('tag_name', '')}…")
    tmp = OWN.with_name(OWN.name + ".download")
    last = [-1]

    def progress(done, total):
        pct = done * 100 // total if total else 0
        if pct != last[0]:
            last[0] = pct
            status(f"Downloading BedrockOnLinux… {pct}%")
    download(assets[app], tmp, progress=progress)
    h = hashlib.sha256()
    with open(tmp, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    if not want or h.hexdigest() != want:
        tmp.unlink(missing_ok=True)
        raise BolError("The BedrockOnLinux download didn't match its checksum. Try again.")
    tmp.chmod(0o755)
    os.replace(tmp, OWN)
    status("BedrockOnLinux installed")


def _run(args, home: Path | None = None, timeout=300) -> subprocess.CompletedProcess:
    cmd = command()
    if not cmd:
        raise BolError("BedrockOnLinux isn't installed")
    try:
        return subprocess.run([*cmd, *args], capture_output=True, text=True, timeout=timeout, env=_env(home),
                              stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise BolError(f"BedrockOnLinux didn't respond: {e}") from e


def _stream(args, home: Path | None, status, what: str):
    """Run a BedrockOnLinux command, passing its progress lines to status()."""
    cmd = command()
    if not cmd:
        raise BolError("BedrockOnLinux isn't installed")
    proc = subprocess.Popen([*cmd, *args], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            env=_env(home), stdin=subprocess.DEVNULL)
    tail = []
    for line in proc.stdout:
        line = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", line).strip()
        if line and not line.startswith("[appimagelauncher"):
            tail = (tail + [line])[-12:]
            status(line[:110])
    if proc.wait() != 0:
        raise BolError(f"BedrockOnLinux couldn't {what}:\n\n" + "\n".join(tail))


_versions: dict[bool, list[dict]] = {}


def versions(include_beta=False) -> list[dict]:
    """[{name, edition, beta, installed}] newest first, from `bedrock-on-linux versions`."""
    if include_beta not in _versions:
        r = _run(["versions"] + (["--beta"] if include_beta else []), timeout=300)   # 1st: fetches the index
        out, edition = [], None
        for line in r.stdout.splitlines():
            if m := re.search(r"\(--mc (\w+)\)", line):
                edition = m.group(1)
            elif edition and (m := re.match(r"\s+(\d+(?:\.\d+)+)\s*(installed)?", line)):
                out.append({"name": m.group(1) if edition == "release" else f"{m.group(1)} (Preview)",
                            "version": m.group(1), "edition": edition, "beta": edition != "release",
                            "installed": bool(m.group(2))})
        if not out:
            raise BolError("BedrockOnLinux didn't list any versions:\n" + (r.stderr or r.stdout)[-400:])
        _versions[include_beta] = out
    return _versions[include_beta]


def home(data: Path) -> Path:
    """The BedrockOnLinux home of a Jace instance (data = its game folder)."""
    return Path(data) / "bedrock-on-linux"


def _main_data() -> Path:
    try:                                           # BedrockOnLinux can be moved in its Settings
        p = (Path(os.environ.get("XDG_CONFIG_HOME") or HOME / ".config") / "bedrock-on-linux"
             / "install_location").read_text().strip()
        if p:
            return Path(p)
    except OSError:
        pass
    return MAIN_DATA


def ensure_home(data: Path) -> Path:
    h = home(data)
    h.mkdir(parents=True, exist_ok=True)
    main = _main_data()
    for name in SHARED_DIRS:
        target = main / name
        target.mkdir(parents=True, exist_ok=True)
        link = h / name
        if link.is_symlink() and link.resolve() == target.resolve():
            continue
        if link.is_symlink() or link.is_file():
            link.unlink()
        elif link.is_dir():
            shutil.rmtree(link)
        link.symlink_to(target, target_is_directory=True)
    return h


def _selected(h: Path) -> tuple[str, str] | None:
    """(edition, version) this home will play, from its settings.json (bol/games.py use_game_dir)."""
    try:
        st = json.loads((h / "settings.json").read_text())
    except (OSError, ValueError):
        return None
    if not st.get("game_dir") or not Path(st["game_dir"]).is_dir() or not st.get("mc_version"):
        return None
    return st.get("mc_edition") or "release", st["mc_version"]


def prepare(name: str, data: Path, status=print):
    """Get Bedrock `name` ready to play in this instance: the Microsoft Store sign-in (once, in
    BedrockOnLinux's own window), the download (once per version, shared) and this instance's
    Wine prefix."""
    if not installed():
        install(status)
    h = ensure_home(data)
    v = next((v for v in versions(include_beta=True) if v["name"] == name), None)
    version, edition = (v["version"], v["edition"]) if v else (name.split()[0], "release")
    sel = _selected(h)
    if sel == (edition, version):
        return
    status("Linking your Microsoft account for the Minecraft download (a sign-in window may open)…")
    _stream(["store-login"], h, status, "sign in to the Microsoft Store")
    status(f"Getting Minecraft Bedrock {version} (the first time downloads the game and Proton)…")
    _stream(["setup", "--mc", edition, "--version", version] + (["--beta"] if edition != "release" else []),
            h, status, f"set up Bedrock {version}")
    _versions.clear()


def play_command(data: Path) -> list[str]:
    cmd = command()
    if not cmd:
        raise BolError("BedrockOnLinux isn't installed")
    return ["env", "APPIMAGELAUNCHER_DISABLE=1", f"BOL_HOME={home(data)}", *cmd, "play"]


def open_gui(data: Path | None = None):
    cmd = command()
    if not cmd:
        raise BolError("BedrockOnLinux isn't installed")
    subprocess.Popen([*cmd, "gui"], start_new_session=True, env=_env(home(data) if data else None),
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# --- worlds and packs --------------------------------------------------------------------

def mojang_dirs(data: Path) -> tuple[Path, Path]:
    """(the signed-in account's com.mojang, Users/Shared's). Worlds, templates and skins are per
    account; the game used the account whose options.txt was written last (bol/content.py)."""
    h = home(data)
    shared = h / SHARED_MOJANG
    users = h / ROAMING / "Users"
    opts = sorted(users.glob("*/games/com.mojang/minecraftpe/options.txt"),
                  key=lambda p: p.stat().st_mtime, reverse=True) if users.is_dir() else []
    return (opts[0].parent.parent if opts else shared), shared


def content_root(data: Path, sub: str) -> Path:
    account, shared = mojang_dirs(data)
    return account if sub in PER_ACCOUNT else shared


def bedrock_root(data: Path) -> Path:
    return home(data) / ROAMING


def import_files(paths, data: Path) -> list[str]:
    ensure_home(data)
    r = _run(["import", *map(str, paths)], home(data), timeout=600)
    if r.returncode != 0:
        raise BolError("BedrockOnLinux couldn't import it:\n" + (r.stderr or r.stdout)[-500:])
    return [f"Imported {Path(p).name}" for p in paths]
