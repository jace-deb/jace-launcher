"""Minecraft: Bedrock Edition instances.

Linux and macOS run Bedrock through the Minecraft Bedrock Launcher (mcpelauncher,
https://minecraft-linux.github.io). It runs the Android version of Bedrock, which you
need to own on Google Play. mcpelauncher's own window does the Google sign-in and
downloads game versions (we never touch the Google account); Jace Launcher installs
mcpelauncher, then starts a chosen downloaded version itself with mcpelauncher-client,
giving every Bedrock instance its own data folder (worlds, packs) like a Java instance.

  Linux  -> Flatpak io.mrarm.mcpelauncher from Flathub (the up-to-date build), or a
            system-wide mcpelauncher-ui-qt if one is installed
  macOS  -> "Minecraft Bedrock Launcher.app" from minecraft-linux/macos-builder
  Windows-> the real Bedrock (Microsoft Store / Xbox app): Play opens it, and importing
            opens the file with Minecraft, which imports it itself
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid as uuidlib
import zipfile
from pathlib import Path

from jace.net import download, get_json, safe_join

FLATPAK_ID = "io.mrarm.mcpelauncher"
FLATHUB = "https://dl.flathub.org/repo/flathub.flatpakrepo"
MAC_RELEASE = "https://api.github.com/repos/minecraft-linux/macos-builder/releases/latest"
MAC_APP = "Minecraft Bedrock Launcher.app"
HOME = Path.home()
IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")      # Linux: BedrockOnLinux (jace/bol.py), not mcpelauncher

# what each kind of content is called, and the com.mojang folder it lives in
FOLDERS = {
    "world": "minecraftWorlds",
    "resource": "resource_packs",
    "behavior": "behavior_packs",
    "skin": "skin_packs",
    "template": "world_templates",
}
IMPORTABLE = (".mcpack", ".mcaddon", ".mcworld", ".mctemplate", ".zip")


class BedrockError(Exception):
    pass


# --- where things are ----------------------------------------------------------------

def _run(cmd, **kw) -> subprocess.CompletedProcess:
    # never let flatpak & co. see the AppImage's own libraries (they break the system's flatpak)
    kw.setdefault("env", _clean_env())
    try:
        return subprocess.run(cmd, capture_output=True, text=True, **kw)
    except OSError as e:
        return subprocess.CompletedProcess(cmd, 1, "", str(e))


def flatpak_installed() -> bool:
    return bool(shutil.which("flatpak")) and _run(["flatpak", "info", FLATPAK_ID]).returncode == 0


def native_launcher() -> str | None:
    return shutil.which("mcpelauncher-ui-qt")


def mac_app() -> Path | None:
    for d in (HOME / "Applications", Path("/Applications")):
        if (d / MAC_APP).is_dir():
            return d / MAC_APP
    return None


def installed() -> str | None:
    """How the Bedrock launcher is installed here ("flatpak", "native", "mac", "windows"), or None."""
    if IS_WIN:
        return "windows"
    if IS_MAC:
        return "mac" if mac_app() else None
    if IS_LINUX:
        from jace import bol
        return "bol" if bol.installed() else None
    if flatpak_installed():
        return "flatpak"
    return "native" if native_launcher() else None


def data_dir() -> Path:
    """mcpelauncher's shared data folder (its default; Jace instances use their own)."""
    if IS_MAC:
        return HOME / "Library" / "Application Support" / "mcpelauncher"
    if installed() == "flatpak" or not native_launcher():
        return HOME / ".var" / "app" / FLATPAK_ID / "data" / "mcpelauncher"
    return Path(os.environ.get("XDG_DATA_HOME") or HOME / ".local" / "share") / "mcpelauncher"


def versions_dir() -> Path:
    """Where mcpelauncher's window keeps downloaded game versions (QStandardPaths GenericDataLocation)."""
    return data_dir() / "versions"


def _version_key(name: str):
    return tuple(int(x) for x in re.findall(r"\d+", name)[:4]) or (0,)


