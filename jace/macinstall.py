"""macOS self-installer: copies Jace Launcher.app out of Downloads (or wherever it was opened)
into an Applications folder and optionally adds it to the Dock, the Desktop and
the Terminal. Used by the setup wizard and by Settings → Delete Jace Launcher.
"""
import os
import plistlib
import shutil
import subprocess
import sys
import time
from pathlib import Path

APP_NAME = "Jace Launcher.app"
HOME = Path.home()
SYSTEM_APPS = Path("/Applications")
USER_APPS = HOME / "Applications"
DESKTOP_LINK = HOME / "Desktop" / "Jace Launcher"
LSREGISTER = ("/System/Library/Frameworks/CoreServices.framework/Frameworks/"
              "LaunchServices.framework/Support/lsregister")

OPTIONS = [
    ("dock", "Keep in the Dock", True),
    ("desktop", "Create a desktop shortcut", True),
    ("terminal", "Add the  jace-launcher  Terminal command", False),
    ("unquarantine", "Remove the \"downloaded from the internet\" flag "
                     "(stops the \"app is damaged\" warning)", True),
]


def running_bundle() -> Path | None:
    """The .app we're running from (Contents/MacOS/<exe> -> .app), if frozen on macOS."""
    if sys.platform != "darwin" or not getattr(sys, "frozen", False):
        return None
    app = Path(sys.executable).resolve().parents[2]
    return app if app.suffix == ".app" else None


def translocated(app: Path) -> bool:
    """Gatekeeper runs quarantined apps from a random read-only copy ("App Translocation")."""
    return "/AppTranslocation/" in str(app)


def default_dir() -> Path:
    return SYSTEM_APPS if os.access(SYSTEM_APPS, os.W_OK) else USER_APPS


def terminal_command_path() -> Path:
    usr_local = Path("/usr/local/bin")
    return usr_local / "jace-launcher" if os.access(usr_local, os.W_OK) else HOME / ".local" / "bin" / "jace-launcher"


def _run(cmd):
    return subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


# --- Dock -------------------------------------------------------------------------

def _dock_url(app: Path) -> str:
    return app.as_uri().rstrip("/") + "/"


def _dock_prefs() -> dict:
    out = subprocess.run(["defaults", "export", "com.apple.dock", "-"], capture_output=True, check=False).stdout
    return plistlib.loads(out) if out else {}


def _tile_url(tile) -> str:
    return tile.get("tile-data", {}).get("file-data", {}).get("_CFURLString", "")


def dock_add(app: Path):
    url = _dock_url(app)
    if any(_tile_url(t) == url for t in _dock_prefs().get("persistent-apps", [])):
        return
    tile = (f"<dict><key>tile-data</key><dict><key>file-data</key><dict>"
            f"<key>_CFURLString</key><string>{url}</string>"
            f"<key>_CFURLStringType</key><integer>15</integer></dict></dict></dict>")
    _run(["defaults", "write", "com.apple.dock", "persistent-apps", "-array-add", tile])
    _run(["killall", "Dock"])


def dock_remove(app_name=APP_NAME):
    """Remove our Dock icon. The Dock saves its own copy of the icon list when it
    restarts, so if it was still starting up (e.g. right after dock_add) it can
    write our icon back; check the result and retry a few times."""
    suffix = app_name.replace(" ", "%20")
    for _ in range(5):
        prefs = _dock_prefs()
        apps = prefs.get("persistent-apps", [])
        keep = [t for t in apps if not _tile_url(t).rstrip("/").endswith(suffix)]
        if len(keep) == len(apps):
            return
        prefs["persistent-apps"] = keep
        subprocess.run(["defaults", "import", "com.apple.dock", "-"], input=plistlib.dumps(prefs), check=False)
        _run(["killall", "Dock"])
        time.sleep(2)


# --- install / uninstall ---------------------------------------------------------------

def install(target_dir: Path, options: dict, status=print) -> tuple[Path, list[str]]:
    src = running_bundle()
    if not src:
        raise RuntimeError("Not running from a packaged Jace Launcher.app")
    target_dir = Path(target_dir).expanduser()
    target_dir.mkdir(parents=True, exist_ok=True)
    dst = target_dir / APP_NAME
    parts = []

    if src.resolve() != dst.resolve():
        status(f"Copying Jace Launcher to {target_dir}")
        tmp = target_dir / f".{APP_NAME}.installing"
        shutil.rmtree(tmp, ignore_errors=True)
        # ditto keeps the code signature, symlinks and extended attributes intact
        subprocess.run(["ditto", str(src), str(tmp)], check=True)
        if dst.exists():
            shutil.rmtree(dst)
        tmp.rename(dst)
    else:
        status("Jace Launcher is already in this folder")

    if options.get("unquarantine"):
        status("Removing the downloaded-from-internet flag")
        _run(["xattr", "-dr", "com.apple.quarantine", str(dst)])
        parts.append("unquarantine")

    status("Registering with Launchpad and Spotlight")
    _run([LSREGISTER, "-f", str(dst)])
    parts.append("applications")

    if options.get("dock"):
        status("Adding to the Dock")
        dock_add(dst)
        parts.append("dock")
    if options.get("desktop"):
        status("Creating desktop shortcut")
        DESKTOP_LINK.parent.mkdir(parents=True, exist_ok=True)
        if DESKTOP_LINK.is_symlink() or DESKTOP_LINK.exists():
            DESKTOP_LINK.unlink()
        DESKTOP_LINK.symlink_to(dst)
        parts.append("desktop")
    if options.get("terminal"):
        cmd = terminal_command_path()
        status(f"Adding the 'jace-launcher' command ({cmd})")
        cmd.parent.mkdir(parents=True, exist_ok=True)
        cmd.write_text(f'#!/bin/sh\nexec "{dst}/Contents/MacOS/Jace Launcher" "$@"\n')
        cmd.chmod(0o755)
        parts.append("terminal")
    status("Done")
    return dst, parts


def relaunch_installed(app: Path, downloaded: Path | None = None):
    """Start the installed copy. Then, once we've quit, delete the downloaded copy we
    were running from (e.g. ~/Downloads/Jace Launcher.app) so only one copy is left.
    Gatekeeper's translocated copy hides the real download location, so in that case
    the download is left for the user to delete."""
    subprocess.Popen(["open", "-n", str(app)])
    if (downloaded and downloaded.suffix == ".app" and downloaded.resolve() != app.resolve()
            and not translocated(downloaded) and not str(downloaded).startswith("/Volumes/")):
        subprocess.Popen(["/bin/sh", "-c", 'sleep 4; rm -rf "$0"', str(downloaded)], start_new_session=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def download_left_behind() -> bool:
    app = running_bundle()
    return bool(app and translocated(app))


def uninstall(app: Path | None):
    """Remove shortcuts now; the .app itself is deleted a moment after we quit."""
    dock_remove()
    for p in (DESKTOP_LINK, terminal_command_path(), HOME / ".local" / "bin" / "jace-launcher"):
        if p.is_symlink() or p.exists():
            p.unlink()
    if app and app.exists() and not translocated(app):
        subprocess.Popen(["/bin/sh", "-c", 'sleep 2; rm -rf "$0"', str(app)], start_new_session=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
