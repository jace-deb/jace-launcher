package dev.jacedeb.jacefriends;

import com.google.gson.JsonObject;
import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientLifecycleEvents;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;
import net.fabricmc.fabric.api.client.keymapping.v1.KeyMappingHelper;
import net.fabricmc.fabric.api.client.message.v1.ClientReceiveMessageEvents;
import net.fabricmc.fabric.api.client.screen.v1.ScreenEvents;
import net.fabricmc.fabric.api.client.screen.v1.Screens;
import net.fabricmc.loader.api.FabricLoader;
import net.minecraft.client.KeyMapping;
import net.minecraft.client.Minecraft;
import net.minecraft.client.gui.components.Button;
import net.minecraft.client.gui.components.toasts.SystemToast;
import net.minecraft.client.gui.screens.PauseScreen;
import net.minecraft.client.gui.screens.Screen;
import net.minecraft.client.gui.screens.TitleScreen;
import net.minecraft.client.server.IntegratedServer;
import net.minecraft.network.chat.Component;
import net.minecraft.resources.Identifier;
import com.mojang.blaze3d.platform.InputConstants;

import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Jace Friends: your Jace Launcher friends list and chat inside Minecraft.
 * Press J (or the Friends button on the title/pause screen).
 */
public class JaceFriends implements ClientModInitializer {
	public static final String VERSION = FabricLoader.getInstance().getModContainer("minecraft")
			.map(m -> m.getMetadata().getVersion().getFriendlyString()).orElse("");
	private static final Pattern E4MC = Pattern.compile("([a-z0-9-]+\\.)+e4mc\\.link");
	private static final int PRESENCE_EVERY_TICKS = 20 * 120;   // heartbeat every 2 minutes

	public static KeyMapping openKey;
	/** Public address e4mc gave our open-to-LAN world, if any. */
	public static volatile String hostingAddress;
	private static Live live;
	private static int ticks;
	private static String lastActivity = "";
	private static boolean triedSignIn;

	@Override
	public void onInitializeClient() {
		openKey = KeyMappingHelper.registerKeyMapping(new KeyMapping("key.jacefriends.open", InputConstants.KEY_J,
				KeyMapping.Category.register(Identifier.fromNamespaceAndPath("jacefriends", "main"))));

		ClientTickEvents.END_CLIENT_TICK.register(JaceFriends::tick);

		// e4mc posts the public address of an opened world in chat; remember it so
		// friends can join from their list.
		ClientReceiveMessageEvents.GAME.register((message, overlay) -> {
			Matcher m = E4MC.matcher(message.getString());
			if (m.find()) {
				hostingAddress = m.group();
				ticks = PRESENCE_EVERY_TICKS;       // tell friends right away
			}
		});

		ScreenEvents.AFTER_INIT.register((mc, screen, w, h) -> {
			if (screen instanceof TitleScreen || screen instanceof PauseScreen) {
				Screens.getWidgets(screen).add(Button.builder(Component.literal("👥 Friends"), b -> open(screen))
						.bounds(w - 86, 6, 80, 20).build());
			}
		});

		ClientLifecycleEvents.CLIENT_STOPPING.register(mc -> {
			if (Social.signedIn()) {
				try {
					Social.presence(null, true);
				} catch (Exception ignored) {
					// going offline is best-effort
				}
			}
		});
	}

	public static void open(Screen parent) {
		Minecraft.getInstance().gui.setScreen(new FriendsScreen(parent));
	}

	private static void tick(Minecraft mc) {
		while (openKey.consumeClick()) {
			if (mc.gui.screen() == null) open(null);
		}
		if (!triedSignIn && mc.level == null && mc.gui.screen() instanceof TitleScreen) {
			triedSignIn = true;                     // sign in quietly once the title screen is up
			Social.async(() -> Social.signedIn() ? Social.session() : Social.signIn())
					.thenAccept(s -> mc.execute(() -> startLive(s)))
					.exceptionally(e -> null);
		}
		IntegratedServer sp = mc.getSingleplayerServer();
		if (sp == null || !sp.isPublished()) hostingAddress = null;

		if (++ticks % 100 != 0 && ticks < PRESENCE_EVERY_TICKS) return;   // check every 5 seconds
		JsonObject activity = activity(mc);
		String key = activity.toString();
		if (key.equals(lastActivity) && ticks < PRESENCE_EVERY_TICKS) return;
		ticks = 0;
		lastActivity = key;
		if (Social.signedIn()) {
			Social.async(() -> {
				Social.presence(activity, false);
				return null;
			}).exceptionally(e -> null);
		}
	}

	/** What we tell friends we're doing. */
	public static JsonObject activity(Minecraft mc) {
		JsonObject a = new JsonObject();
		a.addProperty("version", VERSION);
		IntegratedServer sp = mc.getSingleplayerServer();
		if (sp != null && sp.isPublished() && hostingAddress != null) {
			a.addProperty("type", "hosting");
			a.addProperty("world", sp.getWorldData().getLevelName());
			a.addProperty("address", hostingAddress);
		} else if (mc.level != null) {
			a.addProperty("type", "playing");
			if (mc.getCurrentServer() != null && !mc.isLocalServer()) a.addProperty("server", mc.getCurrentServer().ip);
		} else {
			a.addProperty("type", "launcher");
		}
		return a;
	}

	public static void startLive(JsonObject session) {
		if (live == null) live = new Live(JaceFriends::onLiveEvent);
		live.stop();
		live.start(session);
	}

	private static void onLiveEvent(JsonObject e) {
		Minecraft mc = Minecraft.getInstance();
		String event = Social.str(e, "event");
		JsonObject p = e.has("payload") && e.get("payload").isJsonObject() ? e.getAsJsonObject("payload") : new JsonObject();
		if (event.equals("message")) {
			if (mc.gui.screen() instanceof ChatScreen chat && chat.isWith(Social.str(p, "from"))) {
				chat.reload();
			} else {
				toast("New message", Social.str(p, "name"));
			}
		} else if (event.equals("friends")) {
			String kind = Social.str(p, "kind");
			if (kind.equals("request")) toast("Friend request", Social.str(p, "name") + " wants to be friends");
			if (kind.equals("accepted")) toast("New friend", Social.str(p, "name") + " accepted your request");
		}
		if (mc.gui.screen() instanceof FriendsScreen friends) friends.reload();
	}

	public static void toast(String title, String body) {
		Minecraft mc = Minecraft.getInstance();
		SystemToast.add(mc.gui.toastManager(), SystemToast.SystemToastId.PERIODIC_NOTIFICATION,
				Component.literal(title), Component.literal(body));
	}
}