def installed_versions() -> list[dict]:
    """Bedrock versions downloaded in mcpelauncher, newest first: [{name, dir}]."""
    vdir = versions_dir()
    found = {}
    ini = vdir / "versions.ini"
    if ini.is_file():
        group = None
        for line in ini.read_text(errors="replace").splitlines():
            line = line.strip()
            if line.startswith("[") and line.endswith("]"):
                group = line[1:-1]
            elif group and line.startswith("versionName="):
                found[group] = line.split("=", 1)[1].strip()
    out = []
    for d in sorted(vdir.iterdir()) if vdir.is_dir() else []:
        if d.is_dir() and any(d.glob("lib/*/libminecraftpe.so")):
            out.append({"name": found.get(d.name) or d.name, "dir": str(d)})
    return sorted(out, key=lambda v: _version_key(v["name"]), reverse=True)


def version_dir(name: str) -> Path | None:
    return next((Path(v["dir"]) for v in installed_versions() if v["name"] == name), None)


def client_command(version: str, data: Path, width: int = 0, height: int = 0) -> list[str]:
    """Command that starts Bedrock <version> with <data> as its data folder."""
    vdir = version_dir(version)
    if not vdir:
        raise BedrockError(f"Bedrock {version} isn't downloaded yet. Press Play again to download it.")
    args = ["-dg", str(vdir), "-dd", str(data)]
    mods = launcher_mods()
    if mods:
        # Bedrock 1.21.120+ needs mcpelauncher's "mcpelauncher-updates" mod (it adds things like
        # pthread_sigmask that newer versions use); without it the game fails to load.
        args += ["-m", ",".join(mods)]
    if width > 0 and height > 0:
        args += ["-ww", str(width), "-wh", str(height)]
    kind = installed()
    if kind == "flatpak":
        # the sandbox can't see our files: share just this instance's folder with it
        return ["flatpak", "run", f"--filesystem={data}", "--command=mcpelauncher-client", FLATPAK_ID, *args]
    if kind == "native":
        client = shutil.which("mcpelauncher-client")
        if client:
            return [client, *args]
    if kind == "mac":
        client = next((p for p in mac_app().rglob("mcpelauncher-client") if p.is_file()), None)
        if client:
            return [str(client), *args]
    raise BedrockError("Install the Minecraft Bedrock Launcher first")


def launcher_mods() -> list[str]:
    """Mod folders mcpelauncher's window would load: the ones turned on in its Default profile
    (profiles/profiles.ini, "mods\\N\\path="), or else the newest mcpelauncher-updates for this CPU."""
    mods = []
    ini = data_dir() / "profiles" / "profiles.ini"
    if ini.is_file():
        section = None
        for line in ini.read_text(errors="replace").splitlines():
            line = line.strip()
            if line.startswith("["):
                section = line.strip("[]")
            elif section == "Default" and re.match(r"mods\\\d+\\path=", line):
                path = line.split("=", 1)[1].strip()
                if Path(path).is_dir():
                    mods.append(path.rstrip("/"))
    if not mods:
        arch = _arch()
        base = data_dir() / "mods" / "mcpelauncher-updates"
        found = sorted((d for d in base.glob(f"*/{arch}") if (d / "mod.json").is_file()),
                       key=lambda d: _version_key(d.parent.name), reverse=True)
        if found:
            mods.append(str(found[0]))
    return mods


def _arch() -> str:
    return {"x86_64": "x86_64", "AMD64": "x86_64", "arm64": "arm64-v8a", "aarch64": "arm64-v8a"}.get(
        __import__("platform").machine(), "x86_64")


VERSIONDB = "https://raw.githubusercontent.com/minecraft-linux/mcpelauncher-versiondb/master/versions.{}.json.min"
_db_cache: dict[str, list[dict]] = {}


def available_versions(include_beta: bool = False) -> list[dict]:
    """Every Bedrock version the Minecraft Bedrock Launcher can download for this CPU, newest first:
    [{name, code, beta, installed}] (from mcpelauncher-versiondb), plus any already downloaded.
    On Windows: just the official game."""
    if IS_WIN:
        from jace import official
        return [{"name": official.NAMES["bedrock"], "code": 0, "beta": False, "installed": official.installed("bedrock")}]
    if IS_LINUX:
        from jace import bol
        try:
            return [{**v, "code": 0} for v in bol.versions(include_beta)]
        except bol.BolError:
            return []
    arch = _arch()
    if arch not in _db_cache:
        try:
            _db_cache[arch] = [{"code": int(c), "name": n, "beta": bool(b)} for c, n, b in get_json(VERSIONDB.format(arch))]
        except Exception:                          # offline: only what's downloaded
            _db_cache.pop(arch, None)
    have = {v["name"] for v in installed_versions()}
    seen, out = set(), []
    for v in sorted(_db_cache.get(arch, []), key=lambda v: (_version_key(v["name"]), v["code"]), reverse=True):
        if v["name"] in seen or (v["beta"] and not include_beta and v["name"] not in have):
            continue
        seen.add(v["name"])
        out.append({**v, "installed": v["name"] in have})
    out += [{"name": n, "code": 0, "beta": False, "installed": True} for n in have - seen]
    return sorted(out, key=lambda v: _version_key(v["name"]), reverse=True)


