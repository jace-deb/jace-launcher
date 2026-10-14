"""The official Minecraft Bedrock and Minecraft Education apps on Windows and macOS.

Windows: Bedrock is "Minecraft for Windows" from the Microsoft Store / Xbox app (it's bought
there, so Jace Launcher opens its Store page); Minecraft Education is installed silently from
Microsoft's own installer (aka.ms/downloadmee-desktopApp). macOS: Minecraft Education comes
from Microsoft's .dmg (aka.ms/meeclientmacos) and goes into Applications.

Both apps keep their worlds in their own folders, so every instance of one shares them.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from jace.config import DATA_DIR
from jace.net import download, session

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
HOME = Path.home()

EDU_WIN_URL = "https://aka.ms/downloadmee-desktopApp"
EDU_MAC_URL = "https://aka.ms/meeclientmacos"
BEDROCK_STORE = "ms-windows-store://pdp/?ProductId=9NBLGGH2JHXJ"        # Minecraft for Windows
APPX = {"bedrock": "Microsoft.MinecraftUWP", "education": "*MinecraftEducation*"}
NAMES = {"bedrock": "Minecraft for Windows", "education": "Minecraft Education"}
PROCESSES = {"bedrock": ["Minecraft.Windows"], "education": ["Minecraft.Windows", "MinecraftEducation"]}
MAC_STATE = DATA_DIR / "education-mac.json"


class OfficialError(Exception):
    pass


def _no_window() -> dict:
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if IS_WIN else {}


def _ps(script: str, timeout=60) -> str:
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                            "-Command", script], capture_output=True, text=True, timeout=timeout, **_no_window())
        return r.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _q(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


# --- what's installed ----------------------------------------------------------------------

def win_package(kind: str) -> dict | None:
    """{name, version, location, aumid} of the Store / MSIX app, or None."""
    out = _ps(f"""$p = Get-AppxPackage -Name {_q(APPX[kind])} | Sort-Object Version -Descending | Select-Object -First 1
