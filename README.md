# ⛏ Jace Launcher

A desktop launcher for Minecraft: Java Edition, written in Python and Qt (PySide6).

## Features

- **Every Java Edition version**: releases, snapshots, betas and alphas, from Mojang's version manifest.
- **Mod loaders**: Fabric, Quilt, Forge, NeoForge and Legacy Fabric (1.3–1.13).
- **Java is handled for you**: each version gets the Java runtime Mojang ships for it (Java 8, 16, 17 or 21). You can also point it at your own Java.
- **Instances**: every instance has its own folder for mods, saves, resource packs and shaders. Versions, libraries and assets are downloaded once and shared between instances.
- **Modrinth**: search and install mods, modpacks, resource packs and shaders. Results are filtered to the selected instance's version and loader, and required dependencies are installed automatically.
- **CurseForge** (optional): the same browsing once you add a free API key in Settings.
- **Modpacks**: install from either site, or import a `.mrpack` or CurseForge `.zip` file.
- **Skin and cape changer**:
  - front and back preview with the cape shown
  - Classic or Slim arm model
  - upload a skin from a file, or copy any player's skin by username
  - reset to the default skin
  - equip any cape you own, or wear none
  - a local skin library you can apply with a double-click
- **Accounts**: Microsoft sign-in, plus offline accounts for singleplayer and offline-mode servers.
- **Game log** window, plus per-instance memory, Java and JVM argument overrides.

## Running

```bash
./run.sh
```

The first run creates `.venv` and installs `requirements.txt`. To run it by hand:

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m jace
```

You need Python 3.10 or newer. You don't need Java installed.

## Downloads for Windows, macOS and Linux

GitHub Actions builds every platform, because PyInstaller can't build Windows or Mac apps from Linux. The workflow is in `.github/workflows/build.yml`.

| Platform | File | Install |
|---|---|---|
| Windows 10/11 | `JaceLauncher-<ver>-windows-x64-setup.exe` | Setup wizard: choose the folder, desktop shortcut and Start menu entry. Includes an uninstaller. |
| Windows | `…-windows-x64-portable.zip` | Unzip and run `JaceLauncher.exe`. |
| macOS (Apple Silicon) | `JaceLauncher-<ver>-macos-arm64.dmg` | Open it and drag Jace Launcher into Applications. |
| macOS (Intel) | `JaceLauncher-<ver>-macos-x86_64.dmg` | Same as above. |
| Linux | `JaceLauncher-<ver>-x86_64.AppImage` | Run it; the setup wizard does the rest (see below). |

Every push to `main` builds all of these; download them from the run's **Artifacts**. Pushing a version tag also publishes a GitHub Release:

```bash
git tag v1.0.0 && git push origin v1.0.0
```

The first launch on every platform asks you to add your accounts. **Settings → Delete Jace Launcher** works on all platforms: it runs the uninstaller on Windows, moves the `.app` out of Applications on macOS, and removes the AppImage and shortcuts on Linux.

**Unsigned builds:** the apps aren't signed with paid Apple or Microsoft certificates, so:
- **macOS** says the app "can't be opened". Right-click it, choose **Open**, then **Open** again (only needed once). On macOS 15 and newer, go to **System Settings → Privacy & Security → Open Anyway** instead.
- **Windows SmartScreen** shows "Windows protected your PC". Click **More info → Run anyway**.

To build on a Mac or Windows PC yourself, install the requirements plus `pyinstaller pillow`, then run `python packaging/build.py`. Windows also needs [Inno Setup](https://jrsoftware.org/isinfo.php).

## AppImage and installer

Build a single-file AppImage that includes Python, Qt and everything else:

```bash
./packaging/build_appimage.sh      # -> dist/JaceLauncher-<version>-x86_64.AppImage
```

The first time you run the AppImage, a setup wizard opens. It:
1. signs in to your accounts (Microsoft or offline)
2. lets you choose where to install (default `~/Applications`)
3. adds Jace Launcher to the applications menu, creates a desktop shortcut and adds a `jace-launcher` terminal command
4. installs AppStream metadata (`~/.local/share/metainfo`), which software centers use to describe apps

You can also run it from a terminal:

```bash
./JaceLauncher-x86_64.AppImage --install --yes     # install with defaults, no wizard
./JaceLauncher-x86_64.AppImage --uninstall         # remove (keeps your worlds)
./JaceLauncher-x86_64.AppImage --uninstall --purge # remove everything
```

To uninstall from the desktop, right-click the app in the menu and choose **Uninstall Jace Launcher**, or use **Settings → Desktop integration**.

### Getting into an app store

GNOME Software and KDE Discover only list apps from a package source: apt, Flatpak/Flathub or Snap. A local AppImage can't add itself to them. To appear there:
- **Flathub** (what GNOME Software shows by default): package the app as a Flatpak and send a submission to Flathub's review. The AppStream metainfo this project generates is the file Flathub needs. It currently has no `<url type="homepage">` because there's no website yet.
- **AppImageHub** (appimage.github.io): open a pull request with the AppImage's download URL. AppImage stores like Gear Lever and AppImagePool then list it.
- **Snap Store**: package it with `snapcraft`.

## Where things are stored

| Path | Contents |
|---|---|
| `~/.jacelauncher/game` | Shared versions, libraries, assets and Java runtimes |
| `~/.jacelauncher/instances/<name>/minecraft` | One instance's game folder (mods, saves, …) |
| `~/.jacelauncher/skins` | Your skin library |
| `~/.jacelauncher/accounts.json` | Account tokens (keep this private) |

On Windows the folder is `%APPDATA%\.jacelauncher`. To use a different location, set `JACE_LAUNCHER_HOME`.

## CurseForge

CurseForge's API requires a key. Get one for free at <https://console.curseforge.com>, then paste it into **Settings → Integrations**. Some authors don't allow launchers to download their files. The launcher respects that setting, so it lists those files for you to download by hand.

## Code layout

```
jace/
  config.py        paths and settings
  accounts.py      Microsoft/Xbox/Minecraft auth, offline accounts, skin & cape API
  loaders.py       vanilla + Fabric/Quilt/Legacy Fabric (meta API) + Forge/NeoForge (installer)
  instances.py     instance model, install, launch command
  content.py       Modrinth & CurseForge clients, mod/modpack installs
  skin_render.py   2D skin/cape renderer
  ui/              PySide6 pages (library, browse, skins, accounts, settings)
```