def _set_default_profile_version(ini: Path, value: str | None, old: str | None = None) -> str | None:
    """Set "version=" in profiles.ini's [Default] profile (the one mcpelauncher's window shows first).
    Returns the previous value. value=None restores `old`."""
    lines = ini.read_text(errors="replace").splitlines() if ini.is_file() else ["[Default]"]
    if not any(l.strip() == "[Default]" for l in lines):
        lines = ["[Default]"] + lines
    section, prev, done = None, None, False
    for i, line in enumerate(lines):
        t = line.strip()
        if t.startswith("["):
            if section == "Default" and not done:
                lines.insert(i, f"version={value if value is not None else old}")
                done = True
                break
            section = t.strip("[]")
        elif section == "Default" and t.startswith("version="):
            prev = t.split("=", 1)[1]
            lines[i] = f"version={value if value is not None else old}"
            done = True
            break
    if not done:
        lines.append(f"version={value if value is not None else old}")
    ini.parent.mkdir(parents=True, exist_ok=True)
    ini.write_text("\n".join(lines) + "\n")
    return prev


def _kill_launcher(kind: str):
    if kind == "flatpak":
        _run(["flatpak", "kill", FLATPAK_ID])
    else:
        for name in ("mcpelauncher-ui-qt", "mcpelauncher-client"):
            _run(["pkill", "-f", name])


def download_version(name: str, status=print, timeout: float = 1800) -> Path:
    """Get Bedrock `name` like Java versions are fetched on Play: point the Bedrock launcher's Default
    profile at that version, open its window (Google Play needs your account, which only it has:
    click Download and play there), wait until it's downloaded, then close that window."""
    import time
    if d := version_dir(name):
        return d
    kind = installed()
    if kind not in ("flatpak", "native", "mac"):
        raise BedrockError("Install the Minecraft Bedrock Launcher first")
    v = next((v for v in available_versions(include_beta=True) if v["name"] == name and v["code"]), None)
    if not v:
        raise BedrockError(f"Bedrock {name} isn't in the Minecraft Bedrock Launcher's version list")
    ini = data_dir() / "profiles" / "profiles.ini"
    _kill_launcher(kind)                           # it only reads profiles.ini when it starts
    time.sleep(0.5)
    old = _set_default_profile_version(ini, f"lock {v['code']}")
    try:
        open_launcher()
        status(f"Downloading Bedrock {name}: in the Minecraft Bedrock Launcher window, click "
               "Download and play (sign in to Google Play the first time)…")
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            time.sleep(2)
            if d := version_dir(name):
                time.sleep(1)                      # let it finish writing versions.ini
                _kill_launcher(kind)               # it starts the game itself; Jace starts it per instance
                status(f"Downloaded Bedrock {name}")
                return d
            if kind != "mac" and not _launcher_running(kind):
                raise BedrockError(f"The Minecraft Bedrock Launcher was closed before Bedrock {name} was "
                                   "downloaded. Press Play to try again.")
        raise BedrockError(f"Timed out waiting for Bedrock {name} to download")
    finally:
        _set_default_profile_version(ini, None, old if old is not None else "googleplay")


def _launcher_running(kind: str) -> bool:
    if kind == "flatpak":
        return FLATPAK_ID in _run(["flatpak", "ps", "--columns=application"]).stdout
    return _run(["pgrep", "-f", "mcpelauncher-ui-qt"]).returncode == 0


