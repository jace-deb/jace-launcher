"""Minecraft Education instances on Linux, through the official Android Emulator.

Minecraft Education's Android app runs in Google's Android Emulator (from the Android
SDK) with a "Google Play" system image, so the Play Store works and is certified.
Everything lives in Jace Launcher's data folder: no root, no password. It needs KVM
(/dev/kvm), which most Linux desktops allow for the logged-in user.

Windowed play is the emulator's own window; full screen runs it inside Gamescope (-f).
Using the SDK means accepting Google's Android SDK License - the user does that in the
Setup tab before anything is downloaded.

Signing in needs a Microsoft 365 Education (school) account, or another Minecraft
Education license; that happens inside the app.
"""
import os
import re
import shutil
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path

from jace.config import DATA_DIR, GAME_ROOT
from jace.net import download

PACKAGES = {"Minecraft Education": "com.mojang.minecraftedu",
            "Minecraft Education Preview": "com.mojang.minecraftedu_preview"}
PLAY_STORE = "com.android.vending"

SDK = DATA_DIR / "android-sdk"
AVD_HOME = DATA_DIR / "android-avd"
AVD = "jace-education"
IMAGE = "system-images;android-34;google_apis_playstore;x86_64"     # Android 14 with Google Play
DEVICE = "pixel_tablet"                                               # landscape, like Minecraft
REPO = "https://dl.google.com/android/repository/"
LICENSE_URL = "https://developer.android.com/studio/terms"
DOWNLOAD_MB = 2200

SDKMANAGER = SDK / "cmdline-tools" / "latest" / "bin" / "sdkmanager"
AVDMANAGER = SDK / "cmdline-tools" / "latest" / "bin" / "avdmanager"
EMULATOR = SDK / "emulator" / "emulator"
ADB = SDK / "platform-tools" / "adb"


class EducationError(Exception):
    pass


def _clean_env() -> dict:
    from jace.bedrock import _clean_env as clean
    env = clean()
    env.update({"ANDROID_SDK_ROOT": str(SDK), "ANDROID_HOME": str(SDK), "ANDROID_AVD_HOME": str(AVD_HOME)})
    java = _java(install=False)
    if java:
        env["JAVA_HOME"] = str(Path(java).resolve().parent.parent)
    return env


def _run(cmd, timeout=30, **kw) -> subprocess.CompletedProcess:
    try:
        return subprocess.run([str(c) for c in cmd], capture_output=True, text=True, timeout=timeout,
                              env=_clean_env(), **kw)
    except (OSError, subprocess.TimeoutExpired) as e:
        return subprocess.CompletedProcess(cmd, 1, "", str(e))


def _java(install=True) -> str | None:
    """A Java 17+ for Google's SDK tools: one of the runtimes Jace Launcher downloads for Minecraft."""
    found = sorted((GAME_ROOT / "runtime").glob("*/*/*/bin/java"), reverse=True)
    if found:
        return str(found[0])
    if not install:
        return shutil.which("java")
    import minecraft_launcher_lib as mll
    mll.runtime.install_jvm_runtime("java-runtime-delta", str(GAME_ROOT))     # Java 21
    found = sorted((GAME_ROOT / "runtime").glob("*/*/*/bin/java"), reverse=True)
    return str(found[0]) if found else None


# --- what's set up ---------------------------------------------------------------------

def kvm_ok() -> bool:
    return os.access("/dev/kvm", os.R_OK | os.W_OK)


def status() -> dict:
    image = SDK / "system-images" / "android-34" / "google_apis_playstore" / "x86_64" / "system.img"
    return {
        "kvm": kvm_ok(),
        "tools": SDKMANAGER.is_file(),
        "emulator": EMULATOR.is_file() and ADB.is_file(),
        "image": image.is_file(),
        "device": (AVD_HOME / f"{AVD}.avd").is_dir(),
        "gamescope": bool(shutil.which("gamescope")),
    }


