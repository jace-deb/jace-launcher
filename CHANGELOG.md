# Changelog

## 1.10.3
- **About half the camera delay in Minecraft Education on Linux.** While the game is open, Jace Launcher asks your system for the **Performance** power profile (power-profiles-daemon), and it switches back on its own when you close the game. On a laptop set to Balanced, the emulator, Android's frame encoder and the game were all waiting on low CPU clocks. Measured from an input to the picture changing, the median delay dropped from about 213 ms to about 122 ms.

## 1.10.2
- **Less mouse lag in Minecraft Education on Linux.** Android compresses every frame of the game window in software, on a single thread. On smaller PCs, that encoder was saturated at 1280×720, so frames queued up behind it and the mouse lagged.
  - On those PCs Android now renders at 1024×576 (the same shape as your monitor), and the stream uses a lower bitrate.
  - PCs with 8+ CPU threads and 16 GB+ RAM still get 1920×1080.

## 1.10.1
- **Minecraft Education on Linux lags much less.** Android's preinstalled Google apps (YouTube, YouTube Music, Gmail, the Google app, Messages, Docs, Photos and more) ran in the background and filled the virtual tablet's memory, so it swapped while you played.
  - Jace Launcher now turns those apps off in its emulator. This can be undone, and the Play Store, Play services, Chrome and the keyboard stay on.
  - It also clears background apps before the game starts.
  - Android's swap use dropped from about 900 MB to about 350 MB.
- **No black bars in full screen.** Android's screen now has the same shape as your monitor (for example, 1280×720 on a 1920×1080 screen), or as your game window if you set a size. If the shape changes, Android restarts once to apply it.

## 1.10.0
- **Minecraft Bedrock on Windows.** Bedrock instances play the official Minecraft for Windows. If it isn't installed, Play opens its Microsoft Store page and continues once it's installed. Worlds and packs from Browse and the instance's tabs go into the game's own folder.
- **Minecraft Education on Windows and macOS.** Education instances use Microsoft's official app. On Play, Jace Launcher downloads it from Microsoft, installs it (silently on Windows, into Applications on macOS) and keeps it updated.
- **Minecraft Education on Linux runs much faster.** The virtual tablet is now sized for your PC:
  - Its screen is 1280×800 (1920×1200 on PCs with 8+ CPU threads and 16 GB+ RAM).
  - Its RAM and CPU cores fit what you have, so your PC no longer swaps.
  - Android's animations are off.
  - On a 6-thread, 8 GB laptop it went from about 10 to about 48 FPS.