if ($p) {{
  $id = (Get-AppxPackageManifest $p).Package.Applications.Application | Select-Object -First 1 -ExpandProperty Id
  @{{name=$p.Name; version=$p.Version.ToString(); location=$p.InstallLocation; aumid=$p.PackageFamilyName + '!' + $id}} | ConvertTo-Json -Compress
}}""")
    try:
        return json.loads(out) if out else None
    except ValueError:
        return None


def win_education() -> dict | None:
    """Microsoft's Minecraft Education installer (an MSI) in Programs and Features: {version, location, exe}."""
    import winreg
    keys = [(winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall")]
    for hive, path in keys:
        try:
            root = winreg.OpenKey(hive, path)
        except OSError:
            continue
        with root:
            for i in range(winreg.QueryInfoKey(root)[0]):
                try:
                    with winreg.OpenKey(root, winreg.EnumKey(root, i)) as k:
                        name = winreg.QueryValueEx(k, "DisplayName")[0]
                        if name != "Minecraft Education":
                            continue
                        loc = Path(winreg.QueryValueEx(k, "InstallLocation")[0])
                        version = winreg.QueryValueEx(k, "DisplayVersion")[0]
                except OSError:
                    continue
                exes = [e for e in loc.glob("*.exe") if not re.search(r"unins|icon|crash|setup|update", e.name, re.I)]
                if exes:
                    exe = max(exes, key=lambda e: e.stat().st_size)      # the game, not a helper
                    return {"version": version, "location": str(loc), "exe": str(exe)}
    return None


def mac_app() -> Path | None:
    try:                                         # where Jace Launcher installed it
        app = Path(json.loads(MAC_STATE.read_text())["app"])
        if app.is_dir():
            return app
    except (OSError, ValueError, KeyError):
        pass
    for d in (Path("/Applications"), HOME / "Applications"):
        for pattern in ("minecraft-edu*.app", "Minecraft*Education*.app"):
            for app in sorted(d.glob(pattern)):
                return app
    return None


def installed(kind: str) -> bool:
    if IS_WIN:
        return (kind == "education" and win_education() is not None) or win_package(kind) is not None
    if IS_MAC and kind == "education":
        return mac_app() is not None
    return False


def _latest(url: str) -> tuple[str, str]:
    """(download URL, version) behind one of Microsoft's aka.ms links."""
    try:
        r = session.head(url, allow_redirects=True, timeout=30)
        final = r.url
    except Exception as e:  # noqa: BLE001
        raise OfficialError("Couldn't reach Microsoft's download server. Check your internet connection.") from e
    m = re.search(r"(\d+(?:\.\d+){2,3})\.(?:exe|dmg)$", final)
    return final, (m.group(1) if m else "")


def _download(url: str, dest: Path, status, what: str):
    last = [0.0]

    def progress(done, total):
        if total and time.time() - last[0] > 0.5:
            last[0] = time.time()
            status(f"Downloading {what}… {done * 100 // total}% ({done // 1_000_000} / {total // 1_000_000} MB)")
    download(url, dest, progress=progress)


# --- install / update ----------------------------------------------------------------------

def ensure(kind: str, status=print):
    """Make sure the official app is installed (and, for Education, up to date)."""
    if IS_WIN and kind == "bedrock":
        if not installed("bedrock"):
            _wait_for_store_install(status)
    elif kind == "education" and IS_WIN:
        _education_windows(status)
    elif kind == "education" and IS_MAC:
        _education_mac(status)
    else:
        raise OfficialError("Not available on this computer")


def _wait_for_store_install(status, timeout=3600):
    os.startfile(BEDROCK_STORE)                  # noqa: S606 - opens the Microsoft Store page
    status("Get Minecraft for Windows in the Microsoft Store window (it's bought with your Microsoft account)…")
    end = time.time() + timeout
    while time.time() < end:
        time.sleep(5)
        if installed("bedrock"):
            status("Minecraft for Windows installed")
            return
    raise OfficialError("Minecraft for Windows wasn't installed. Install it from the Microsoft Store or the Xbox "
                        "app, then press Play again.")


def _education_windows(status):
    pkg = win_education() or win_package("education")
    try:
        url, latest = _latest(EDU_WIN_URL)
    except OfficialError:
        if pkg:
            return                               # offline: play what's installed
        raise
    if pkg and (not latest or _vkey(pkg["version"]) >= _vkey(latest)):
        return
    with tempfile.TemporaryDirectory() as tmp:
        exe = Path(tmp) / Path(url).name
        _download(url, exe, status, "Minecraft Education" + (" (update)" if pkg else ""))
        status("Installing Minecraft Education…")
        try:
            code = subprocess.run([str(exe), "/quiet", "/norestart"], timeout=1200, **_no_window()).returncode
        except subprocess.TimeoutExpired:
            code = "timed out"
        if not installed("education") and not os.environ.get("JACE_NO_INTERACTIVE"):
            status("Finish installing Minecraft Education in its installer window…")
            subprocess.run([str(exe)])           # the normal installer, if the quiet install didn't work
    if not installed("education"):
        raise OfficialError(f"Minecraft Education didn't install (quiet installer: {code}).")
    status("Minecraft Education installed")


def _education_mac(status):
    app = mac_app()
    state = {}
    try:
        state = json.loads(MAC_STATE.read_text())
    except (OSError, ValueError):
        pass
    try:
        url, latest = _latest(EDU_MAC_URL)
    except OfficialError:
        if app:
            return
        raise
    if app and (not latest or not state or state.get("version") == latest):
        if not state:                            # installed by hand: take it as current from now on
            _save_mac_state({"version": latest, "app": str(app)})
        return
    with tempfile.TemporaryDirectory() as tmp:
        dmg = Path(tmp) / "MinecraftEducation.dmg"
        _download(url, dmg, status, "Minecraft Education" + (" (update)" if app else ""))
        status("Installing Minecraft Education…")
        mnt = Path(tmp) / "mnt"
        mnt.mkdir()
        r = subprocess.run(["hdiutil", "attach", "-nobrowse", "-readonly", "-noautoopen", "-mountpoint", str(mnt),
                            str(dmg)], capture_output=True, text=True)
        if r.returncode != 0:
            raise OfficialError("Couldn't open the Minecraft Education download:\n" + r.stderr[-300:])
        try:
            src = next(mnt.glob("*.app"), None)
            if not src:
                raise OfficialError("The Minecraft Education download has no app in it")
            apps = Path("/Applications")
            dest_dir = apps if os.access(apps, os.W_OK) else HOME / "Applications"
            dest_dir.mkdir(exist_ok=True)
            dest = (app.parent if app else dest_dir) / src.name
            if app and app != dest:
                shutil.rmtree(app, ignore_errors=True)
            if dest.exists():
                shutil.rmtree(dest, ignore_errors=True)
            subprocess.run(["ditto", str(src), str(dest)], check=True)
            status(f"Installed {dest}")
        finally:
            subprocess.run(["hdiutil", "detach", str(mnt), "-force"], capture_output=True)
    _save_mac_state({"version": latest, "app": str(dest)})
    status("Minecraft Education installed")


def _save_mac_state(state: dict):
    MAC_STATE.parent.mkdir(parents=True, exist_ok=True)
    MAC_STATE.write_text(json.dumps(state))


def _vkey(v: str):
    return tuple(int(x) for x in re.findall(r"\d+", v))


# --- launching -----------------------------------------------------------------------------

def launch_command(kind: str) -> list[str]:
    """A command that starts the official app and keeps running until the game is closed."""
    if IS_MAC:
        app = mac_app()
        if not app:
            raise OfficialError("Minecraft Education isn't installed")
        return ["open", "-W", "-n", str(app)]
    if kind == "education" and (edu := win_education()):
        return [edu["exe"]]                      # Microsoft's installer: the game's own .exe
    pkg = win_package(kind)
    if not pkg:
        raise OfficialError(f"{NAMES[kind]} isn't installed")
    names = ",".join(_q(n) for n in PROCESSES[kind])
    script = f"""$loc = {_q(pkg.get('location') or '')}
$before = @(Get-Process | ForEach-Object Id)
Start-Process explorer.exe -ArgumentList ('shell:AppsFolder\\' + {_q(pkg['aumid'])})
$p = $null
for ($i = 0; $i -lt 180 -and -not $p; $i++) {{
  Start-Sleep -Seconds 1
  $p = Get-Process | Where-Object {{ ($_.ProcessName -in @({names})) -or ($loc -and $_.Path -and $_.Path.StartsWith($loc, 'OrdinalIgnoreCase')) }} | Select-Object -First 1
}}
if (-not $p) {{ Write-Output 'Minecraft did not start'; exit 1 }}
Write-Output ('Started ' + $p.ProcessName + ' (' + {_q(pkg['version'])} + ')')
$p.WaitForExit()
Write-Output 'Minecraft closed'"""
    return ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script]
