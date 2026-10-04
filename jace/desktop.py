"""AppImage self-installer: copies the AppImage to a folder of your choice and adds
an applications-menu entry, a desktop shortcut, a terminal command and AppStream
metadata (what GNOME Software / KDE Discover read to describe apps).

From a terminal:
    ./JaceLauncher-x86_64.AppImage --install      # opens the setup wizard
    ./JaceLauncher-x86_64.AppImage --install --yes  # install with defaults, no questions
    ./JaceLauncher-x86_64.AppImage --uninstall [--purge]
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

from jace import APP_RELEASE_DATE, APP_VERSION
from jace.config import DATA_DIR, read_json, write_json

APP_ID = "io.github.jacelauncher.JaceLauncher"
ICON_SRC = Path(__file__).parent / "assets" / "icon.png"
APPIMAGE_NAME = "JaceLauncher.AppImage"

HOME = Path.home()
DEFAULT_DIR = HOME / "Applications"
DATA_HOME = Path(os.environ.get("XDG_DATA_HOME") or HOME / ".local" / "share")
MENU_FILE = DATA_HOME / "applications" / f"{APP_ID}.desktop"
ICON_FILE = DATA_HOME / "icons" / "hicolor" / "256x256" / "apps" / f"{APP_ID}.png"
METAINFO_FILE = DATA_HOME / "metainfo" / f"{APP_ID}.metainfo.xml"
BIN_LINK = HOME / ".local" / "bin" / "jace-launcher"
RECORD = DATA_DIR / "install.json"


def desktop_dir() -> Path:
    """The user's Desktop folder (localised names like ~/Escritorio included)."""
    try:
        out = subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True, text=True, timeout=5).stdout.strip()
        if out and Path(out) != HOME:
            return Path(out)
    except (OSError, subprocess.SubprocessError):
        pass
    return HOME / "Desktop"


def desktop_shortcut() -> Path:
    return desktop_dir() / f"{APP_ID}.desktop"


def running_appimage() -> Path | None:
    p = os.environ.get("APPIMAGE")
    return Path(p) if p and Path(p).is_file() else None


def install_record() -> dict:
    return read_json(RECORD, {})


def installed_path() -> Path | None:
    p = install_record().get("path")
    return Path(p) if p and Path(p).is_file() else None


def is_installed() -> bool:
    return installed_path() is not None


def running_installed_copy() -> bool:
    src, dst = running_appimage(), installed_path()
    return bool(src and dst and src.resolve() == dst.resolve())


def _desktop_entry(exe: Path) -> str:
    return ("[Desktop Entry]\n"
            "Type=Application\n"
            "Name=Jace Launcher\n"
            "GenericName=Minecraft Launcher\n"
            "Comment=Play Minecraft: Java Edition with mods, modpacks, skins and capes\n"
            f"Exec=\"{exe}\" %U\n"
            f"Icon={APP_ID}\n"
            "Terminal=false\n"
            "Categories=Game;\n"
            "Keywords=minecraft;launcher;mods;fabric;forge;neoforge;quilt;modrinth;curseforge;skins;\n"
            f"StartupWMClass={APP_ID}\n"
            "Actions=uninstall;\n\n"
            "[Desktop Action uninstall]\n"
            "Name=Uninstall Jace Launcher\n"
            f"Exec=\"{exe}\" --uninstall-gui\n")


def _metainfo() -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<component type="desktop-application">
  <id>{APP_ID}</id>
  <name>Jace Launcher</name>
  <summary>Minecraft: Java Edition launcher with mod loaders, Modrinth and CurseForge</summary>
  <developer id="io.github.jacelauncher"><name>Jace</name></developer>
  <metadata_license>CC0-1.0</metadata_license>
  <project_license>MIT</project_license>
  <description>
    <p>Jace Launcher plays every Minecraft: Java Edition version, from the oldest alphas to the
       newest snapshots, and installs the right Java automatically.</p>
    <ul>
      <li>Fabric, Quilt, Forge, NeoForge and Legacy Fabric</li>
      <li>Browse and install mods, modpacks, resource packs and shaders from Modrinth and CurseForge</li>
      <li>Built-in skin and cape changer with a skin library</li>
      <li>Microsoft and offline accounts</li>
    </ul>
  </description>
  <launchable type="desktop-id">{APP_ID}.desktop</launchable>
  <icon type="stock">{APP_ID}</icon>
  <categories><category>Game</category></categories>
  <keywords><keyword>minecraft</keyword><keyword>mods</keyword><keyword>launcher</keyword></keywords>
  <content_rating type="oars-1.1"/>
  <releases><release version="{APP_VERSION}" date="{APP_RELEASE_DATE}"/></releases>
