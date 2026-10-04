"""One-click updates from GitHub Releases.

check()  -> info about a newer release (or None)
apply()  -> downloads the right file for this platform and arranges for it to
            replace the running app; the caller must quit right afterwards.

  Linux    the AppImage file is replaced in place, then restarted
  macOS    the new .app is unzipped, swapped in once we quit, then opened
  Windows  the new installer .exe is started with --apply-update; once we quit
           it copies itself over the installed app and starts it
"""
import os
import platform
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from jace import APP_VERSION, desktop, macinstall
from jace.net import download, get_json, session

REPO = "ququoqu/jace-launcher"
LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"


def current_version() -> str:
    # JACE_FAKE_VERSION lets us test the update flow against a real release
    return os.environ.get("JACE_FAKE_VERSION") or APP_VERSION


def parse_version(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


def asset_suffix() -> str | None:
    if sys.platform == "win32":
        return "-windows-x64.exe"
    if sys.platform == "darwin":
        return f"-macos-{'arm64' if platform.machine() == 'arm64' else 'x86_64'}.app.zip"
    if sys.platform.startswith("linux"):
        return "-x86_64.AppImage"
    return None


def update_target() -> Path | None:
    """What gets replaced: the installed copy, else the package we're running from."""
    if not desktop.frozen():
        return None
    target = desktop.installed_path() or desktop.running_package()
    if target and sys.platform == "darwin" and macinstall.translocated(target):
        return None
    return target


def unsupported_reason() -> str | None:
    if not desktop.frozen():
        return "You're running from source - update with  git pull."
    if asset_suffix() is None:
        return "Updates aren't available for this platform."
    target = update_target()
    if target is None:
        if sys.platform == "darwin":
            return "Install Jace Launcher first (open it from Downloads and finish setup), then update."
        return "Install Jace Launcher first, then update."
    if not os.access(target.parent, os.W_OK):
        return f"Can't write to {target.parent}."
    return None


def _latest_release() -> dict:
    """Latest release via the GitHub API. The API allows only 60 anonymous requests
    an hour per IP address (shared networks hit that), so if it refuses, read the
    tag from github.com's /releases/latest redirect and build the download link
    from the release file naming instead."""
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        return get_json(LATEST, headers=headers)
    except Exception:  # noqa: BLE001 - rate limited or API down: use the website instead
        r = session.head(f"https://github.com/{REPO}/releases/latest", allow_redirects=False, timeout=20)
        tag = r.headers.get("location", "").rstrip("/").rsplit("/", 1)[-1]
        if not tag.startswith("v"):
            raise
        ver = tag.lstrip("v")
        suffix = asset_suffix() or ""
        name = f"JaceLauncher-{ver}{suffix}"
        return {"tag_name": tag, "body": "", "html_url": f"https://github.com/{REPO}/releases/tag/{tag}",
                "assets": [{"name": name, "size": None,
                            "browser_download_url": f"https://github.com/{REPO}/releases/download/{tag}/{name}"}]}


def check() -> dict | None:
    """Return {version, notes, url, size, page} if a newer release exists, else None."""
    rel = _latest_release()
    latest = rel.get("tag_name", "").lstrip("v")
    if not latest or parse_version(latest) <= parse_version(current_version()):
        return None
    suffix = asset_suffix()
    asset = next((a for a in rel.get("assets", []) if suffix and a["name"].endswith(suffix)), None)
    return {"version": latest, "notes": rel.get("body") or "", "page": rel.get("html_url", ""),
            "url": asset and asset["browser_download_url"], "size": asset and asset["size"]}


def _clean_env() -> dict:
    """Environment for starting another copy of the app without PyInstaller's
    internal variables (otherwise the new copy thinks it's our child process)."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("_PYI", "_MEI"))}
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env


def cli(argv) -> None:
    """--update --yes [--no-relaunch]: update without the GUI (used by tests)."""
    reason = unsupported_reason()
    if reason:
        print(reason)
        sys.exit(1)
    info = check()
    if not info:
        print(f"Up to date ({current_version()})")
        return
    print(f"Updating {current_version()} -> {info['version']}")
    cb = {"setStatus": print, "setMax": lambda m: None, "setProgress": lambda v: None}
    apply(info, cb, relaunch="--no-relaunch" not in argv,
          extra_args=[a for a in ("--no-gui",) if a in argv])
    print("Update staged")


def _progress(callback):
    state = {"max": None}

    def report(done, total):
        if total and state["max"] != total:
            state["max"] = total
            callback["setMax"](total)
        callback["setProgress"](done)
    return report


def apply(info: dict, callback: dict, relaunch=True, extra_args=()) -> str:
    """Download and stage the update. Returns a message; caller then quits the app."""
    reason = unsupported_reason()
    if reason:
        raise RuntimeError(reason)
    if not info.get("url"):
        raise RuntimeError("This release has no download for your platform.")
    status = callback["setStatus"]
    target = update_target()
    status(f"Downloading Jace Launcher {info['version']}…")

    if sys.platform.startswith("linux"):
        new = target.with_name(target.name + ".new")
        download(info["url"], new, progress=_progress(callback))
        new.chmod(0o755)
        os.replace(new, target)          # safe while running: the old file stays mounted
        if relaunch:
            subprocess.Popen([str(target)], start_new_session=True, env=_clean_env())
        return "restarting"

    work = Path(tempfile.mkdtemp(prefix="jace-update-"))
    if sys.platform == "darwin":
        archive = download(info["url"], work / "update.app.zip", progress=_progress(callback))
        status("Unpacking…")
        subprocess.run(["ditto", "-x", "-k", str(archive), str(work / "new")], check=True)
        new_app = work / "new" / macinstall.APP_NAME
        # Copy next to the old app first (same volume), then swap with an instant rename,
        # so the app is never half-copied even if this is interrupted.
        script = ('while kill -0 "$0" 2>/dev/null; do sleep 0.5; done; '
                  'rm -rf "$1.new" && ditto "$2" "$1.new" && xattr -dr com.apple.quarantine "$1.new" '
                  '&& rm -rf "$1.old" && mv "$1" "$1.old" && mv "$1.new" "$1" && rm -rf "$1.old"'
                  + ('; open "$1"' if relaunch else ''))
        subprocess.Popen(["/bin/sh", "-c", script, str(os.getpid()), str(target), str(new_app)],
                         start_new_session=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return "restarting"

    # Windows: the new release .exe installs itself over the old one after we exit
    exe = download(info["url"], work / f"JaceLauncher-{info['version']}-setup.exe", progress=_progress(callback))
    install_dir = target.parent
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    args = [str(exe), "--apply-update", str(install_dir), "--wait-pid", str(os.getpid()), *extra_args]
    if not relaunch:
        args.append("--no-relaunch")
    subprocess.Popen(args, creationflags=flags, close_fds=True, cwd=str(work), env=_clean_env())
    return "restarting"
