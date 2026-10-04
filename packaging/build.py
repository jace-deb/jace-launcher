"""Build Jace Launcher for the platform this runs on.

    python packaging/build.py

  Windows -> dist/JaceLauncher-<ver>-windows-x64-setup.exe  (Inno Setup installer)
             dist/JaceLauncher-<ver>-windows-x64-portable.zip
  macOS   -> dist/JaceLauncher-<ver>-macos-<arch>.dmg         (drag to Applications)
  Linux   -> use packaging/build_appimage.sh

PyInstaller can't cross-compile, so the Windows and macOS builds run on
GitHub Actions (.github/workflows/build.yml).
"""
import os
import platform
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from jace import APP_VERSION  # noqa: E402
from jace.desktop import APP_ID  # noqa: E402

BUILD = ROOT / "build" / sys.platform
DIST = ROOT / "dist"
ASSETS = ROOT / "jace" / "assets"


def run(cmd, **kw):
    print("+", " ".join(map(str, cmd)), flush=True)
    subprocess.run(list(map(str, cmd)), check=True, **kw)


def pyinstaller(name: str, icon: Path, extra=()):
    shutil.rmtree(BUILD, ignore_errors=True)
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--log-level", "WARN",
         "--name", name, "--windowed", "--icon", icon,
         "--distpath", BUILD / "dist", "--workpath", BUILD / "work", "--specpath", BUILD,
         "--paths", ROOT,
         "--add-data", f"{ASSETS}{os.pathsep}jace/assets",
         "--collect-all", "minecraft_launcher_lib",
         "--hidden-import", "PySide6.QtWebEngineWidgets", "--hidden-import", "PySide6.QtWebEngineCore",
         *extra, ROOT / "packaging" / "entry.py"])
    return BUILD / "dist"


def build_windows():
    out = pyinstaller("JaceLauncher", ASSETS / "icon.ico")
    DIST.mkdir(exist_ok=True)
    base = f"JaceLauncher-{APP_VERSION}-windows-x64"

    portable = shutil.make_archive(str(DIST / f"{base}-portable"), "zip", out, "JaceLauncher")
    print("Built", portable)

    iscc = shutil.which("iscc") or r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    if not Path(iscc).exists():
        sys.exit("Inno Setup (iscc) not found - install it from https://jrsoftware.org/isinfo.php")
    run([iscc, f"/DAppVersion={APP_VERSION}", f"/DSourceDir={out / 'JaceLauncher'}",
         f"/DOutputDir={DIST}", f"/DOutputName={base}-setup", f"/DIconFile={ASSETS / 'icon.ico'}",
         ROOT / "packaging" / "windows" / "installer.iss"])
    print("Built", DIST / f"{base}-setup.exe")


def macos_min_version(app: Path) -> str:
    """Highest LC_BUILD_VERSION 'minos' among the app's key binaries, i.e. the oldest
    macOS this bundle can really run on. Used for LSMinimumSystemVersion so older Macs
    get a clear "needs a newer macOS" message instead of a silent crash at launch."""
    binaries = [p for pat in ("Contents/MacOS/*", "**/QtCore.framework/Versions/A/QtCore",
                              "**/QtWebEngineCore.framework/Versions/A/QtWebEngineCore", "**/libpython3*.dylib",
                              "**/Python.framework/Versions/*/Python")
                for p in app.glob(pat) if p.is_file()]
    found = []
    for b in binaries:
        out = subprocess.run(["otool", "-l", str(b)], capture_output=True, text=True).stdout
        lines = out.splitlines()
        for i, line in enumerate(lines):
            if "LC_BUILD_VERSION" in line or "LC_VERSION_MIN_MACOSX" in line:
                for nxt in lines[i + 1:i + 6]:
                    parts = nxt.split()
                    if parts and parts[0] in ("minos", "version"):
                        found.append((tuple(int(x) for x in parts[1].split(".")), b.name))
                        break
    if not found:
        sys.exit("Couldn't determine the minimum macOS version of the build")
    ver, name = max(found)
    print(f"Minimum macOS: {'.'.join(map(str, ver))} (from {name})")
    return ".".join(map(str, ver))


def build_macos():
    arch = "arm64" if platform.machine() == "arm64" else "x86_64"
    out = pyinstaller("Jace Launcher", ASSETS / "icon.icns",
                      ["--osx-bundle-identifier", APP_ID, "--target-arch", arch])
    app = out / "Jace Launcher.app"

    info = app / "Contents" / "Info.plist"
    with open(info, "rb") as f:
        plist = plistlib.load(f)
    plist.update({
        "CFBundleDisplayName": "Jace Launcher",
        "CFBundleShortVersionString": APP_VERSION,
        "CFBundleVersion": APP_VERSION,
        "LSApplicationCategoryType": "public.app-category.games",
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": macos_min_version(app),
    })
    with open(info, "wb") as f:
        plistlib.dump(plist, f)
    # Info.plist changed, so re-sign (ad-hoc: no Apple developer account needed,
    # but required for the app to run at all on Apple Silicon)
    run(["codesign", "--force", "--deep", "--sign", "-", app])

    stage = BUILD / "dmg"
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True)
    run(["ditto", app, stage / app.name])
    (stage / "Applications").symlink_to("/Applications")
    DIST.mkdir(exist_ok=True)
    dmg = DIST / f"JaceLauncher-{APP_VERSION}-macos-{arch}.dmg"
    dmg.unlink(missing_ok=True)
    run(["hdiutil", "create", "-volname", "Jace Launcher", "-srcfolder", stage, "-ov", "-format", "UDZO", dmg])
    print("Built", dmg)


if __name__ == "__main__":
    if sys.platform == "win32":
        build_windows()
    elif sys.platform == "darwin":
        build_macos()
    else:
        sys.exit("On Linux, run packaging/build_appimage.sh")
