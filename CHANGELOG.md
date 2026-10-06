# Changelog

## 1.1.0
- **Synced friends list:** your friends are tied to your Minecraft account through Jace Social, so they follow you to any computer. Add friends by username, even if they haven't used Jace Launcher yet; they'll see your request when they sign in.
- **Chat** with friends, with live notifications and unread badges.
- **See what friends are doing:** online, playing a version or server, or hosting a world. Click **Join** to play with them; the launcher picks an instance with the right Minecraft version.
- **Jace Friends mod** for Minecraft 26.3 (on Jace Store): friends list and chat in game (press **J**), plus "Host this world for friends" with e4mc.
- Sign-in is verified by Mojang and needs a Microsoft account.
- **Jace Store in Browse:** search and install mods, modpacks, resource packs and shaders from Jace Store. Files are checked against the store's SHA-1, Store mods count in **Check for updates**, and hand-added Store files get the **Delete** button.
- **Dependencies from the mod itself:** required mods listed in a jar's `fabric.mod.json`, `quilt.mod.json` or `mods.toml` are installed automatically from Modrinth. This covers Jace Store mods and jars you add by hand.

## 1.0.9
- **Browse:** mods, resource packs and shaders already in the selected instance show a **Delete** button instead of Install. This includes ones you added by hand.
- **Synced folders:** share worlds, resource packs, shaders, screenshots and schematics between instances. Move the shared folder into Dropbox, OneDrive or Google Drive to sync between computers.
- **Settings → About** with the version, "Made by jace.deb" and the GitHub link.
- The project moved to github.com/jace-deb/jace-launcher. Update checks follow the move.

## 1.0.8
- **Mod updates:** **Check for updates** on an instance's Mods tab also works for mods you added by hand. **Update all** installs them.
- Missing required dependencies are installed automatically when you install a mod, add a jar, or check for updates.
- The icon builder opens instantly.

## 1.0.7
- The Windows version now runs under Wine/Bottles. It was failing with "DLL load failed while importing QtCore".
- **Instance shortcuts:** add a desktop or Start menu shortcut that starts an instance straight away.
- **Per-instance window size.**
- **Custom instance icons**, plus an **icon builder** with shapes, gradients, text, symbols and Minecraft block or item textures. Modpacks use their own icon.

## 1.0.6
- Windows: the Microsoft Visual C++ runtime is now bundled.

## 1.0.5
- **Installing is required:** the downloaded app runs the setup wizard. Cancelling closes it.
- **Friends list:** add friends by username, see their skin, see when they're online on their server, and join them in one click.
- Old 64×32 skins like Notch's now show the right face.

## 1.0.4
- **One-click updates** on every platform.
- Windows is now a single self-installing `.exe` with a setup wizard: Start menu, desktop shortcut and "Installed apps" entry.

## 1.0.3
- macOS ships as **Jace Launcher.app** instead of a disk image.

## 1.0.2
- macOS setup wizard: installs to Applications and adds the app to the Dock and desktop.

## 1.0.1
- Fixed the macOS app quitting at launch on macOS 12 Monterey.

## 1.0.0
- First release: every Java Edition version, with Fabric, Quilt, Forge, NeoForge and Legacy Fabric.
- Automatic Java, isolated instances, and Modrinth and CurseForge browsing.
- Skin and cape changer, plus Microsoft and offline accounts.
- The macOS build in this version needs macOS 13 or newer.
