"""Build Jace Launcher for the platform this runs on.

    python packaging/build.py

  Windows -> dist/JaceLauncher-<ver>-windows-x64.exe          (self-installing, setup wizard)
  macOS   -> dist/JaceLauncher-<ver>-macos-<arch>.app.zip     (unzips to Jace Launcher.app)
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
         "--hidden-import", "PySide6.QtMultimedia", "--collect-all", "aiortc",   # voice calls
         *extra, ROOT / "packaging" / "entry.py"])
    return BUILD / "dist"


# Microsoft Visual C++ runtime DLLs that Qt and Python need. Most Windows PCs have
# them, but fresh installs and Wine prefixes (Bottles, Lutris) often don't, which
# makes QtCore fail with "DLL load failed". Microsoft allows shipping them app-locally.
VC_RUNTIME = ["vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll", "msvcp140_1.dll",
              "msvcp140_2.dll", "concrt140.dll"]


def vc_runtime_args() -> list:
    system32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
    args = []
    for dll in VC_RUNTIME:
        src = system32 / dll
        if not src.is_file():
            sys.exit(f"Missing {src} - install the Visual C++ 2015-2022 redistributable (x64)")
        args += ["--add-binary", f"{src}{os.pathsep}."]
    return args


def build_windows():
    """One self-installing .exe: a onefile build that also carries a small onedir
    launcher, which the setup wizard installs next to the unpacked app files."""
    from PIL import Image
    vc = vc_runtime_args()
    onedir = pyinstaller("JaceLauncher", ASSETS / "icon.ico", vc)
    launcher = onedir / "JaceLauncher" / "JaceLauncher.exe"
    keep = ROOT / "build" / "win-launcher"
    shutil.rmtree(keep, ignore_errors=True)
    keep.mkdir(parents=True)
    shutil.copy2(launcher, keep / "JaceLauncher.exe")

    splash = ROOT / "build" / "splash.png"
    Image.open(ASSETS / "icon.png").convert("RGBA").resize((256, 256), Image.NEAREST).save(splash)
    out = pyinstaller("JaceLauncher", ASSETS / "icon.ico",
                      [*vc, "--onefile", "--splash", splash,
                       "--add-data", f"{keep / 'JaceLauncher.exe'}{os.pathsep}jace_setup"])
    DIST.mkdir(exist_ok=True)
    final = DIST / f"JaceLauncher-{APP_VERSION}-windows-x64.exe"
    shutil.copy2(out / "JaceLauncher.exe", final)
    print("Built", final)


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
        # without this macOS blocks the microphone for voice calls
        "NSMicrophoneUsageDescription": "Jace Launcher uses the microphone for voice calls with your friends.",
        "LSMinimumSystemVersion": macos_min_version(app),
    })
    with open(info, "wb") as f:
        plistlib.dump(plist, f)
    # Info.plist changed, so re-sign (ad-hoc: no Apple developer account needed,
    # but required for the app to run at all on Apple Silicon)
    run(["codesign", "--force", "--deep", "--sign", "-", app])

    # A .app is a folder, so it's shipped zipped; Safari unzips downloads automatically,
    # leaving "Jace Launcher.app" in Downloads. ditto keeps symlinks and the signature.
    DIST.mkdir(exist_ok=True)
    archive = DIST / f"JaceLauncher-{APP_VERSION}-macos-{arch}.app.zip"
    archive.unlink(missing_ok=True)
    run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", app, archive])
    print("Built", archive)


if __name__ == "__main__":
    if sys.platform == "win32":
        build_windows()
    elif sys.platform == "darwin":
        build_macos()
    else:
        sys.exit("On Linux, run packaging/build_appimage.sh")