def problem(fullscreen=False) -> str | None:
    """Why Education can't start yet, in plain words (None = ready)."""
    s = status()
    if not s["kvm"]:
        return ("The Android emulator needs KVM (hardware virtualization). Turn on virtualization (VT-x / AMD-V) "
                "in your BIOS, and make sure /dev/kvm is usable (on most distros: sudo usermod -aG kvm $USER, "
                "then log out and back in).")
    if not (s["tools"] and s["emulator"] and s["image"] and s["device"]):
        return "The Android emulator isn't set up yet. Open the instance → Setup → Set up Android emulator."
    if fullscreen and not s["gamescope"]:
        return "Full screen needs Gamescope (install it with your package manager, e.g. sudo pacman -S gamescope), " \
               "or turn off Full screen."
    return None


def running() -> bool:
    return ADB.is_file() and "emulator-" in _run([ADB, "devices"], timeout=10).stdout


# --- setup ------------------------------------------------------------------------------

def _latest_tools_url() -> str:
    from jace.net import session
    xml = session.get(REPO + "repository2-3.xml", timeout=30).text
    m = re.search(r'<remotePackage path="cmdline-tools;latest">(.*?)</remotePackage>', xml, re.S)
    names = re.findall(r"<url>(commandlinetools-linux-[^<]+)</url>", m.group(1) if m else xml)
    if not names:
        raise EducationError("Couldn't find Google's Android command-line tools download")
    return REPO + names[-1]


def setup(status_cb=print, license_accepted=False):
    """Download the emulator, Android 14 with Google Play, and make the virtual tablet.
    Only call with license_accepted=True after the user accepted the Android SDK License."""
    if not license_accepted:
        raise EducationError("Accept the Android SDK License first")
    if not kvm_ok():
        raise EducationError(problem())
    SDK.mkdir(parents=True, exist_ok=True)
    AVD_HOME.mkdir(parents=True, exist_ok=True)
    status_cb("Getting Java for Google's tools…")
    if not _java():
        raise EducationError("Couldn't get Java for the Android tools")
    if not SDKMANAGER.is_file():
        url = _latest_tools_url()
        status_cb("Downloading Android command-line tools…")
        with tempfile.TemporaryDirectory() as tmp:
            z = Path(tmp) / "tools.zip"
            download(url, z)
            with zipfile.ZipFile(z) as zf:
                zf.extractall(tmp)
            dest = SDK / "cmdline-tools" / "latest"
            shutil.rmtree(dest, ignore_errors=True)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(Path(tmp) / "cmdline-tools"), str(dest))
        for f in (SDK / "cmdline-tools" / "latest" / "bin").iterdir():
            f.chmod(0o755)
    # the user accepted the license in Jace Launcher, so tell sdkmanager
    _run([SDKMANAGER, f"--sdk_root={SDK}", "--licenses"], timeout=120, input="y\n" * 20)
    status_cb(f"Downloading the Android emulator and Android 14 with Google Play (about {DOWNLOAD_MB // 1000} GB)…")
    proc = subprocess.Popen([str(SDKMANAGER), f"--sdk_root={SDK}", "platform-tools", "emulator", IMAGE],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.PIPE,
                            text=True, env=_clean_env())
    proc.stdin.write("y\n" * 5)
    proc.stdin.close()
    last = ""
    buf = ""
    while True:
        ch = proc.stdout.read(1)
        if not ch:
            break
        if ch in "\r\n":
            m = re.search(r"(\d+)%\s*(.*)", buf)
            if m and m.group(0) != last:
                last = m.group(0)
                status_cb(f"{m.group(1)}%  {m.group(2).strip()[:70]}")
            buf = ""
        else:
            buf += ch
    if proc.wait() != 0 or not status()["image"]:
        raise EducationError("Downloading the Android emulator failed. Check your internet connection and disk "
                             "space (it needs about 6 GB free), then try again.")
    status_cb("Creating the virtual tablet…")
    r = _run([AVDMANAGER, "create", "avd", "-n", AVD, "-k", IMAGE, "-d", DEVICE, "--force"], timeout=180,
             input="no\n")
    if r.returncode != 0:
        r = _run([AVDMANAGER, "create", "avd", "-n", AVD, "-k", IMAGE, "--force"], timeout=180, input="no\n")
    if r.returncode != 0:
        raise EducationError("Couldn't create the virtual device:\n" + (r.stderr or r.stdout)[-400:])
    cfg = AVD_HOME / f"{AVD}.avd" / "config.ini"
    lines = [ln for ln in cfg.read_text().splitlines()
             if not ln.split("=")[0].strip() in ("hw.keyboard", "hw.gpu.enabled", "hw.gpu.mode", "hw.ramSize",
                                                  "disk.dataPartition.size", "hw.initialOrientation")]
    lines += ["hw.keyboard=yes", "hw.gpu.enabled=yes", "hw.gpu.mode=auto", "hw.ramSize=4096",
              "disk.dataPartition.size=8G", "hw.initialOrientation=landscape"]
    cfg.write_text("\n".join(lines) + "\n")
    status_cb("Ready! Open Google Play, sign in and install Minecraft Education.")