def com_mojang(root: Path | None = None) -> Path:
    """Bedrock's com.mojang folder (worlds, packs) inside a data folder (an instance's)."""
    if root is not None and IS_LINUX:
        from jace import bol
        return bol.mojang_dirs(root)[0]
    if root is not None and not IS_WIN:          # Windows: the official game has one shared folder
        return Path(root) / "games" / "com.mojang"
    if IS_WIN:
        appdata = Path(os.environ.get("APPDATA", HOME / "AppData" / "Roaming"))
        gdk = appdata / "Minecraft Bedrock" / "Users" / "Shared" / "games" / "com.mojang"
        uwp = (Path(os.environ.get("LOCALAPPDATA", HOME / "AppData" / "Local")) / "Packages"
               / "Microsoft.MinecraftUWP_8wekyb3d8bbwe" / "LocalState" / "games" / "com.mojang")
        return gdk if gdk.exists() or not uwp.exists() else uwp
    return data_dir() / "games" / "com.mojang"


def unsupported_reason() -> str | None:
    if IS_WIN or IS_MAC or IS_LINUX:
        return None
    if not shutil.which("flatpak") and not native_launcher():
        return ("Bedrock on Linux needs Flatpak. Install it with your package manager (for example "
                "sudo pacman -S flatpak, sudo apt install flatpak or sudo dnf install flatpak), then come back.")
    return None


# --- install / update / play ------------------------------------------------------------

def install(status=print):
    """Install the Minecraft Bedrock Launcher for this computer."""
    why = unsupported_reason()
    if why:
        raise BedrockError(why)
    if IS_WIN:
        raise BedrockError("On Windows, get Minecraft Bedrock from the Microsoft Store or the Xbox app.")
    if IS_MAC:
        return _install_mac(status)
    if IS_LINUX:
        from jace import bol
        try:
            return bol.install(status)
        except bol.BolError as e:
            raise BedrockError(str(e)) from e
    status("Adding Flathub (just for you, no password needed)…")
    _run(["flatpak", "remote-add", "--user", "--if-not-exists", "flathub", FLATHUB])
    status("Installing the Minecraft Bedrock Launcher from Flathub (this can take a few minutes)…")
    r = _run(["flatpak", "install", "--user", "-y", "--noninteractive", "flathub", FLATPAK_ID])
    if r.returncode != 0 or not flatpak_installed():
        info = _run(["flatpak", "info", FLATPAK_ID])
        raise BedrockError("Flatpak couldn't install the Minecraft Bedrock Launcher.\n\n"
                           + ((r.stderr or r.stdout) + "\n" + (info.stderr or info.stdout)).strip()[-800:])
    status("Installed")


def _install_mac(status):
    rel = get_json(MAC_RELEASE)
    dmg = next((a for a in rel.get("assets", []) if a["name"].endswith(".dmg")), None)
    if not dmg:
        raise BedrockError("Couldn't find the Mac download of the Minecraft Bedrock Launcher")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "bedrock.dmg"
        status(f"Downloading the Minecraft Bedrock Launcher {rel.get('tag_name', '')} "
               f"({dmg['size'] // 1048576} MB)…")
        download(dmg["browser_download_url"], path)
        mount = Path(tmp) / "mnt"
        mount.mkdir()
        status("Installing…")
        r = _run(["hdiutil", "attach", "-nobrowse", "-readonly", "-mountpoint", str(mount), str(path)])
        if r.returncode != 0:
            raise BedrockError("Couldn't open the download: " + r.stderr[-300:])
        try:
            app = next(mount.glob("*.app"), None)
            if not app:
                raise BedrockError("The download didn't contain the app")
            # a writable location, so the app's own updater works
            dest_dir = HOME / "Applications"
            dest_dir.mkdir(exist_ok=True)
            dest = dest_dir / MAC_APP
            if dest.exists():
                shutil.rmtree(dest)
            subprocess.run(["ditto", str(app), str(dest)], check=True)
        finally:
            _run(["hdiutil", "detach", "-quiet", str(mount)])
        _run(["xattr", "-dr", "com.apple.quarantine", str(dest)])
    status("Installed")


def update(status=print):
    kind = installed()
    if kind == "flatpak":
        status("Updating the Minecraft Bedrock Launcher…")
        r = _run(["flatpak", "update", "--user", "-y", "--noninteractive", FLATPAK_ID])
        if r.returncode != 0:
            raise BedrockError("Flatpak couldn't update it:\n" + (r.stderr or r.stdout)[-600:])
    elif kind == "mac":
        _install_mac(status)                    # reinstall the newest build
    status("Up to date")


