"""Minecraft Education instances on Linux, through the official Android Emulator.

Minecraft Education's Android app runs in Google's Android Emulator (from the Android
SDK) with a "Google Play" system image, so the Play Store works and is certified.
Everything lives in Jace Launcher's data folder: no root, no password. It needs KVM
(/dev/kvm), which most Linux desktops allow for the logged-in user.

The emulator runs without a window of its own (no toolbar, no "not responding" prompts while
Android boots); scrcpy shows Android's screen in a plain window, or full screen. Android draws
with ANGLE on the host's Vulkan (the emulator's GuestAngle feature): with the default OpenGL ES
3.0 translator Minecraft Education's renderer shows only a black screen.
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

# scrcpy (Apache-2.0) shows the emulator's screen: github.com/Genymobile/scrcpy
SCRCPY_VERSION = "5.0.1"
SCRCPY_URL = (f"https://github.com/Genymobile/scrcpy/releases/download/v{SCRCPY_VERSION}/"
              f"scrcpy-linux-x86_64-v{SCRCPY_VERSION}.tar.gz")
SCRCPY_SHA256 = "9f969d30cc574816077edecda65719c1c70b0aee1df1ba5fa00779ac07b8fd6e"
SCRCPY_DIR = DATA_DIR / "scrcpy"
SCRCPY = SCRCPY_DIR / "scrcpy"
EMULATOR_ARGS = ["-avd", AVD, "-no-window", "-gpu", "host", "-feature", "GuestAngle", "-no-boot-anim"]


class EducationError(Exception):
    pass


license_accepted = False        # set by the UI once the user accepted the Android SDK License


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
        "scrcpy": SCRCPY.is_file(),
    }


def set_up() -> bool:
    s = status()
    return all(s[k] for k in ("tools", "emulator", "image", "device"))


def problem(fullscreen=False) -> str | None:   # (fullscreen: kept for callers; scrcpy needs nothing extra)
    """Why Education can't start yet, in plain words (None = ready)."""
    s = status()
    if not s["kvm"]:
        return ("The Android emulator needs KVM (hardware virtualization). Turn on virtualization (VT-x / AMD-V) "
                "in your BIOS, and make sure /dev/kvm is usable (on most distros: sudo usermod -aG kvm $USER, "
                "then log out and back in).")
    if not set_up():
        return "The Android emulator isn't set up yet. Press Play (or Setup → Set up Android emulator)."
    return None


def running() -> bool:
    return ADB.is_file() and "emulator-" in _run([ADB, "devices"], timeout=10).stdout


# --- setup ------------------------------------------------------------------------------

def _latest_tools_url() -> str:
    from jace.net import session
    xml = None
    for attempt in range(4):                   # ride out a short network / DNS hiccup
        try:
            xml = session.get(REPO + "repository2-3.xml", timeout=30).text
            break
        except Exception:  # noqa: BLE001
            if attempt == 3:
                raise EducationError("Couldn't reach Google's download server (dl.google.com). Check your "
                                     "internet connection and try again.")
            time.sleep(3)
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
    ensure_scrcpy(status_cb)
    status_cb("Ready! Press Play: Minecraft Education installs from Google Play the first time.")


def ensure_scrcpy(status_cb=print):
    """Download scrcpy (the window that shows Android) if it isn't here yet."""
    if SCRCPY.is_file():
        return
    import hashlib
    import tarfile
    status_cb("Downloading scrcpy (the game window)…")
    with tempfile.TemporaryDirectory() as tmp:
        tgz = Path(tmp) / "scrcpy.tar.gz"
        download(SCRCPY_URL, tgz)
        if hashlib.sha256(tgz.read_bytes()).hexdigest() != SCRCPY_SHA256:
            raise EducationError("The scrcpy download was corrupted. Try again.")
        with tarfile.open(tgz) as tf:
            tf.extractall(tmp, filter="data")
        src = next(Path(tmp).glob("scrcpy-linux-*"))
        shutil.rmtree(SCRCPY_DIR, ignore_errors=True)
        shutil.move(str(src), str(SCRCPY_DIR))
    SCRCPY.chmod(0o755)