</component>
"""


def _refresh_menus():
    for cmd in (["update-desktop-database", str(MENU_FILE.parent)],
                ["gtk-update-icon-cache", "-q", "-t", str(DATA_HOME / "icons" / "hicolor")]):
        if shutil.which(cmd[0]):
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


def _write(path: Path, text: str, executable=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    if executable:
        os.chmod(path, 0o755)


def install(target_dir: Path = DEFAULT_DIR, menu=True, desktop=True, terminal=True, appstream=True,
            status=print) -> Path:
    src = running_appimage()
    if not src:
        raise RuntimeError("Not running from an AppImage - build one with packaging/build_appimage.sh")
    target_dir = Path(target_dir).expanduser()
    target_dir.mkdir(parents=True, exist_ok=True)
    exe = target_dir / APPIMAGE_NAME

    old = installed_path()
    status(f"Copying Jace Launcher to {target_dir}")
    if src.resolve() != exe.resolve():
        tmp = exe.with_name(exe.name + ".tmp")
        shutil.copy2(src, tmp)
        os.chmod(tmp, 0o755)
        os.replace(tmp, exe)
    if old and old.resolve() != exe.resolve() and old.resolve() != src.resolve():
        old.unlink(missing_ok=True)   # moved to a new location

    ICON_FILE.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ICON_SRC, ICON_FILE)
    entry = _desktop_entry(exe)
    done = []

    for p in (MENU_FILE, desktop_shortcut(), BIN_LINK, METAINFO_FILE):
        if p.is_symlink() or p.exists():
            p.unlink()

    if menu:
        status("Adding to the applications menu")
        _write(MENU_FILE, entry, executable=True)
        done.append("menu")
    if desktop:
        status("Creating desktop shortcut")
        sc = desktop_shortcut()
        _write(sc, entry, executable=True)
        # GNOME (Desktop Icons NG) only launches desktop files marked as trusted
        if shutil.which("gio"):
            subprocess.run(["gio", "set", str(sc), "metadata::trusted", "true"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        done.append("desktop")
    if terminal:
        status("Adding the 'jace-launcher' command")
        BIN_LINK.parent.mkdir(parents=True, exist_ok=True)
        BIN_LINK.symlink_to(exe)
        done.append("terminal")
    if appstream:
        status("Registering with software centers")
        _write(METAINFO_FILE, _metainfo())
        done.append("appstream")

    _refresh_menus()
    write_json(RECORD, {"path": str(exe), "version": APP_VERSION, "parts": done})
    status("Done")
    return exe


def uninstall(remove_data=False, delete_running=False):
    """Remove the installed AppImage, menu entry and shortcuts.
    delete_running also deletes the AppImage file we're running from (e.g. the download)."""
    exe = installed_path()
    running = running_appimage() if delete_running else None
    for p in (MENU_FILE, desktop_shortcut(), ICON_FILE, BIN_LINK, METAINFO_FILE, exe, running):
        if p and (p.is_symlink() or p.exists()):
            p.unlink()
    RECORD.unlink(missing_ok=True)
    if remove_data:
        shutil.rmtree(DATA_DIR, ignore_errors=True)
    _refresh_menus()


# --- Windows / macOS builds -------------------------------------------------------

def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def windows_uninstaller() -> Path | None:
    """Inno Setup's uninstaller next to the installed .exe."""
    if sys.platform != "win32" or not frozen():
        return None
    found = sorted(Path(sys.executable).parent.glob("unins*.exe"))
    return found[0] if found else None


def mac_app_bundle() -> Path | None:
    """The Jace Launcher.app we're running from (Contents/MacOS/<exe> -> .app)."""
    if sys.platform != "darwin" or not frozen():
        return None
    app = Path(sys.executable).resolve().parents[2]
    return app if app.suffix == ".app" else None


def removal_summary() -> list[str]:
    """Human-readable list of what delete_app() will remove on this platform."""
    if windows_uninstaller():
        return [f"the app in {Path(sys.executable).parent}",
                "Start menu entry, desktop shortcut and the Windows uninstall entry"]
    if mac_app_bundle():
        return [f"{mac_app_bundle()}"]
    items = []
    installed, running = installed_path(), running_appimage()
    if installed:
        items.append(f"the app at {installed}")
    if running and (not installed or running.resolve() != installed.resolve()):
        items.append(f"this AppImage file ({running})")
    items.append("menu entry, desktop shortcut and terminal command")
    if not installed and not running and not frozen():
        items.append("(running from source: the source folder itself is left alone)")
    return items


def delete_app(remove_data=False):
    """Delete Jace Launcher on any platform. The caller should quit right after,
    because on Windows/macOS the actual removal finishes once this process exits."""
    if remove_data:
        shutil.rmtree(DATA_DIR, ignore_errors=True)
    unins = windows_uninstaller()
    if unins:
        # wait for us to exit so no files are locked, then run Inno's uninstaller quietly
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        subprocess.Popen(f'cmd /c timeout /t 3 /nobreak >nul & "{unins}" /SILENT /SUPPRESSMSGBOXES',
                         creationflags=flags, close_fds=True)
        return
    app = mac_app_bundle()
    if app:
        subprocess.Popen(["/bin/sh", "-c", 'sleep 2; rm -rf "$0"', str(app)], start_new_session=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
    uninstall(remove_data=False, delete_running=True)


def handle_cli(argv) -> bool:
    """Handle non-GUI flags. Returns True if the app should exit."""
    if "--install" in argv and ("--yes" in argv or "-y" in argv):
        exe = install()
        print(f"Installed to {exe}")
        return True
    if "--uninstall" in argv:
        uninstall(remove_data="--purge" in argv)
        print("Jace Launcher removed." + ("" if "--purge" in argv else
              " Your instances and worlds were kept (add --purge to delete them too)."))
        return True
    if "--help" in argv or "-h" in argv:
        print("Jace Launcher\n"
              "  --install            open the setup wizard (AppImage only)\n"
              "  --install --yes      install with default options, no questions\n"
              "  --uninstall          remove menu entry, shortcuts and the installed AppImage\n"
              "  --uninstall --purge  also delete instances, worlds and accounts")
        return True
    return False


if __name__ == "__main__":
    sys.exit(0 if handle_cli(sys.argv[1:]) else 1)
