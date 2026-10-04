#!/usr/bin/env bash
# Build dist/JaceLauncher-x86_64.AppImage
#   1. PyInstaller bundles Python + PySide6 + the app into a folder
#   2. we lay out an AppDir (desktop file, icon, AppStream metadata)
#   3. appimagetool turns that into a single AppImage file
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"
APP_ID="io.github.jacelauncher.JaceLauncher"
VERSION="$(.venv/bin/python -c 'import jace; print(jace.APP_VERSION)')"
BUILD="$ROOT/build/appimage"
APPDIR="$BUILD/AppDir"
TOOL="$ROOT/packaging/tools/appimagetool"

[ -x .venv/bin/python ] || { echo "Run ./run.sh once first to create .venv"; exit 1; }
.venv/bin/python -m pip install -q pyinstaller
if [ ! -x "$TOOL" ]; then
  mkdir -p "$(dirname "$TOOL")"
  curl -sSL -o "$TOOL" https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
  chmod +x "$TOOL"
fi

echo "==> PyInstaller"
rm -rf "$BUILD"
.venv/bin/pyinstaller --noconfirm --clean --log-level WARN \
  --name jace-launcher --windowed \
  --distpath "$BUILD/dist" --workpath "$BUILD/work" --specpath "$BUILD" \
  --paths "$ROOT" \
  --add-data "$ROOT/jace/assets:jace/assets" \
  --collect-all minecraft_launcher_lib \
  --hidden-import PySide6.QtWebEngineWidgets --hidden-import PySide6.QtWebEngineCore \
  "$ROOT/packaging/entry.py"

# Qt >= 6.5 needs libxcb-cursor on X11 but many distros don't install it.
# Put it next to Qt's own libs (their RUNPATH is $ORIGIN) so it's always found.
QTLIB="$(find "$BUILD/dist/jace-launcher" -type d -path '*PySide6/Qt/lib' | head -1)"
XCBC="$(ldconfig -p | awk '/libxcb-cursor.so.0 /{print $NF; exit}')"
if [ -z "$XCBC" ] && [ -e .venv/syslibs/libxcb-cursor.so.0 ]; then XCBC=.venv/syslibs/libxcb-cursor.so.0; fi
if [ -n "$XCBC" ]; then cp -L "$XCBC" "$QTLIB/libxcb-cursor.so.0"; else echo "warning: libxcb-cursor0 not bundled"; fi

echo "==> AppDir"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/share/applications" "$APPDIR/usr/share/metainfo" \
         "$APPDIR/usr/share/icons/hicolor/256x256/apps"
cp -a "$BUILD/dist/jace-launcher" "$APPDIR/usr/bin/"
cp packaging/AppRun "$APPDIR/AppRun"
cp jace/assets/icon.png "$APPDIR/$APP_ID.png"
cp jace/assets/icon.png "$APPDIR/usr/share/icons/hicolor/256x256/apps/$APP_ID.png"
ln -sf "$APP_ID.png" "$APPDIR/.DirIcon"
cat > "$APPDIR/$APP_ID.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Jace Launcher
GenericName=Minecraft Launcher
Comment=Play Minecraft: Java Edition with mods, modpacks, skins and capes
Exec=jace-launcher %U
Icon=$APP_ID
Terminal=false
Categories=Game;
Keywords=minecraft;launcher;mods;fabric;forge;neoforge;quilt;modrinth;curseforge;skins;
DESKTOP
cp "$APPDIR/$APP_ID.desktop" "$APPDIR/usr/share/applications/"
PYTHONPATH="$ROOT" .venv/bin/python -c "from jace.desktop import _metainfo; print(_metainfo(), end='')" \
  > "$APPDIR/usr/share/metainfo/$APP_ID.metainfo.xml"

echo "==> appimagetool"
mkdir -p dist
OUT="$ROOT/dist/JaceLauncher-$VERSION-x86_64.AppImage"
ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN=1 "$TOOL" --no-appstream "$APPDIR" "$OUT"
echo
echo "Built $OUT ($(du -h "$OUT" | cut -f1))"
echo "Run it once to open the setup wizard, or:  $OUT --install --yes"
