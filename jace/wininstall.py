"""Windows self-installer.

The release is one .exe (a PyInstaller "onefile" build). Starting a onefile app
unpacks the whole app to a temp folder every time, which is slow, so that .exe is
only used to install: it copies its unpacked files plus a small embedded
launcher (the "onedir" JaceLauncher.exe) into the install folder. The installed
app then starts fast. Shortcuts, the "Installed apps" entry and the terminal
command are optional.
"""
import ctypes
import os
import shutil
import subprocess
import sys
from pathlib import Path

from jace import APP_VERSION

APP_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\JaceLauncher"
EMBEDDED_DIR = "jace_setup"          # where the onedir launcher sits inside the onefile build
EXE_NAME = "JaceLauncher.exe"
NO_WINDOW = 0x08000000               # CREATE_NO_WINDOW

OPTIONS = [
    ("startmenu", "Add to the Start menu", True),
    ("desktop", "Create a desktop shortcut", True),
    ("apps", "Show in Windows \"Installed apps\" (so you can uninstall it from Windows Settings)", True),
    ("terminal", "Add the  jace-launcher  command to the terminal", False),
]


def running_exe() -> Path | None:
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return None
    return Path(sys.executable)


def is_setup_build() -> bool:
    """True for the downloaded onefile .exe, False for an installed copy."""
    exe = running_exe()
    if not exe:
        return False
    return (Path(sys._MEIPASS) / EMBEDDED_DIR / EXE_NAME).is_file()


def default_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "Programs" / "Jace Launcher"


def clean_env() -> dict:
    from jace.updater import _clean_env
    return _clean_env()


def _known_folder(csidl: int) -> Path:
    buf = ctypes.create_unicode_buffer(260)
    ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buf)
    return Path(buf.value)


def desktop_dir() -> Path:
    return _known_folder(0x10)        # CSIDL_DESKTOPDIRECTORY (follows OneDrive redirection)


def start_menu_dir() -> Path:
    return _known_folder(0x02)        # CSIDL_PROGRAMS


def shortcut_paths() -> list[Path]:
    return [start_menu_dir() / "Jace Launcher.lnk", desktop_dir() / "Jace Launcher.lnk"]


def make_shortcut(lnk: Path, exe: Path, args=(), icon: Path | None = None, description="Jace Launcher"):
    q = lambda p: str(p).replace("'", "''")  # noqa: E731 - PowerShell single-quote escaping
    arg_str = " ".join(f'"{a}"' for a in args)
    ps = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{q(lnk)}');"
          f"$s.TargetPath='{q(exe)}';$s.Arguments='{q(arg_str)}';$s.WorkingDirectory='{q(exe.parent)}';"
          f"$s.IconLocation='{q(icon or exe)},0';$s.Description='{q(description)}';$s.Save()")
    lnk.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", ps],
                   check=True, creationflags=NO_WINDOW, capture_output=True)


def _broadcast_env_change():
    result = ctypes.c_ulong()
    ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, "Environment", 0x0002, 5000, ctypes.byref(result))


def _user_path_edit(add: Path | None = None, remove: Path | None = None):
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_READ | winreg.KEY_WRITE) as k:
        try:
            value, kind = winreg.QueryValueEx(k, "Path")
        except FileNotFoundError:
            value, kind = "", winreg.REG_EXPAND_SZ
        parts = [p for p in value.split(";") if p]
        norm = lambda p: os.path.normcase(os.path.normpath(os.path.expandvars(p)))  # noqa: E731
        if remove:
            parts = [p for p in parts if norm(p) != norm(str(remove))]
        if add and norm(str(add)) not in map(norm, parts):
            parts.append(str(add))
        winreg.SetValueEx(k, "Path", 0, kind, ";".join(parts))
    _broadcast_env_change()


def _dir_size_kb(d: Path) -> int:
    return sum(f.stat().st_size for f in d.rglob("*") if f.is_file()) // 1024


