package dev.jacedeb.jacefriends;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;

/**
 * Talks to the Jace Launcher that started this game (voice calls happen in the
 * launcher). The launcher passes -Djacelauncher.link=PORT:TOKEN; without it the
 * game wasn't started from Jace Launcher, so calls aren't available.
 */
public final class LauncherLink {
	public static final String REQUIRED = "Jace Launcher required!";
	private static final HttpClient HTTP = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(2)).build();
	private static final String LINK = System.getProperty("jacelauncher.link", "");

	private LauncherLink() {}

	public static boolean available() {
		return LINK.contains(":");
	}

	private static JsonObject call(String method, String path, JsonObject body) throws Exception {
		if (!available()) throw new Social.SocialException(REQUIRED);
		String[] parts = LINK.split(":", 2);
		HttpRequest.Builder b = HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + parts[0] + path))
				.timeout(Duration.ofSeconds(5)).header("X-Jace-Token", parts[1]);
		if (body != null) b.header("Content-Type", "application/json").method(method, HttpRequest.BodyPublishers.ofString(body.toString()));
		else b.method(method, HttpRequest.BodyPublishers.noBody());
		HttpResponse<String> r;
		try {
			r = HTTP.send(b.build(), HttpResponse.BodyHandlers.ofString());
		} catch (Exception e) {
			throw new Social.SocialException("Jace Launcher isn't running - reopen it to make calls");
		}
		JsonObject json = r.body().isBlank() ? new JsonObject() : JsonParser.parseString(r.body()).getAsJsonObject();
		if (r.statusCode() >= 400) throw new Social.SocialException(Social.str(json, "error").isEmpty() ? "Call failed" : Social.str(json, "error"));
		return json;
	}

	/** {state: idle|calling|ringing|in-call, peer, peer_name, muted} */
	public static JsonObject status() throws Exception { return call("GET", "/call", null); }

	public static void start(String uuid, String name) throws Exception {
		JsonObject b = new JsonObject();
		b.addProperty("uuid", uuid);
		b.addProperty("name", name);
		call("POST", "/call", b);
	}

	public static void answer() throws Exception { call("POST", "/call/answer", new JsonObject()); }
	public static void hangUp() throws Exception { call("POST", "/call/hangup", new JsonObject()); }
	public static void toggleMute() throws Exception { call("POST", "/call/mute", new JsonObject()); }
}
