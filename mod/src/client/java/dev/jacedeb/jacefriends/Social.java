package dev.jacedeb.jacefriends;

import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import net.fabricmc.loader.api.FabricLoader;
import net.minecraft.client.Minecraft;
import net.minecraft.client.User;

import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.time.Instant;
import java.util.Map;
import java.util.concurrent.Callable;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.stream.Collectors;

/**
 * Jace Social API client (same server as Jace Launcher's Friends page).
 * Sign-in works like joining a Minecraft server: Mojang confirms the account,
 * so the game's access token is only ever sent to Mojang.
 */
public final class Social {
	public static final String BASE = System.getProperty("jacefriends.url", "https://jace-social.vercel.app");
	private static final HttpClient HTTP = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(15)).build();
	private static final ExecutorService IO = Executors.newFixedThreadPool(2, r -> {
		Thread t = new Thread(r, "Jace Friends");
		t.setDaemon(true);
		return t;
	});
	private static volatile JsonObject session;

	public static class SocialException extends RuntimeException {
		public SocialException(String msg) { super(msg); }
	}

	private Social() {}

	/** Run work off the game thread. */
	public static <T> CompletableFuture<T> async(Callable<T> work) {
		return CompletableFuture.supplyAsync(() -> {
			try {
				return work.call();
			} catch (SocialException e) {
				throw e;
			} catch (Exception e) {
				throw new SocialException("Can't reach Jace Social (" + e.getClass().getSimpleName() + ")");
			}
		}, IO);
	}

	public static String myUuid() {
		return Minecraft.getInstance().getUser().getProfileId().toString().replace("-", "");
	}

	private static Path sessionFile() {
		return FabricLoader.getInstance().getConfigDir().resolve("jacefriends-session.json");
	}

	public static synchronized JsonObject session() {
		if (session != null && session.get("uuid").getAsString().equals(myUuid())
				&& Instant.parse(session.get("expires_at").getAsString()).isAfter(Instant.now())) {
			return session;
		}
		try {
			JsonObject all = JsonParser.parseString(Files.readString(sessionFile())).getAsJsonObject();
			if (all.has(myUuid())) {
				JsonObject s = all.getAsJsonObject(myUuid());
				if (Instant.parse(s.get("expires_at").getAsString()).isAfter(Instant.now())) {
					session = s;
					return s;
				}
			}
		} catch (Exception ignored) {
			// no saved session yet
		}
		return null;
	}

	public static boolean signedIn() {
		return session() != null;
	}

	/** Verify this Minecraft account with Jace Social. Blocking. */
	public static synchronized JsonObject signIn() throws Exception {
		User user = Minecraft.getInstance().getUser();
		String token = user.getAccessToken();
		if (token == null || token.isBlank() || token.equals("0") || token.equals("FabricMC")) {
			throw new SocialException("Friends and chat need a Microsoft account (offline accounts can't be verified).");
		}
		JsonObject start = call("POST", "/api/v1/auth/start", new JsonObject(), null, false).getAsJsonObject();
		String serverId = start.get("server_id").getAsString();
		JsonObject join = new JsonObject();
		join.addProperty("accessToken", token);
		join.addProperty("selectedProfile", myUuid());
		join.addProperty("serverId", serverId);
		HttpResponse<String> r = HTTP.send(HttpRequest.newBuilder(URI.create("https://sessionserver.mojang.com/session/minecraft/join"))
				.timeout(Duration.ofSeconds(20)).header("Content-Type", "application/json")
				.POST(HttpRequest.BodyPublishers.ofString(join.toString())).build(), HttpResponse.BodyHandlers.ofString());
		if (r.statusCode() != 204 && r.statusCode() != 200) {
			throw new SocialException("Mojang didn't accept the sign-in. Restart the game from your launcher and try again.");
		}
		JsonObject finish = new JsonObject();
		finish.addProperty("name", user.getName());
		finish.addProperty("server_id", serverId);
		JsonObject s = call("POST", "/api/v1/auth/finish", finish, null, false).getAsJsonObject();
		JsonObject all;
		try {
			all = JsonParser.parseString(Files.readString(sessionFile())).getAsJsonObject();
		} catch (Exception e) {
			all = new JsonObject();
		}
		all.add(myUuid(), s);
		Files.writeString(sessionFile(), all.toString());
		session = s;
		return s;
	}

	public static JsonElement call(String method, String path, JsonElement body, Map<String, String> params, boolean auth) throws Exception {
		return call(method, path, body, params, auth, true);
	}

	private static JsonElement call(String method, String path, JsonElement body, Map<String, String> params,
									boolean auth, boolean retry) throws Exception {
		String url = BASE + path;
		if (params != null && !params.isEmpty()) {
			url += "?" + params.entrySet().stream()
					.map(e -> e.getKey() + "=" + URLEncoder.encode(e.getValue(), StandardCharsets.UTF_8))
					.collect(Collectors.joining("&"));
		}
		HttpRequest.Builder b = HttpRequest.newBuilder(URI.create(url)).timeout(Duration.ofSeconds(20));
		if (auth) {
			JsonObject s = session();
			if (s == null) s = signIn();
			b.header("Authorization", "Bearer " + s.get("token").getAsString());
		}
		if (body != null) {
			b.header("Content-Type", "application/json").method(method, HttpRequest.BodyPublishers.ofString(body.toString()));
		} else {
			b.method(method, HttpRequest.BodyPublishers.noBody());
		}
		HttpResponse<String> r = HTTP.send(b.build(), HttpResponse.BodyHandlers.ofString());
		if (r.statusCode() == 401 && auth && retry) {     // session expired: sign in again once
			session = null;
			signIn();
			return call(method, path, body, params, true, false);
		}
		JsonElement json;
		try {
			json = JsonParser.parseString(r.body());
		} catch (Exception e) {
			json = new JsonObject();
		}
		if (r.statusCode() >= 400) {
			String err = json.isJsonObject() && json.getAsJsonObject().has("error")
					? json.getAsJsonObject().get("error").getAsString() : "Jace Social error (" + r.statusCode() + ")";
			throw new SocialException(err);
		}
		return json;
	}

	// --- API -----------------------------------------------------------------------

	public static JsonObject friends() throws Exception {
		return call("GET", "/api/v1/friends", null, null, true).getAsJsonObject();
	}

	public static JsonObject addFriend(String name) throws Exception {
		JsonObject b = new JsonObject();
		b.addProperty("name", name.trim());
		return call("POST", "/api/v1/friends", b, null, true).getAsJsonObject();
	}

	public static void respond(String uuid, boolean accept) throws Exception {
		JsonObject b = new JsonObject();
		b.addProperty("uuid", uuid);
		b.addProperty("accept", accept);
		call("POST", "/api/v1/friends/respond", b, null, true);
	}

	public static void removeFriend(String uuid) throws Exception {
		call("DELETE", "/api/v1/friends", null, Map.of("uuid", uuid), true);
	}

	public static JsonObject messages(String withUuid) throws Exception {
		return call("GET", "/api/v1/messages", null, Map.of("with", withUuid), true).getAsJsonObject();
	}

	public static void send(String to, String text) throws Exception {
		JsonObject b = new JsonObject();
		b.addProperty("to", to);
		b.addProperty("body", text);
		call("POST", "/api/v1/messages", b, null, true);
	}

	public static void markRead(String withUuid) throws Exception {
		JsonObject b = new JsonObject();
		b.addProperty("with", withUuid);
		call("POST", "/api/v1/messages/read", b, null, true);
	}

	public static void presence(JsonObject activity, boolean offline) throws Exception {
		JsonObject b = new JsonObject();
		b.add("activity", activity);
		b.addProperty("offline", offline);
		call("POST", "/api/v1/presence", b, null, true);
	}

	// --- helpers for friend rows ----------------------------------------------------

	public static String str(JsonObject o, String key) {
		return o != null && o.has(key) && !o.get(key).isJsonNull() ? o.get(key).getAsString() : "";
	}

	public static JsonObject activity(JsonObject f) {
		return f.has("activity") && f.get("activity").isJsonObject() ? f.getAsJsonObject("activity") : null;
	}

	public static String describe(JsonObject f) {
		if (!f.get("online").getAsBoolean()) {
			return f.has("uses_jace") && !f.get("uses_jace").getAsBoolean() ? "Hasn't joined Jace yet" : "Offline";
		}
		JsonObject a = activity(f);
		String type = str(a, "type");
		if (type.equals("hosting")) {
			String world = str(a, "world");
			return "Hosting \"" + (world.isEmpty() ? "a world" : world) + "\" " + str(a, "version");
		}
		if (type.equals("playing")) {
			String server = str(a, "server");
			return "Playing " + str(a, "version") + (server.isEmpty() ? "" : " on " + server);
		}
		return "Online";
	}

	/** Address to join this friend at, or "" if they aren't hosting / on a server. */
	public static String joinAddress(JsonObject f) {
		if (!f.get("online").getAsBoolean()) return "";
		JsonObject a = activity(f);
		return switch (str(a, "type")) {
			case "hosting" -> str(a, "address");
			case "playing" -> str(a, "server");
			default -> "";
		};
	}
}
