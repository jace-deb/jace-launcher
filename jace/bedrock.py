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
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


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
        raise BedrockError(f"Bedrock {version} isn't downloaded. Click \"Download versions\" (it opens the "
                           f"Minecraft Bedrock Launcher) and download it there, then press Play again.")
    args = ["-dg", str(vdir), "-dd", str(data)]
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


def com_mojang(root: Path | None = None) -> Path:
    """Bedrock's com.mojang folder (worlds, packs) inside a data folder (an instance's)."""
    if root is not None:
        return Path(root) / "games" / "com.mojang"
    if IS_WIN:
        appdata = Path(os.environ.get("APPDATA", HOME / "AppData" / "Roaming"))
        gdk = appdata / "Minecraft Bedrock" / "Users" / "Shared" / "games" / "com.mojang"
        uwp = (Path(os.environ.get("LOCALAPPDATA", HOME / "AppData" / "Local")) / "Packages"
               / "Microsoft.MinecraftUWP_8wekyb3d8bbwe" / "LocalState" / "games" / "com.mojang")
        return gdk if gdk.exists() or not uwp.exists() else uwp
    return data_dir() / "games" / "com.mojang"


def unsupported_reason() -> str | None:
    if IS_WIN or IS_MAC:
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
    status("Adding Flathub (just for you, no password needed)…")
    _run(["flatpak", "remote-add", "--user", "--if-not-exists", "flathub", FLATHUB])
    status("Installing the Minecraft Bedrock Launcher from Flathub (this can take a few minutes)…")
    r = _run(["flatpak", "install", "--user", "-y", "--noninteractive", "flathub", FLATPAK_ID])
    if r.returncode != 0:
        raise BedrockError("Flatpak couldn't install the Bedrock launcher:\n" + (r.stderr or r.stdout)[-600:])
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
    if kind == "windows":
        os.startfile("minecraft:")             # noqa: S606 - opens Bedrock if it's installed
    elif kind == "mac":
        subprocess.Popen(["open", str(mac_app())], **opts)
    elif kind == "flatpak":
        subprocess.Popen(["flatpak", "run", FLATPAK_ID], start_new_session=True, env=_clean_env(), **opts)
    elif kind == "native":
        subprocess.Popen([native_launcher()], start_new_session=True, env=_clean_env(), **opts)
    else:
        raise BedrockError("Install the Minecraft Bedrock Launcher first")


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
    if IS_WIN and data is None:
        os.startfile(str(path))                 # noqa: S606 - Minecraft imports it itself
        return [f"Opened {path.name} with Minecraft"]
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
