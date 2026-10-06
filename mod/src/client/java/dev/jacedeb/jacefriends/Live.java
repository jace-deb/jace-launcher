package dev.jacedeb.jacefriends;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import net.minecraft.client.Minecraft;

import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.WebSocket;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.CompletionStage;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;
import java.util.function.Consumer;

/**
 * Live notifications over Supabase Realtime (Phoenix websocket protocol). We join
 * our own private, unguessable channel; payloads only say what changed.
 */
public final class Live implements WebSocket.Listener {
	private static final ScheduledExecutorService TIMER = Executors.newSingleThreadScheduledExecutor(r -> {
		Thread t = new Thread(r, "Jace Friends live");
		t.setDaemon(true);
		return t;
	});
	private final Consumer<JsonObject> onEvent;     // {event, payload}, delivered on the game thread
	private final StringBuilder partial = new StringBuilder();
	private volatile WebSocket socket;
	private volatile boolean wanted;
	private ScheduledFuture<?> heartbeat;
	private String url;
	private String topic;
	private int ref;

	public Live(Consumer<JsonObject> onEvent) {
		this.onEvent = onEvent;
	}

	public synchronized void start(JsonObject session) {
		JsonObject rt = session.getAsJsonObject("realtime");
		if (rt == null || !rt.has("url") || !rt.has("key") || rt.get("key").isJsonNull()) return;
		String host = rt.get("url").getAsString().replaceFirst("^http", "ws").replaceAll("/$", "");
		url = host + "/realtime/v1/websocket?apikey=" + URLEncoder.encode(rt.get("key").getAsString(), StandardCharsets.UTF_8)
				+ "&vsn=1.0.0";
		topic = "realtime:" + session.get("inbox").getAsString();
		wanted = true;
		connect();
	}

	public synchronized void stop() {
		wanted = false;
		if (heartbeat != null) heartbeat.cancel(false);
		if (socket != null) socket.sendClose(WebSocket.NORMAL_CLOSURE, "bye");
		socket = null;
	}

	private void connect() {
		if (!wanted) return;
		HttpClient.newHttpClient().newWebSocketBuilder().buildAsync(URI.create(url), this)
				.exceptionally(e -> {
					retry();
					return null;
				});
	}

	private void retry() {
		if (wanted) TIMER.schedule(this::connect, 10, TimeUnit.SECONDS);
	}

	private synchronized void send(String t, String event, JsonObject payload) {
		WebSocket ws = socket;
		if (ws == null) return;
		JsonObject m = new JsonObject();
		m.addProperty("topic", t);
		m.addProperty("event", event);
		m.add("payload", payload);
		m.addProperty("ref", String.valueOf(++ref));
		m.addProperty("join_ref", "1");
		ws.sendText(m.toString(), true);
	}

	@Override
	public void onOpen(WebSocket ws) {
		socket = ws;
		JsonObject broadcast = new JsonObject();
		broadcast.addProperty("ack", false);
		broadcast.addProperty("self", false);
		JsonObject presence = new JsonObject();
		presence.addProperty("key", "");
		JsonObject config = new JsonObject();
		config.add("broadcast", broadcast);
		config.add("presence", presence);
		config.addProperty("private", false);
		JsonObject payload = new JsonObject();
		payload.add("config", config);
		send(topic, "phx_join", payload);
		if (heartbeat != null) heartbeat.cancel(false);
		heartbeat = TIMER.scheduleAtFixedRate(() -> send("phoenix", "heartbeat", new JsonObject()), 25, 25, TimeUnit.SECONDS);
		ws.request(1);
	}

	@Override
	public CompletionStage<?> onText(WebSocket ws, CharSequence data, boolean last) {
		partial.append(data);
		if (last) {
			String text = partial.toString();
			partial.setLength(0);
			try {
				JsonObject msg = JsonParser.parseString(text).getAsJsonObject();
				if ("broadcast".equals(Social.str(msg, "event")) && msg.get("payload").isJsonObject()) {
					JsonObject inner = msg.getAsJsonObject("payload");
					Minecraft.getInstance().execute(() -> onEvent.accept(inner));
				}
			} catch (Exception ignored) {
				// not a message we care about
			}
		}
		ws.request(1);
		return null;
	}

	@Override
	public CompletionStage<?> onClose(WebSocket ws, int status, String reason) {
		socket = null;
		retry();
		return null;
	}

	@Override
	public void onError(WebSocket ws, Throwable error) {
		socket = null;
		retry();
	}
}
