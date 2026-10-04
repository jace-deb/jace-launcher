"""One-click shortcuts that start an instance straight away (no launcher window).

Each shortcut runs the installed launcher with  --launch <instance id>.
  Linux    .desktop files in the applications menu and on the Desktop
  Windows  .lnk files in the Start menu and on the Desktop
  macOS    a small "<name>.app" in ~/Applications (Launchpad/Spotlight) + a Desktop link
"""
import plistlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

from jace import desktop, macinstall, wininstall
from jace.config import DATA_DIR
from jace.instance_icons import icon_image

ICON_DIR = DATA_DIR / "shortcut-icons"
HOME = Path.home()


def launcher_command() -> list[str]:
    """How to start Jace Launcher from outside: the installed app if there is one."""
    installed = desktop.installed_path()
    if installed and installed.suffix == ".app":
        return [str(installed / "Contents" / "MacOS" / "Jace Launcher")]
    if installed:
        return [str(installed)]
    if desktop.frozen():
        return [sys.executable]
    entry = Path(__file__).resolve().parent.parent / "packaging" / "entry.py"
    return [sys.executable, str(entry)]          # running from source


def _safe(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "_", name).strip() or "Minecraft"


def _desktop_dir() -> Path:
    if sys.platform == "win32":
        return wininstall.desktop_dir()
    if sys.platform == "darwin":
        return HOME / "Desktop"
    return desktop.desktop_dir()


def _paths(inst) -> dict[str, Path]:
    name = _safe(inst.name)
    if sys.platform == "win32":
        return {"menu": wininstall.start_menu_dir() / "Jace Launcher" / f"{name}.lnk",
                "desktop": _desktop_dir() / f"{name}.lnk"}
    if sys.platform == "darwin":
        return {"menu": HOME / "Applications" / "Jace Launcher Instances" / f"{name}.app",
                "desktop": _desktop_dir() / name}
    return {"menu": desktop.DATA_HOME / "applications" / f"jace-instance-{inst.id}.desktop",
            "desktop": _desktop_dir() / f"jace-instance-{inst.id}.desktop"}


def _save_icon(inst) -> Path:
    ICON_DIR.mkdir(parents=True, exist_ok=True)
    img = icon_image(inst, 256)
    if sys.platform == "win32":
        path = ICON_DIR / f"{inst.id}.ico"
        img.scaled(256, 256).save(str(path), "ICO")
    elif sys.platform == "darwin":
        path = ICON_DIR / f"{inst.id}.icns"
        if not img.save(str(path), "ICNS"):
            path = ICON_DIR / f"{inst.id}.png"
            img.save(str(path), "PNG")
    else:
        path = ICON_DIR / f"{inst.id}.png"
        img.save(str(path), "PNG")
    return path


def _linux_entry(inst, cmd, icon) -> str:
    exec_line = " ".join(f'"{c}"' for c in cmd + ["--launch", inst.id])
    return ("[Desktop Entry]\nType=Application\n"
            f"Name={inst.name}\nComment=Play {inst.describe()} with Jace Launcher\n"
            f"Exec={exec_line}\nIcon={icon}\nTerminal=false\nCategories=Game;\n")


def _mac_app(inst, cmd, icon: Path, dest: Path):
    if dest.exists():
        shutil.rmtree(dest)
    macos = dest / "Contents" / "MacOS"
    res = dest / "Contents" / "Resources"
    macos.mkdir(parents=True)
    res.mkdir(parents=True)
    args = " ".join(f'"{c}"' for c in cmd)
    run = macos / "launch"
    run.write_text(f'#!/bin/sh\nexec {args} --launch "{inst.id}"\n')
    run.chmod(0o755)
    icon_file = None
    if icon.suffix == ".icns":
        shutil.copy2(icon, res / "icon.icns")
        icon_file = "icon"
    plist = {"CFBundleName": inst.name, "CFBundleDisplayName": inst.name, "CFBundleExecutable": "launch",
             "CFBundleIdentifier": f"{desktop.APP_ID}.instance.{re.sub(r'[^A-Za-z0-9.-]', '-', inst.id)}",
             "CFBundlePackageType": "APPL", "CFBundleShortVersionString": "1.0",
             "LSApplicationCategoryType": "public.app-category.games"}
    if icon_file:
        plist["CFBundleIconFile"] = icon_file
    with open(dest / "Contents" / "Info.plist", "wb") as f:
        plistlib.dump(plist, f)
    subprocess.run([macinstall.LSREGISTER, "-f", str(dest)], capture_output=True, check=False)


def create(inst, menu=True, on_desktop=True) -> list[Path]:
    """Create shortcuts for an instance; returns the created paths."""
    cmd = launcher_command()
    icon = _save_icon(inst)
    paths = _paths(inst)
    made = []
    if sys.platform == "win32":
        for key, want in (("menu", menu), ("desktop", on_desktop)):
            if want:
                wininstall.make_shortcut(paths[key], Path(cmd[0]), args=cmd[1:] + ["--launch", inst.id],
                                         icon=icon, description=f"Play {inst.name}")
                made.append(paths[key])
    elif sys.platform == "darwin":
        app = paths["menu"]
        _mac_app(inst, cmd, icon, app)
        made.append(app)
        if on_desktop:
            link = paths["desktop"]
            if link.is_symlink() or link.exists():
                link.unlink()
            link.symlink_to(app)
            made.append(link)
    else:
        entry = _linux_entry(inst, cmd, icon)
        for key, want in (("menu", menu), ("desktop", on_desktop)):
            if want:
                p = paths[key]
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(entry)
                p.chmod(0o755)
                if key == "desktop" and shutil.which("gio"):
                    subprocess.run(["gio", "set", str(p), "metadata::trusted", "true"], capture_output=True,
                                   check=False)
                made.append(p)
        if shutil.which("update-desktop-database"):
            subprocess.run(["update-desktop-database", str(paths["menu"].parent)], capture_output=True,
                           check=False)
    inst.data["shortcuts"] = [str(p) for p in made]
    inst.save()
    return made


def remove(inst):
    for p in inst.data.get("shortcuts", []):
        p = Path(p)
        if p.is_symlink() or p.is_file():
            p.unlink()
        elif p.is_dir() and p.suffix == ".app":
            shutil.rmtree(p, ignore_errors=True)
    for ext in (".png", ".ico", ".icns"):
        (ICON_DIR / f"{inst.id}{ext}").unlink(missing_ok=True)
    inst.data["shortcuts"] = []


def has_shortcuts(inst) -> bool:
    return any(Path(p).exists() or Path(p).is_symlink() for p in inst.data.get("shortcuts", []))


def menu_name() -> str:
    return {"win32": "Start menu", "darwin": "Launchpad"}.get(sys.platform, "applications menu")