def open_launcher():
    """Open mcpelauncher's window: Google Play sign-in and downloading versions (or Bedrock on Windows)."""
    kind = installed()
    opts = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if kind == "bol":
        from jace import bol
        bol.open_gui()
    elif kind == "windows":
        os.startfile("minecraft:")             # noqa: S606 - opens Bedrock if it's installed
    elif kind == "mac":
        subprocess.Popen(["open", str(mac_app())], **opts)
    elif kind == "flatpak":
        _start_and_check(["flatpak", "run", FLATPAK_ID])
    elif kind == "native":
        _start_and_check([native_launcher()])
    else:
        raise BedrockError("The Minecraft Bedrock Launcher isn't installed (or Jace Launcher can't see it). "
                           "Click Install Bedrock launcher.")


def _start_and_check(cmd: list[str]):
    """Start a program and make sure it didn't exit straight away; if it did, show why."""
    log = tempfile.TemporaryFile(mode="w+")
    proc = subprocess.Popen(cmd, start_new_session=True, env=_clean_env(), stdin=subprocess.DEVNULL,
                            stdout=log, stderr=subprocess.STDOUT, text=True)
    try:
        code = proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        return                                   # still running: it opened
    log.seek(0)
    raise BedrockError(f"The Minecraft Bedrock Launcher closed right away (exit code {code}):\n\n"
                       + log.read().strip()[-800:])


def _clean_env() -> dict:
    """Our AppImage's library paths would confuse other programs."""
    env = dict(os.environ)
    for k in ("LD_LIBRARY_PATH", "QT_PLUGIN_PATH", "QML2_IMPORT_PATH", "PYTHONPATH", "PYTHONHOME"):
        env.pop(k, None)
    orig = os.environ.get("LD_LIBRARY_PATH_ORIG")
    if orig:
        env["LD_LIBRARY_PATH"] = orig
    return env


# --- worlds and packs -------------------------------------------------------------------

def _pack_name(folder: Path) -> str:
    try:
        m = json.loads((folder / "manifest.json").read_text(encoding="utf-8-sig", errors="replace"))
        name = m.get("header", {}).get("name") or folder.name
        return name if not name.startswith("pack.") else folder.name
    except (OSError, ValueError):
        return folder.name


def list_content(data: Path | None = None) -> dict[str, list[dict]]:
    """{"world": [...], "resource": [...], ...}; each item {name, path}."""
    root = com_mojang(data)
    out = {}
    for kind, sub in FOLDERS.items():
        items = []
        if IS_LINUX and data is not None:
            from jace import bol
            root = bol.content_root(data, sub)
        for d in sorted((root / sub).iterdir()) if (root / sub).is_dir() else []:
            if not d.is_dir():
                continue
            if kind == "world":
                name_file = d / "levelname.txt"
                name = name_file.read_text(errors="replace").strip() if name_file.exists() else d.name
            else:
                name = _pack_name(d)
            items.append({"name": name, "path": str(d)})
        out[kind] = sorted(items, key=lambda i: i["name"].lower())
    return out


def remove(path: str, data: Path | None = None):
    p = Path(path).resolve()
    root = com_mojang(data).resolve()
    if IS_LINUX and data is not None:
        from jace import bol
        root = bol.bedrock_root(data).resolve()
    if root not in p.parents:
        raise BedrockError("That isn't in Minecraft Bedrock's folder")
    shutil.rmtree(p)


def _kind_of(manifest: dict) -> str:
    types = {m.get("type") for m in manifest.get("modules", []) if isinstance(m, dict)}
    if "world_template" in types:
        return "template"
    if "skin_pack" in types:
        return "skin"
    if types & {"data", "script", "client_data"}:
        return "behavior"
    return "resource"


def _safe_name(name: str) -> str:
    return re.sub(r"[^\w\- ]+", "", name).strip()[:40] or "pack"


def _extract(zf: zipfile.ZipFile, prefix: str, dest: Path):
    """Extract the members under prefix/ into dest, refusing paths that escape it.
    A refused or failed import leaves nothing behind."""
    try:
        _extract_into(zf, prefix, dest)
    except ValueError as e:
        shutil.rmtree(dest, ignore_errors=True)
        raise BedrockError("This file tries to put files outside Minecraft's folder, so it wasn't imported.") from e
    except Exception:
        shutil.rmtree(dest, ignore_errors=True)
        raise