## 1.9.0
- **Minecraft Education no longer shows a black screen.** Android now draws with ANGLE on your GPU's Vulkan (the emulator's GuestAngle mode). The emulator's default OpenGL ES 3.0 couldn't run the game's renderer.
- **Just press Play.** The first time, Jace Launcher sets up the Android emulator (you accept the Android SDK License), then installs Minecraft Education from Google Play by itself. You no longer need the Setup tab.
- **Google sign-in gets its own small window.** If Android isn't signed in to Google yet, Google Play opens on the Minecraft Education page in a small window. Once you're signed in, Jace Launcher presses Install for you.
- **New game window.** The emulator runs without its own window, and the game appears in a clean [scrcpy](https://github.com/Genymobile/scrcpy) window:
  - no emulator toolbar
  - no "not responding" prompts while Android starts
  - Android's "isn't responding" and "Viewing full screen" pop-ups are turned off
- **Real full screen.** There's no bar and no black screen, and Gamescope isn't needed anymore.
- In the game, the keyboard and mouse act like real ones plugged into the tablet. Press **Left Alt** to free the mouse.

## 1.8.2
- **Bedrock instances list every Bedrock version, and the one you pick downloads when you press Play**, like Java versions.
  - The list comes from the Minecraft Bedrock Launcher's version database (about 130 releases for your CPU). Tick **Snapshots** when creating an instance to include betas.
  - Downloads need your Google Play account, and only the Minecraft Bedrock Launcher has it. So on Play, its window opens with that version selected: click **Download and play** there. Jace Launcher closes it when the download finishes and starts Bedrock in your instance.
  - The **Download versions…** button is gone. **Open Bedrock launcher** remains in the New instance window for signing in to Google Play.

## 1.8.1
- **Bedrock:** "Install Bedrock launcher" now checks that the launcher actually got installed, and shows Flatpak's error if it didn't. Before, it could report success when nothing was installed.
- **Bedrock:** if the Minecraft Bedrock Launcher closes right after "Download versions…", Jace Launcher now shows its error output instead of doing nothing.
- **Bedrock:** Flatpak and mcpelauncher now run without Jace Launcher's bundled library paths, which could break them.
- After an update, the restarted Jace Launcher no longer inherits Qt and library paths from the old copy.
- **Education setup** now retries when Google's download server can't be reached (for example, a brief DNS failure) and shows a clear message if it still fails.
- Added `--self-test-bedrock`, which writes Bedrock diagnostics to the file named in `JACE_SELF_TEST_OUT`.

## 1.8.0
- **Minecraft Education now runs in Google's Android Emulator instead of Waydroid.** It's more reliable, and setup needs no password or system changes.
  - **Setup → Set up Android emulator** downloads everything into Jace Launcher's folder, about 2 GB: Google's Android Emulator, Android 14 with Google Play (Play Store certified), and a virtual tablet. You accept Google's Android SDK License first.
  - **Open Google Play** to sign in and install Minecraft Education, or **Install APK…**.
  - **Play** opens it in the emulator's window. With **Settings → Full screen** it opens full screen through Gamescope.
  - **Remove emulator** frees the space again.
  - It needs hardware virtualization (KVM), which most computers have.
- The project moved to **github.com/okjace** (website: <https://okjace.github.io/jace-launcher/>). Update checks keep working from older versions.

## 1.7.0
- **Minecraft Education on Linux:** **New instance → Mod loader: Education** (Minecraft Education or its Preview).
  - The Android app runs in **Waydroid**, shown in a **Cage** window.
  - Tick **Settings → Full screen** to open it truly full screen with **Gamescope**.
  - Sign in inside the app with your school's Microsoft 365 Education account.
  - The instance's **Setup** tab shows what's ready.
    - **Set up Waydroid** opens a terminal that installs Waydroid, Cage and Gamescope and downloads Android with Google Play. You type your password there, once.
    - **Open Google Play** lets you install the app.
    - **Install APK…** installs one you already have.
  - When you close the game, Waydroid stops so it doesn't keep using memory.

## 1.6.1
- **Bedrock 1.21.120 and newer start now.** They crashed with `cannot locate symbol "pthread_sigmask"`. Jace Launcher now loads the same mods as the Minecraft Bedrock Launcher's own Play button, including its required "mcpelauncher-updates" fix-up mod.
- The first time, the Minecraft Bedrock Launcher may ask whether that mod can use your Google Play sign-in (for the license check). Allow it to play.

## 1.6.0
- **Bedrock instances:** Minecraft Bedrock now works like a normal instance, and the separate Bedrock tab is gone.
  - **Library → New instance → Mod loader: Bedrock**, then pick a Bedrock version. **Play** starts that version.
  - Each Bedrock instance has its own worlds and packs, a **Worlds** and a **Packs** tab, its own window size, icon and shortcut.
  - You don't need a Microsoft account. Bedrock uses the Google Play account in the Minecraft Bedrock Launcher.
  - **Download versions…** (in New instance and in the instance's Settings) opens the Minecraft Bedrock Launcher: sign in to Google Play and download versions there. If it isn't installed, **Install Bedrock launcher** installs it.
- **Change version:** every instance's **Settings** has a version picker now, for Java (with the matching loader version) and Bedrock. Java game files download on the next Play.
- **Browse:** with a Bedrock instance under **Install into**, Browse shows Jace Store's Minecraft Bedrock section (add-ons, texture packs, worlds, skin packs, world templates) and installs into that instance.

## 1.5.0
- **Minecraft Bedrock** (new 🟩 Bedrock page):
  - **Linux and macOS:** one click installs the [Minecraft Bedrock Launcher](https://minecraft-linux.github.io): from Flathub on Linux, the Mac app on macOS. **Play Bedrock** starts it, and **Update** keeps it current. It runs the Android version of Bedrock, so you need to own Minecraft on Google Play. You sign in with Google in its own window; Jace Launcher never sees your Google account.
  - **Windows:** **Play Bedrock** opens Minecraft from the Microsoft Store / Xbox app.
  - **Worlds and Packs** tabs list your Bedrock worlds and resource, behavior and skin packs, and let you delete them.
  - **Import file…** adds `.mcpack`, `.mcaddon`, `.mcworld` and `.mctemplate` files. A newer copy of a pack replaces the old one, and files that try to write outside Minecraft's folder are refused.
  - **Jace Store** tab: search and install from Jace Store's new Minecraft Bedrock section: add-ons, texture packs, worlds, skin packs and world templates.

## 1.4.5
- **Linux:** Jace Launcher shows up only once in your app menu. AppImageLauncher used to add a second "Jace Launcher (1)" entry. The AppImage now tells it not to, and Jace Launcher removes any such duplicate when it starts.

## 1.4.4
- **Linux:** fixed a crash when clicking **Add Microsoft account**, in setup and in the launcher. This happened on newer distros (Arch, CachyOS, Fedora…), especially on Wayland. The AppImage shipped an older copy of some system libraries, which broke the graphics drivers, and the Microsoft sign-in page couldn't start. It now uses your system's own, so hardware graphics work again too.

## 1.4.3
- **Windows setup no longer closes when you add a Microsoft account.** When the Microsoft sign-in page started loading, Windows rebuilt the setup window to draw the page, which hid setup and ended it. The sign-in window is now a separate window, so setup stays open.
- `crash.log` also records how setup ended and why the app quit.

## 1.4.1
- **Windows:** fixed a crash after signing in with Microsoft, including in the setup wizard. The sign-in window now closes its built-in browser safely.
- **Crash log:** if something goes wrong, Jace Launcher shows the error and saves the details to `crash.log` in its data folder (`%APPDATA%\.jacelauncher` on Windows), instead of just closing.

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