def remove_all():
    """Delete the emulator, Android image and virtual tablet (frees several GB)."""
    if running():
        _run([ADB, "emu", "kill"])
    shutil.rmtree(SDK, ignore_errors=True)
    shutil.rmtree(AVD_HOME, ignore_errors=True)


# --- launching ---------------------------------------------------------------------------

def _adb(*args, timeout=30) -> subprocess.CompletedProcess:
    return _run([ADB, *args], timeout=timeout)


def _host_ram_mb() -> int:
    try:
        return int(re.search(r"MemTotal:\s+(\d+)", Path("/proc/meminfo").read_text()).group(1)) // 1024
    except (OSError, AttributeError):
        return 8192


def tune_avd():
    """Size the virtual tablet for this PC: a big screen and lots of RAM on a small laptop means swapping
    and slow video encoding (the main causes of lag). Rendering 1280x800 is about 4x less work than 2560x1600."""
    cfg = AVD_HOME / f"{AVD}.avd" / "config.ini"
    if not cfg.is_file():
        return
    cores, ram = os.cpu_count() or 4, _host_ram_mb()
    big = cores >= 8 and ram >= 15000
    want = {
        "hw.cpu.ncore": str(max(2, min(8, cores - 2))),
        "hw.ramSize": str(4096 if ram >= 15000 else 3072 if ram >= 11000 else 2560),
        "hw.lcd.width": "1920" if big else "1280",
        "hw.lcd.height": "1200" if big else "800",
        "hw.lcd.density": "240" if big else "160",
        "hw.gpu.enabled": "yes", "hw.gpu.mode": "host", "hw.keyboard": "yes",
        "hw.initialOrientation": "landscape", "vm.heapSize": "256M",
    }
    lines = cfg.read_text().splitlines()
    have = {ln.split("=", 1)[0].strip(): ln.split("=", 1)[1].strip() for ln in lines if "=" in ln}
    if all(have.get(k) == v for k, v in want.items()):
        return
    lines = [ln for ln in lines if ln.split("=", 1)[0].strip() not in want] + [f"{k}={v}" for k, v in want.items()]
    cfg.write_text("\n".join(lines) + "\n")