def _extract_into(zf: zipfile.ZipFile, prefix: str, dest: Path):
    dest.mkdir(parents=True, exist_ok=True)
    for info in zf.infolist():
        if not info.filename.startswith(prefix) or info.is_dir():
            continue
        rel = info.filename[len(prefix):]
        if not rel:
            continue
        target = safe_join(dest, rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as src, open(target, "wb") as out:
            shutil.copyfileobj(src, out)


def _import_zip(zf: zipfile.ZipFile, hint: str, done: list[str], root: Path):
    names = zf.namelist()
    # nested packs (.mcaddon = several .mcpack files)
    for n in names:
        if n.lower().endswith((".mcpack", ".mcworld", ".mctemplate")) and not n.endswith("/"):
            with zf.open(n) as f, tempfile.TemporaryFile() as tmp:
                shutil.copyfileobj(f, tmp)
                tmp.seek(0)
                with zipfile.ZipFile(tmp) as inner:
                    _import_zip(inner, Path(n).name, done, root)
    # worlds: a level.dat (at the top or in one folder)
    worlds = [n[:-len("level.dat")] for n in names if n.endswith("level.dat") and n.count("/") <= 1]
    manifests = [n[:-len("manifest.json")] for n in names
                 if n.endswith("manifest.json") and not any(n.startswith(w) and w for w in worlds)]
    if hint.lower().endswith(".mcworld") or (worlds and not manifests):
        for prefix in worlds or [""]:
            dest = root / FOLDERS["world"] / uuidlib.uuid4().hex[:12]
            _extract(zf, prefix, dest)
            name = (dest / "levelname.txt").read_text(errors="replace").strip() if (dest / "levelname.txt").exists() else hint
            done.append(f"World: {name}")
        return
    for prefix in manifests:
        try:
            manifest = json.loads(zf.read(prefix + "manifest.json").decode("utf-8-sig", errors="replace"))
        except ValueError:
            continue
        if not isinstance(manifest, dict) or "header" not in manifest:
            continue
        kind = "template" if hint.lower().endswith(".mctemplate") else _kind_of(manifest)
        header = manifest.get("header", {})
        uid = str(header.get("uuid", ""))
        folder = root / FOLDERS[kind]
        # replace an older copy of the same pack (same uuid)
        for existing in folder.glob("*") if folder.is_dir() else []:
            try:
                old = json.loads((existing / "manifest.json").read_text(encoding="utf-8-sig", errors="replace"))
                if uid and old.get("header", {}).get("uuid") == uid:
                    shutil.rmtree(existing)
            except (OSError, ValueError):
                pass
        name = header.get("name") or Path(hint).stem
        dest = folder / f"{_safe_name(name if not str(name).startswith('pack.') else Path(hint).stem)}_{uid[:8] or uuidlib.uuid4().hex[:8]}"
        _extract(zf, prefix, dest)
        done.append(f"{kind.title()} pack: {name}")


def import_file(path: str | Path, data: Path | None = None) -> list[str]:
    """Import a .mcpack / .mcaddon / .mcworld / .mctemplate (or a zip of one) into a data
    folder (an instance's). Returns what was added."""
    path = Path(path)
    if IS_LINUX and data is not None:
        from jace import bol
        try:
            return bol.import_files([path], data)
        except bol.BolError as e:
            raise BedrockError(str(e)) from e
    try:
        zf = zipfile.ZipFile(path)
    except zipfile.BadZipFile as e:
        raise BedrockError(f"{path.name} isn't a Bedrock pack or world") from e
    done: list[str] = []
    with zf:
        _import_zip(zf, path.name, done, com_mojang(data))
    if not done:
        raise BedrockError(f"{path.name} has no Bedrock pack or world in it")
    return done


def install_version(version: dict, data: Path, status=print) -> list[str]:
    """Download a Jace Store Bedrock version (as returned by content.JaceStore) and import it."""
    f = version.get("file")
    if not f:
        raise BedrockError("That version has no file to download")
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp) / Path(f["filename"]).name
        status(f"Downloading {f['filename']}…")
        download(f["url"], dest, sha1=f.get("sha1"))
        return import_file(dest, data)