def _register_app(exe: Path):
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, APP_KEY) as k:
        for name, val in (("DisplayName", "Jace Launcher"), ("DisplayVersion", APP_VERSION),
                          ("Publisher", "Jace"), ("DisplayIcon", f'"{exe}",0'),
                          ("InstallLocation", str(exe.parent)),
                          ("UninstallString", f'"{exe}" --uninstall-gui'),
                          ("QuietUninstallString", f'"{exe}" --uninstall'),
                          ("URLInfoAbout", "https://github.com/ququoqu/jace-launcher")):
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, val)
        for name, val in (("NoModify", 1), ("NoRepair", 1), ("EstimatedSize", _dir_size_kb(exe.parent))):
            winreg.SetValueEx(k, name, 0, winreg.REG_DWORD, val)


def _copy_tree(src: Path, dst: Path, status, skip: str | None = None):
    files = [f for f in src.rglob("*") if f.is_file() and not (skip and f.relative_to(src).parts[0] == skip)]
    for i, f in enumerate(files):
        if i % 250 == 0:
            status(f"Copying files… {i * 100 // max(1, len(files))}%")
        out = dst / f.relative_to(src)
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, out)


def install(target_dir: Path, options: dict, status=print) -> tuple[Path, list[str]]:
    target_dir = Path(target_dir).expanduser()
    target_dir.mkdir(parents=True, exist_ok=True)
    exe = target_dir / EXE_NAME
    internal = target_dir / "_internal"

    if is_setup_build():
        # stage the new files next to the old ones, then swap, so a failed copy
        # never leaves a half-installed app
        stage, old = target_dir / "_internal.new", target_dir / "_internal.old"
        shutil.rmtree(stage, ignore_errors=True)
        _copy_tree(Path(sys._MEIPASS), stage, status, skip=EMBEDDED_DIR)
        shutil.rmtree(old, ignore_errors=True)
        if internal.exists():
            internal.rename(old)
        stage.rename(internal)
        shutil.copy2(Path(sys._MEIPASS) / EMBEDDED_DIR / EXE_NAME, exe)
        shutil.rmtree(old, ignore_errors=True)
    else:
        src = running_exe().parent
        if src.resolve() != target_dir.resolve():
            _copy_tree(src, target_dir, status)

    parts = []
    if options.get("startmenu"):
        status("Adding to the Start menu")
        make_shortcut(shortcut_paths()[0], exe)
        parts.append("startmenu")
    if options.get("desktop"):
        status("Creating desktop shortcut")
        make_shortcut(shortcut_paths()[1], exe)
        parts.append("desktop")
    if options.get("apps"):
        status("Adding to Installed apps")
        _register_app(exe)
        parts.append("apps")
    if options.get("terminal"):
        status("Adding the 'jace-launcher' command")
        bin_dir = target_dir / "bin"
        bin_dir.mkdir(exist_ok=True)
        (bin_dir / "jace-launcher.cmd").write_text(f'@start "" "%~dp0..\\{EXE_NAME}" %*\r\n')
        _user_path_edit(add=bin_dir)
        parts.append("terminal")
    status("Done")
    return exe, parts


def relaunch(exe: Path, delete_after: Path | None = None):
    """Start the installed app; optionally delete the downloaded setup .exe once we exit."""
    subprocess.Popen([str(exe)], cwd=str(exe.parent), env=clean_env(), close_fds=True,
                     creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
    if delete_after and delete_after.resolve() != exe.resolve():
        _after_exit(f'del /f /q "{delete_after}"')


def _after_exit(command: str):
    """Run a cmd.exe command a few seconds after we exit (files are unlocked by then)."""
    subprocess.Popen(f'cmd /c timeout /t 3 /nobreak >nul & {command}', cwd=os.environ.get("TEMP", "C:\\"),
                     creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | NO_WINDOW,
                     close_fds=True)


def uninstall(install_dir: Path | None):
    import winreg
    for lnk in shortcut_paths():
        lnk.unlink(missing_ok=True)
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, APP_KEY)
    except FileNotFoundError:
        pass
    if install_dir:
        _user_path_edit(remove=install_dir / "bin")
        _after_exit(f'rmdir /s /q "{install_dir}"')
    exe = running_exe()
    if exe and is_setup_build():
        _after_exit(f'del /f /q "{exe}"')


def wait_for_pid(pid: int, timeout_ms=60000):
    SYNCHRONIZE = 0x00100000
    h = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
    if h:
        ctypes.windll.kernel32.WaitForSingleObject(h, timeout_ms)
        ctypes.windll.kernel32.CloseHandle(h)
