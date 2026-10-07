package dev.jacedeb.jacefriends;

import net.minecraft.client.KeyMapping;
import net.minecraft.client.Minecraft;
import net.minecraft.client.gui.components.toasts.SystemToast;
import net.minecraft.client.gui.screens.ConnectScreen;
import net.minecraft.client.gui.screens.Screen;
import net.minecraft.client.multiplayer.ServerData;
import net.minecraft.client.multiplayer.resolver.ServerAddress;
import net.minecraft.client.server.IntegratedServer;
import net.minecraft.network.chat.Component;
import com.mojang.blaze3d.platform.InputConstants;

/**
 * Every Minecraft/loader API that differs between the supported versions lives here,
 * so the rest of the mod is the same code everywhere. Stonecutter switches the
 * `//? if` branches when building each version.
 */
public final class Compat {
	private Compat() {}

	public static String profileUuid() {
		//? if >=1.20.2 {
		return Minecraft.getInstance().getUser().getProfileId().toString().replace("-", "");
		//?} else {
		/*return Minecraft.getInstance().getUser().getUuid().replace("-", "");
		*///?}
	}

	public static String mcVersion() {
		//? if >=1.21.6 {
		return net.minecraft.SharedConstants.getCurrentVersion().name();
		//?} else {
		/*return net.minecraft.SharedConstants.getCurrentVersion().getName();
		*///?}
	}

	public static Screen currentScreen() {
		//? if >=26.2 {
		return Minecraft.getInstance().gui.screen();
		//?} else {
		/*return Minecraft.getInstance().screen;
		*///?}
	}

	public static void setScreen(Screen screen) {
		//? if >=26.2 {
		Minecraft.getInstance().gui.setScreen(screen);
		//?} else {
		/*Minecraft.getInstance().setScreen(screen);
		*///?}
	}

	public static void toast(String title, String body) {
		Minecraft mc = Minecraft.getInstance();
		Component t = Component.literal(title);
		Component b = Component.literal(body);
		//? if >=26.2 {
		SystemToast.add(mc.gui.toastManager(), SystemToast.SystemToastId.PERIODIC_NOTIFICATION, t, b);
		//?} elif >=1.21.2 {
		/*SystemToast.add(mc.getToastManager(), SystemToast.SystemToastId.PERIODIC_NOTIFICATION, t, b);
		*///?} elif >=1.20.4 {
		/*SystemToast.add(mc.getToasts(), SystemToast.SystemToastId.PERIODIC_NOTIFICATION, t, b);
		*///?} else {
		/*SystemToast.add(mc.getToasts(), SystemToast.SystemToastIds.PERIODIC_NOTIFICATION, t, b);
		*///?}
	}

	public static KeyMapping newKeyMapping() {
		//? if >=1.21.9 {
		return new KeyMapping("key.jacefriends.open", InputConstants.KEY_J,
				KeyMapping.Category.register(net.minecraft.resources.Identifier.fromNamespaceAndPath("jacefriends", "main")));
		//?} else {
		/*return new KeyMapping("key.jacefriends.open", InputConstants.KEY_J, "key.categories.jacefriends");
		*///?}
	}

	/** Join a server / hosted world from a menu (we only allow this outside a world). */
	public static void connect(Screen parent, String address, String name) {
		Minecraft mc = Minecraft.getInstance();
		ServerAddress addr = ServerAddress.parseString(address);
		//? if >=1.20.2 {
		ServerData data = new ServerData(name, address, ServerData.Type.OTHER);
		//?} else {
		/*ServerData data = new ServerData(name, address, false);
		*///?}
		//? if >=1.20.5 {
		ConnectScreen.startConnecting(parent, mc, addr, data, false, null);
		//?} else {
		/*ConnectScreen.startConnecting(parent, mc, addr, data, false);
		*///?}
	}

	/** Open the singleplayer world to LAN (e4mc then gives it a public address). */
	public static boolean publishLan(IntegratedServer sp, int port) {
		//? if >=26.2 {
		return sp.publishServer(net.minecraft.server.MinecraftServer.MultiplayerScope.LAN, port);
		//?} else {
		/*Minecraft mc = Minecraft.getInstance();
		return sp.publishServer(mc.gameMode != null ? mc.gameMode.getPlayerMode() : net.minecraft.world.level.GameType.SURVIVAL,
				false, port);
		*///?}
	}

	public static boolean isModLoaded(String id) {
		//? if fabric {
		return net.fabricmc.loader.api.FabricLoader.getInstance().isModLoaded(id);
		//?} elif neoforge {
		/*return net.neoforged.fml.ModList.get() != null && net.neoforged.fml.ModList.get().isLoaded(id);
		*///?} else {
		/*return net.minecraftforge.fml.ModList.get() != null && net.minecraftforge.fml.ModList.get().isLoaded(id);
		*///?}
	}

	/** Run a command on the integrated server as the server itself (no chat output). */
	public static void runCommand(net.minecraft.server.MinecraftServer server, String command) {
		server.getCommands().performPrefixedCommand(server.createCommandSourceStack().withSuppressedOutput(), command);
	}

	/** Minecraft's own Friends screen (26.2+), which we replace with Jace Friends. */
	public static boolean isVanillaFriends(Screen screen) {
		//? if >=26.2 {
		return screen instanceof net.minecraft.client.gui.screens.friends.FriendsOverlayScreen;
		//?} else {
		/*return false;
		*///?}
	}

	/** The World Options screen (26.3+), which gets a "Host world" button. */
	public static boolean isWorldOptions(Screen screen) {
		//? if >=26.3 {
		return screen instanceof net.minecraft.client.gui.screens.WorldOptionsScreen;
		//?} else {
		/*return false;
		*///?}
	}

	public static boolean isEnter(int key) {
		return key == InputConstants.KEY_RETURN || key == InputConstants.KEY_NUMPADENTER;
	}
}
