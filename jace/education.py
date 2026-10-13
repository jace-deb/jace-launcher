"""Minecraft Education instances on Linux, through Waydroid.

Minecraft Education's Android app runs in Waydroid (Android in a container). Waydroid's
full Android screen is shown in Cage, a small kiosk compositor, as its own window; for
full screen, that Cage runs inside Gamescope (-f). Setting Waydroid up needs root once
(installing packages, `waydroid init`), so Jace Launcher opens a terminal with the
commands and you type your password there - it never handles it.

Signing in needs a Microsoft 365 Education (school) account, or another Minecraft
Education license; that happens inside the app.
"""
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

PACKAGES = {"Minecraft Education": "com.mojang.minecraftedu",
            "Minecraft Education Preview": "com.mojang.minecraftedu_preview"}
PLAY_STORE = "com.android.vending"
WAYDROID_CFG = Path("/var/lib/waydroid/waydroid.cfg")


class EducationError(Exception):
    pass


def _run(cmd, timeout=20) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=_clean_env())
    except (OSError, subprocess.TimeoutExpired) as e:
        return subprocess.CompletedProcess(cmd, 1, "", str(e))


def _clean_env() -> dict:
    from jace.bedrock import _clean_env as clean
    return clean()


# --- what's set up ---------------------------------------------------------------------

def status() -> dict:
    """{waydroid, cage, gamescope, initialized, container, wayland} - what's ready."""
    have = {name: bool(shutil.which(name)) for name in ("waydroid", "cage", "gamescope")}
    have["initialized"] = WAYDROID_CFG.is_file()
    have["container"] = (have["waydroid"] and
                         _run(["systemctl", "is-active", "waydroid-container"]).stdout.strip() == "active")
    have["wayland"] = bool(os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY"))
    return have


def problem(fullscreen=False) -> str | None:
    """Why Education can't start yet, in plain words (None = ready)."""
    s = status()
    if not s["waydroid"] or not s["cage"] or not s["initialized"]:
        return "Waydroid isn't set up yet. Open the instance → Setup → Set up Waydroid."
    if not s["container"]:
        return "Waydroid's background service isn't running. Open the instance → Setup → Set up Waydroid."
    if fullscreen and not s["gamescope"]:
        return "Full screen needs Gamescope. Run Setup again (it installs it), or turn off Full screen."
    return None


def installed_apps() -> set[str] | None:
    """Android packages installed in Waydroid, or None if we can't tell (no session running)."""
    r = _run(["waydroid", "app", "list"], timeout=15)
    if r.returncode != 0 or "packageName" not in r.stdout:
        return None
    return {line.split(":", 1)[1].strip() for line in r.stdout.splitlines() if line.startswith("packageName:")}


# --- setup (needs root once: done in a terminal by the user) -----------------------------

SETUP_SCRIPT = r"""#!/usr/bin/env bash
# Jace Launcher: set up Waydroid for Minecraft Education. You'll be asked for your password.
set -e
echo "== Installing Waydroid, Cage and Gamescope"
if command -v pacman >/dev/null; then sudo pacman -S --needed waydroid cage gamescope
elif command -v apt >/dev/null; then sudo apt install -y waydroid cage gamescope
elif command -v dnf >/dev/null; then sudo dnf install -y waydroid cage gamescope
elif command -v zypper >/dev/null; then sudo zypper install -y waydroid cage gamescope
else echo "Install waydroid, cage and gamescope with your package manager, then run this again."; exit 1; fi
if [ ! -f /var/lib/waydroid/waydroid.cfg ]; then
  echo "== Downloading Android with Google Play (about 1 GB)"
  sudo waydroid init -s GAPPS
fi
echo "== Starting Waydroid's service"
sudo systemctl enable --now waydroid-container
echo
echo "Done! Back in Jace Launcher: open Google Play, sign in, and install Minecraft Education."
echo "If Play says this device isn't certified, follow https://docs.waydro.id/faq/google-play-certification"
read -rp "Press Enter to close this window."
"""


def open_setup_terminal():
    """Open a terminal running the setup script (the user types their password there)."""
    script = Path(tempfile.gettempdir()) / "jace-waydroid-setup.sh"
    script.write_text(SETUP_SCRIPT)
    script.chmod(0o755)
    for term, args in (("kgx", ["--"]), ("gnome-terminal", ["--"]), ("konsole", ["-e"]), ("ptyxis", ["--"]),
                       ("kitty", []), ("alacritty", ["-e"]), ("foot", []), ("xfce4-terminal", ["-x"]),
                       ("xterm", ["-e"])):
        if shutil.which(term):
            subprocess.Popen([term, *args, "bash", str(script)], start_new_session=True, env=_clean_env(),
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
    raise EducationError(f"Couldn't find a terminal app. Run this yourself: bash {script}")


def _ensure_session(timeout=90):
    """Start Waydroid's Android session (in the background) and wait until it's running."""
    if "RUNNING" in _run(["waydroid", "status"]).stdout:
        return
    subprocess.Popen(["waydroid", "session", "start"], start_new_session=True, env=_clean_env(),
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    end = time.time() + timeout
    while time.time() < end:
        if "RUNNING" in _run(["waydroid", "status"]).stdout:
            return
        time.sleep(2)
    raise EducationError("Waydroid didn't start. Try Setup → Set up Waydroid again.")


def install_apk(path: str | Path, status_cb=print):
    """Install a Minecraft Education APK you have into Waydroid."""
    why = problem()
    if why:
        raise EducationError(why)
    status_cb("Starting Waydroid…")
    _ensure_session()
    status_cb("Installing the app…")
    r = _run(["waydroid", "app", "install", str(path)], timeout=300)
    if r.returncode != 0:
        raise EducationError("Waydroid couldn't install it:\n" + (r.stderr or r.stdout)[-400:])


# --- launching ---------------------------------------------------------------------------

def launch_command(package: str, fullscreen: bool = False, width: int = 0, height: int = 0) -> list[str]:
    """Waydroid's Android screen in a Cage window (inside full-screen Gamescope if asked),
    opening <package>. The session stops when the window closes."""
    why = problem(fullscreen)
    if why:
        raise EducationError(why)
    inner = ("waydroid show-full-ui & ui=$!; "
             "for i in $(seq 1 60); do waydroid status 2>/dev/null | grep -q RUNNING && break; sleep 2; done; "
             f"sleep 4; waydroid app launch {package}; wait $ui")
    cage = ["cage", "-d", "--", "sh", "-c", inner]
    if fullscreen:
        args = ["gamescope", "-f", "--expose-wayland"]
        if width > 0 and height > 0:
            args += ["-W", str(width), "-H", str(height)]
        return [*args, "--", *cage]
    return cage


def stop_session():
    _run(["waydroid", "session", "stop"], timeout=30)
