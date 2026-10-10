# Changelog

## 1.4.0
- **Voice channels and group calls** from the Jace Social mod: join a server's voice channel or a group chat's call in game. Everyone in it connects to everyone, like in the Jace Social app. The call bar here shows it too, with Mute, Deafen and Leave.
- **Camera and screen sharing** in calls and voice channels: **📷 Camera** and **🖥️ Share screen** in the call bar (or in game) send your camera or your main screen. People see them in Jace Social; the launcher stays voice-only for what others send, and **Watch in Jace Social** opens it there.
- Several people talking at once are mixed together.
- Fixes calls breaking when you turned something on mid-call after answering someone using a browser.

## 1.3.2
- **Calls with video:** when the friend you're calling turns on their camera or shares their screen, the call bar says so and shows **Watch in Jace Social**. That moves the call to Jace Social in your browser, where you can see it; they don't have to do anything. The Jace Social mod gets the same button (mod 1.4.1).
- Calls keep working when the other person turns their camera or screen sharing on and off. The launcher stays voice-only and doesn't download their video.
- Fixes calls with someone who moves the call to another device.

## 1.3.1
- **Jace Social mod 1.4 and later:** your friends see the mod's in-game status again. The mod's files are now named `jace_social_…jar`, and the launcher didn't recognise them.
- **Server add-ons:** LuckPerms is no longer offered on Fabric and Quilt. There it only runs on dedicated servers, so it did nothing in worlds you host. The Jace Social mod's own permissions do that job (Host world → Permissions).

## 1.3.0
- **Jace Social:** the friends system is now its own project, with a web app and a desktop app at <https://jace-deb.github.io/jace-social/>. The in-game mod is now called Jace Social too.
- **No more "Sign in to Jace Social" button:** friends and chat sign in automatically with your Microsoft Minecraft account at startup, and when you add or switch accounts.
- **Settings → Jace Social → Link Jace:** link your Jace account, so you can sign in to Jace Social on the web and in the desktop app. Your friends, chats and servers are the same everywhere.
- Friends now see more of what you're doing while you play from Jace Launcher: your mod loader, modpack and how long you've been playing.

## 1.2.1
- **Voice calls on older Macs:** fixed "Voice calls aren't available in this build" on macOS 12 and 13. Some libraries in 1.2.0 needed macOS 14 (Apple Silicon) or macOS 15 (Intel).

## 1.2.0
- **Voice calls with friends:** click **📞 Call** in a friend's chat. Audio goes directly between you, or through a relay when your networks don't allow a direct connection. While you play, the Jace Friends mod can start, answer, mute and hang up calls. That needs the game to be started from Jace Launcher.
- **Server add-ons** (an instance's **Mods** tab): one-click LuckPerms, WorldEdit, Chunky, spark and Ledger for worlds you host for friends.
- **Jace Store dependencies:** when a Jace Store mod lists dependencies (on Jace Store or Modrinth), they're installed with it.
- **Jace Friends mod** now supports every release from 1.20.1 to 26.3 on Fabric/Quilt, NeoForge and Forge, with a **Host world** button and roles (Visitor / Builder / Admin) for friends who join.

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
