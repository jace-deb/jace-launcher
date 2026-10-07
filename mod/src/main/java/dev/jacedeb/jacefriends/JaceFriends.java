package dev.jacedeb.jacefriends;

import com.google.gson.JsonObject;
import net.minecraft.client.KeyMapping;
import net.minecraft.client.Minecraft;
import net.minecraft.client.gui.components.Button;
import net.minecraft.client.gui.screens.PauseScreen;
import net.minecraft.client.gui.screens.Screen;
import net.minecraft.client.gui.screens.TitleScreen;
import net.minecraft.client.server.IntegratedServer;
import net.minecraft.network.chat.Component;
import net.minecraft.server.level.ServerPlayer;

import java.util.ArrayList;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Loader-independent mod logic; the Fabric/NeoForge/Forge entry points call into this. */
public final class JaceFriends {
	public static final String VERSION = /*$ mod_version*/ "1.1.0";
	private static final Pattern E4MC = Pattern.compile("([a-z0-9-]+\\.)+e4mc\\.link");
	private static final int PRESENCE_EVERY_TICKS = 20 * 120;   // heartbeat every 2 minutes

	public static KeyMapping openKey;
	/** Public address e4mc gave our open-to-LAN world, if any. */
	public static volatile String hostingAddress;
	private static Live live;
	private static int ticks;
	private static String lastActivity = "";
	private static boolean triedSignIn;
	private static boolean announced;
	private static Screen lastScreen;

	private JaceFriends() {}

	public static KeyMapping createKey() {
		openKey = Compat.newKeyMapping();
		return openKey;
	}

	public static void open(Screen parent) {
		Compat.setScreen(new FriendsScreen(parent));
	}

	/**
	 * Buttons we add to Minecraft's menus: "Friends" on the title and pause screens
	 * (before 26.2; from 26.2 Minecraft's own Friends button opens Jace Friends instead),
	 * and "Host world" on the pause screen and, from 26.3, the World Options screen.
	 */
	public static List<Button> screenButtons(Screen screen, int width, int height) {
		List<Button> out = new ArrayList<>();
		boolean menu = screen instanceof TitleScreen || screen instanceof PauseScreen;
		if (!announced) {                   // one log line (on the first menu) so tests can see the mod is working
			announced = true;
			System.out.println("[Jace Friends] " + VERSION + " ready on Minecraft " + Compat.mcVersion());
		}
		//? if <26.2 {
		/*if (menu) out.add(Button.builder(Component.literal("Friends"), b -> open(screen)).bounds(width - 86, 6, 80, 20).build());
		*///?}
		IntegratedServer sp = Minecraft.getInstance().getSingleplayerServer();
		if (sp != null && (screen instanceof PauseScreen || Compat.isWorldOptions(screen))) {
			String label = sp.isPublished() ? "Hosting" : "Host world";
			int y = screen instanceof PauseScreen ? 6 : height - 26;
			out.add(Button.builder(Component.literal(label), b -> Compat.setScreen(new HostScreen(screen))).bounds(6, y, 80, 20).build());
		}
		return out;
	}

	/** e4all posts the public address of an opened world in chat; remember it. */
	public static void onGameMessage(Component message) {
		// the address can be hidden ("click to copy"), so also look inside the click event
		Matcher m = E4MC.matcher(message.getString() + " " + message);
		if (m.find()) {
			hostingAddress = m.group();
			ticks = PRESENCE_EVERY_TICKS;       // tell friends right away
		}
	}

	/** Someone joined the world we're hosting (server thread). */
	public static void onPlayerJoin(ServerPlayer player) {
		IntegratedServer sp = Minecraft.getInstance().getSingleplayerServer();
		if (sp != null && sp.isPublished()) Roles.apply(sp, player, true);
	}

	public static void tick(Minecraft mc) {
		Screen current = Compat.currentScreen();
		if (Compat.isVanillaFriends(current)) {
			open(lastScreen);                   // Minecraft's Friends button -> Jace Friends
		} else if (!(current instanceof FriendsScreen || current instanceof ChatScreen || current instanceof HostScreen)) {
			lastScreen = current;
		}
		Calls.tick();
		if (openKey != null) {
			while (openKey.consumeClick()) {
				if (Compat.currentScreen() == null) open(null);
			}
		}
		if (!triedSignIn && mc.level == null && Compat.currentScreen() instanceof TitleScreen) {
			triedSignIn = true;                 // sign in quietly once the title screen is up
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

	public static void stopping() {
		if (Social.signedIn()) {
			try {
				Social.presence(null, true);
			} catch (Exception ignored) {
				// going offline is best-effort; friends see us offline after 3 minutes anyway
			}
		}
	}

	/** What we tell friends we're doing. */
	public static JsonObject activity(Minecraft mc) {
		JsonObject a = new JsonObject();
		a.addProperty("version", Compat.mcVersion());
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
		String event = Social.str(e, "event");
		JsonObject p = e.has("payload") && e.get("payload").isJsonObject() ? e.getAsJsonObject("payload") : new JsonObject();
		Screen screen = Compat.currentScreen();
		if (event.equals("message")) {
			if (screen instanceof ChatScreen chat && chat.isWith(Social.str(p, "from"))) {
				chat.reload();
			} else {
				Compat.toast("New message", Social.str(p, "name"));
			}
		} else if (event.equals("friends")) {
			String kind = Social.str(p, "kind");
			if (kind.equals("request")) Compat.toast("Friend request", Social.str(p, "name") + " wants to be friends");
			if (kind.equals("accepted")) Compat.toast("New friend", Social.str(p, "name") + " accepted your request");
		}
		if (screen instanceof FriendsScreen friends) friends.reload();
	}
}
