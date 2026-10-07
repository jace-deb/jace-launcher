package dev.jacedeb.jacefriends;

import com.google.gson.JsonObject;
import net.minecraft.client.Minecraft;

import java.util.function.Consumer;

/**
 * Voice calls. The audio runs in Jace Launcher; the game only shows the call and
 * sends Call / Answer / Mute / Hang up to the launcher (see LauncherLink).
 */
public final class Calls {
	private static volatile JsonObject state = new JsonObject();
	private static String lastState = "idle";
	private static boolean polling;
	private static int ticks;

	private Calls() {}

	/** idle, calling, ringing or in-call */
	public static String state() {
		String s = Social.str(state, "state");
		return s.isEmpty() ? "idle" : s;
	}

	public static String peerName() {
		return Social.str(state, "peer_name");
	}

	public static boolean muted() {
		return state.has("muted") && state.get("muted").getAsBoolean();
	}

	/** Ask the launcher about calls once a second. */
	static void tick() {
		if (!LauncherLink.available() || polling || ++ticks % 20 != 0) return;
		polling = true;
		Social.async(LauncherLink::status).whenComplete((s, err) -> Minecraft.getInstance().execute(() -> {
			polling = false;
			state = err == null ? s : new JsonObject();
			String now = state();
			if (now.equals(lastState)) return;
			if (now.equals("ringing")) Compat.toast("Incoming call", peerName() + " is calling - press J to answer");
			if (now.equals("idle") && lastState.equals("in-call")) Compat.toast("Call ended", "");
			lastState = now;
			if (Compat.currentScreen() instanceof FriendsScreen f) f.callChanged();
		}));
	}

	/** Run a call action; errors (like "Jace Launcher required!") go to {@code status}. */
	public static void act(FriendsScreen.ThrowingRunnable work, Consumer<String> status) {
		if (!LauncherLink.available()) {
			status.accept(LauncherLink.REQUIRED);
			return;
		}
		Social.async(() -> {
			work.run();
			return LauncherLink.status();
		}).whenComplete((s, err) -> Minecraft.getInstance().execute(() -> {
			if (err != null) {
				status.accept(FriendsScreen.cause(err));
				return;
			}
			state = s;
			lastState = state();
			if (Compat.currentScreen() instanceof FriendsScreen f) f.callChanged();
		}));
	}

	public static void call(JsonObject friend, Consumer<String> status) {
		String uuid = Social.str(friend, "uuid");
		String name = Social.str(friend, "name");
		act(() -> LauncherLink.start(uuid, name), status);
	}
}