def boot(status_cb=print):
    """Start Android in the background (no emulator window) and wait until it has booted."""
    if not running():
        tune_avd()
        status_cb("Starting Android…")
        log = open(DATA_DIR / "android-emulator.log", "w")
        subprocess.Popen([str(EMULATOR), *EMULATOR_ARGS], start_new_session=True, env=_clean_env(),
                         stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
    end = time.time() + 300
    _adb("wait-for-device", timeout=300)
    while _adb("shell", "getprop", "sys.boot_completed", timeout=10).stdout.strip() != "1":
        if time.time() > end:
            raise EducationError("Android didn't start in time. Try again (details: android-emulator.log in "
                                 "Jace Launcher's folder).")
        time.sleep(2)
    # no "isn't responding" / crash pop-ups, no "Viewing full screen" hint over the game
    _adb("shell", "settings", "put", "global", "hide_error_dialogs", "1")
    _adb("shell", "settings", "put", "secure", "immersive_mode_confirmations", "confirmed")
    for anim in ("window_animation_scale", "transition_animation_scale", "animator_duration_scale"):
        _adb("shell", "settings", "put", "global", anim, "0")


def app_installed(package: str) -> bool:
    return f"package:{package}" in _adb("shell", "pm", "list", "packages", package).stdout.split()


def google_signed_in() -> bool:
    return "type=com.google" in _adb("shell", "dumpsys", "account").stdout


def _scrcpy(title: str, *args) -> list[str]:
    return [str(SCRCPY), f"--window-title={title}", "--no-audio", "--stay-awake", "--disable-screensaver",
            "--max-fps=60", "--video-bit-rate=12M", *args]


def _scrcpy_env() -> dict:
    return {**_clean_env(), "ADB": str(ADB), "SCRCPY_SERVER_PATH": str(SCRCPY_DIR / "scrcpy-server")}


def _tap_install() -> bool:
    """Press Google Play's main Install button if it's on screen (the user is already signed in).
    The page can also list "Available on more devices" with Install buttons for *other* devices
    further down, so only the topmost one is ever pressed."""
    _adb("shell", "uiautomator", "dump", "/sdcard/jace-ui.xml", timeout=30)
    xml = _adb("shell", "cat", "/sdcard/jace-ui.xml", timeout=20).stdout
    if re.search(r'(?:text|content-desc)="(?:Open|Uninstall|Installing|Pending|Cancel)"', xml):
        return False                               # already installing / installed
    found = [tuple(map(int, m.groups())) for m in re.finditer(
        r'<node [^>]*?(?:text|content-desc)="Install"[^>]*?bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml)]
    if not found:
        return False
    x1, y1, x2, y2 = min(found, key=lambda b: b[1])
    _adb("shell", "input", "tap", str((x1 + x2) // 2), str((y1 + y2) // 2))
    return True


def ensure_app(package: str, status_cb=print, timeout: float = 1800):
    """Install Minecraft Education from Google Play if it isn't installed: Play opens on its page in a
    small window (sign in to Google there the first time) and Install is pressed for you."""
    if app_installed(package):
        return
    ensure_scrcpy(status_cb)
    _adb("shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", f"market://details?id={package}",
         PLAY_STORE)
    win = subprocess.Popen(_scrcpy("Google Play - Minecraft Education", "--window-width=960", "--window-height=600"),
                           start_new_session=True, env=_scrcpy_env(), stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        end, tapped = time.time() + timeout, False
        while time.time() < end:
            if app_installed(package):
                status_cb("Minecraft Education installed")
                time.sleep(3)                      # let Play finish
                return
            if win.poll() is not None:
                raise EducationError("The Google Play window was closed before Minecraft Education was installed. "
                                     "Press Play to try again.")
            if not google_signed_in():
                status_cb("Sign in to Google in the Google Play window…")
            else:
                status_cb("Installing Minecraft Education from Google Play…")
                if not tapped:
                    tapped = _tap_install()
            time.sleep(3)
        raise EducationError("Timed out waiting for Minecraft Education to install")
    finally:
        if win.poll() is None:
            win.terminate()


def prepare(package: str, status_cb=print, license_accepted=False):
    """Everything Play needs: the emulator (set up on first use), Android running, the app installed."""
    if not kvm_ok():
        raise EducationError(problem())
    if not set_up():
        setup(status_cb, license_accepted=license_accepted or globals()["license_accepted"])
    ensure_scrcpy(status_cb)
    boot(status_cb)
    ensure_app(package, status_cb)


def launch_command(package: str, fullscreen: bool = False, width: int = 0, height: int = 0) -> list[str]:
    """scrcpy showing Android with <package> started (call prepare() first). Closing it ends the session."""
    why = problem()
    if why:
        raise EducationError(why)
    args = [f"--start-app={package}", "--keyboard=uhid", "--mouse=uhid"]
    if fullscreen:
        args.append("--fullscreen")
    elif width > 0 and height > 0:
        args += [f"--window-width={width}", f"--window-height={height}"]
    return _scrcpy("Minecraft Education", *args)


def launch_env() -> dict:
    return _scrcpy_env()


def install_apk(path: str | Path, status_cb=print):
    """Install a Minecraft Education APK you have."""
    why = problem()
    if why:
        raise EducationError(why)
    started = not running()
    boot(status_cb)
    status_cb("Installing the app…")
    r = _run([ADB, "install", "-r", str(path)], timeout=600)
    if started:
        _adb("emu", "kill")
    if r.returncode != 0 or "Success" not in r.stdout:
        raise EducationError("Couldn't install it:\n" + (r.stderr or r.stdout)[-400:])


def open_play_store(status_cb=print):
    """Google Play in a small window, e.g. to sign in or update apps."""
    ensure_scrcpy(status_cb)
    boot(status_cb)
    _adb("shell", "monkey", "-p", PLAY_STORE, "-c", "android.intent.category.LAUNCHER", "1")
    return subprocess.Popen(_scrcpy("Google Play", "--window-width=960", "--window-height=600"),
                            start_new_session=True, env=_scrcpy_env(), stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def stop_session():
    if running():
        _run([ADB, "emu", "kill"], timeout=30)