def remove_all():
    """Delete the emulator, Android image and virtual tablet (frees several GB)."""
    if running():
        _run([ADB, "emu", "kill"])
    shutil.rmtree(SDK, ignore_errors=True)
    shutil.rmtree(AVD_HOME, ignore_errors=True)


# --- launching ---------------------------------------------------------------------------

def _boot_and_open(package: str | None, headless=False) -> str:
    """Shell script: start the emulator, wait for Android, open package; ends when the window closes."""
    emu = f'"{EMULATOR}" -avd {AVD} -gpu auto -no-boot-anim -no-audio' if headless else \
          f'"{EMULATOR}" -avd {AVD} -gpu auto -no-boot-anim'
    if headless:
        emu += " -no-window"
    script = (f"{emu} & e=$!; "
              f'"{ADB}" wait-for-device; '
              f'for i in $(seq 1 150); do [ "$("{ADB}" shell getprop sys.boot_completed 2>/dev/null | tr -d "\\r")" = 1 ] && break; sleep 2; done; ')
    if package:
        script += f'"{ADB}" shell monkey -p {package} -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1; '
    return script + "wait $e"


def launch_command(package: str, fullscreen: bool = False, width: int = 0, height: int = 0) -> list[str]:
    """The emulator (in full-screen Gamescope if asked), opening <package>."""
    why = problem(fullscreen)
    if why:
        raise EducationError(why)
    cmd = ["sh", "-c", _boot_and_open(package)]
    if fullscreen:
        args = ["gamescope", "-f"]
        if width > 0 and height > 0:
            args += ["-W", str(width), "-H", str(height)]
        # inside Gamescope the emulator (a Qt app) draws through Gamescope's X server
        return [*args, "--", "env", "QT_QPA_PLATFORM=xcb", *cmd]
    return cmd


def launch_env() -> dict:
    return _clean_env()


def install_apk(path: str | Path, status_cb=print):
    """Install a Minecraft Education APK you have."""
    why = problem()
    if why:
        raise EducationError(why)
    started = False
    if not running():
        status_cb("Starting Android in the background…")
        subprocess.Popen(["sh", "-c", _boot_and_open(None, headless=True)], start_new_session=True,
                         env=_clean_env(), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
        started = True
        end = time.time() + 300
        while time.time() < end:
            if _run([ADB, "shell", "getprop", "sys.boot_completed"], timeout=10).stdout.strip() == "1":
                break
            time.sleep(3)
        else:
            raise EducationError("Android didn't start in time. Try again.")
    status_cb("Installing the app…")
    r = _run([ADB, "install", "-r", str(path)], timeout=600)
    if started:
        _run([ADB, "emu", "kill"])
    if r.returncode != 0 or "Success" not in r.stdout:
        raise EducationError("Couldn't install it:\n" + (r.stderr or r.stdout)[-400:])


def stop_session():
    if running():
        _run([ADB, "emu", "kill"], timeout=30)
