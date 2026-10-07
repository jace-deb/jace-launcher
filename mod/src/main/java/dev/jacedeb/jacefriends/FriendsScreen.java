package dev.jacedeb.jacefriends;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import net.minecraft.client.Minecraft;
import net.minecraft.client.gui.components.Button;
import net.minecraft.client.gui.components.EditBox;
import net.minecraft.client.gui.screens.Screen;
import net.minecraft.client.gui.screens.TitleScreen;
import net.minecraft.client.server.IntegratedServer;
import net.minecraft.network.chat.Component;

import java.util.ArrayList;
import java.util.List;

/** Friends list: requests, friends with live status, join and chat. */
public class FriendsScreen extends Screen {
	private static final int ROW = 24;
	private final Screen parent;
	private JsonObject data;
	private String status = "Loading…";
	private int page;
	private EditBox addBox;
	private String addText = "";
	private final List<Row> rows = new ArrayList<>();

	private record Row(String kind, JsonObject f) {}

	public FriendsScreen(Screen parent) {
		super(Component.literal("Friends"));
		this.parent = parent;
		reload();
	}

	public void reload() {
		Social.async(() -> {
			if (!Social.signedIn()) JaceFriends.startLive(Social.signIn());
			return Social.friends();
		}).whenComplete((d, err) -> Minecraft.getInstance().execute(() -> {
			if (err != null) {
				status = cause(err);
			} else {
				data = d;
				int online = 0;
				for (JsonElement e : d.getAsJsonArray("friends")) if (e.getAsJsonObject().get("online").getAsBoolean()) online++;
				status = "Signed in as " + Minecraft.getInstance().getUser().getName() + " · " + online + " online";
			}
			rebuildWidgets();
		}));
	}

	static String cause(Throwable t) {
		while (t.getCause() != null && !(t instanceof Social.SocialException)) t = t.getCause();
		return t.getMessage() == null ? "Something went wrong" : t.getMessage();
	}

	private void collectRows() {
		rows.clear();
		if (data == null) return;
		for (JsonElement e : data.getAsJsonArray("incoming")) rows.add(new Row("incoming", e.getAsJsonObject()));
		List<JsonObject> friends = new ArrayList<>();
		for (JsonElement e : data.getAsJsonArray("friends")) friends.add(e.getAsJsonObject());
		friends.sort((a, b) -> {
			int c = Boolean.compare(b.get("online").getAsBoolean(), a.get("online").getAsBoolean());
			return c != 0 ? c : Social.str(a, "name").compareToIgnoreCase(Social.str(b, "name"));
		});
		for (JsonObject f : friends) rows.add(new Row("friend", f));
		for (JsonElement e : data.getAsJsonArray("outgoing")) rows.add(new Row("outgoing", e.getAsJsonObject()));
	}

	private int perPage() {
		return Math.max(1, (height - 64 - 36 - (inCall() ? ROW : 0)) / ROW);
	}

	private static boolean inCall() {
		return !Calls.state().equals("idle");
	}

	private void setStatus(String s) {
		status = s;
	}

	/** The launcher says the call changed (ringing, answered, ended). */
	void callChanged() {
		rebuildWidgets();
	}

	/** Answer / Mute / Hang up, above the bottom buttons while there's a call. */
	private void callButtons(int cx, int y) {
		String state = Calls.state();
		int x = cx + 154;
		x -= 70;
		addRenderableWidget(Button.builder(Component.literal(state.equals("ringing") ? "Decline" : "Hang up"),
				b -> Calls.act(LauncherLink::hangUp, this::setStatus)).bounds(x, y, 70, 20).build());
		if (state.equals("ringing")) {
			x -= 64;
			addRenderableWidget(Button.builder(Component.literal("Answer"), b -> Calls.act(LauncherLink::answer, this::setStatus))
					.bounds(x, y, 62, 20).build());
		} else if (state.equals("in-call")) {
			x -= 64;
			addRenderableWidget(Button.builder(Component.literal(Calls.muted() ? "Unmute" : "Mute"),
					b -> Calls.act(LauncherLink::toggleMute, this::setStatus)).bounds(x, y, 62, 20).build());
		}
	}

	private static String callText() {
		return switch (Calls.state()) {
			case "calling" -> "Calling " + Calls.peerName() + "…";
			case "ringing" -> Calls.peerName() + " is calling you";
			default -> "In a call with " + Calls.peerName() + (Calls.muted() ? " (muted)" : "");
		};
	}

	@Override
	protected void init() {
		int cx = width / 2;
		if (addBox != null) addText = addBox.getValue();
		addBox = new EditBox(font, cx - 150, 34, 196, 20, Component.literal("Minecraft username"));
		addBox.setHint(Component.literal("Add a friend by username"));
		addBox.setMaxLength(16);
		addBox.setValue(addText);
		addRenderableWidget(addBox);
		addRenderableWidget(Button.builder(Component.literal("Add"), b -> addFriend()).bounds(cx + 50, 34, 50, 20).build());
		addRenderableWidget(Button.builder(Component.literal("Refresh"), b -> {
			status = "Loading…";
			reload();
		}).bounds(cx + 104, 34, 50, 20).build());

		collectRows();
		int per = perPage();
		page = Math.min(page, Math.max(0, (rows.size() - 1) / per));
		int y = 64;
		int right = cx + 154;
		for (int i = page * per; i < Math.min(rows.size(), (page + 1) * per); i++) {
			Row r = rows.get(i);
			String uuid = Social.str(r.f, "uuid");
			int x = right;
			if (r.kind.equals("incoming")) {
				x -= 60;
				addRenderableWidget(Button.builder(Component.literal("Decline"), b -> act(() -> Social.respond(uuid, false)))
						.bounds(x, y, 60, 20).build());
				x -= 56;
				addRenderableWidget(Button.builder(Component.literal("Accept"), b -> act(() -> Social.respond(uuid, true)))
						.bounds(x, y, 54, 20).build());
			} else if (r.kind.equals("outgoing")) {
				x -= 56;
				addRenderableWidget(Button.builder(Component.literal("Cancel"), b -> act(() -> Social.removeFriend(uuid)))
						.bounds(x, y, 56, 20).build());
			} else {
				int unread = r.f.has("unread") ? r.f.get("unread").getAsInt() : 0;
				x -= 56;
				addRenderableWidget(Button.builder(Component.literal(unread > 0 ? "Chat (" + unread + ")" : "Chat"),
						b -> Compat.setScreen(new ChatScreen(this, r.f))).bounds(x, y, 56, 20).build());
				if (r.f.get("online").getAsBoolean() && Calls.state().equals("idle")) {
					x -= 42;
					addRenderableWidget(Button.builder(Component.literal("Call"), b -> Calls.call(r.f, this::setStatus))
							.bounds(x, y, 40, 20).build());
				}
				if (!Social.joinAddress(r.f).isEmpty()) {
					x -= 46;
					addRenderableWidget(Button.builder(Component.literal("Join"), b -> join(r.f)).bounds(x, y, 44, 20).build());
				}
			}
			y += ROW;
		}

		int by = height - 28;
		if (inCall()) callButtons(cx, by - ROW);
		IntegratedServer sp = minecraft.getSingleplayerServer();
		if (sp != null && !sp.isPublished()) {
			addRenderableWidget(Button.builder(Component.literal("Host this world for friends"), b -> Compat.setScreen(new HostScreen(this)))
					.bounds(cx - 154, by, 150, 20).build());
		}
		if (rows.size() > per) {
			addRenderableWidget(Button.builder(Component.literal("<"), b -> { page--; rebuildWidgets(); })
					.bounds(cx + 2, by, 20, 20).build()).active = page > 0;
			addRenderableWidget(Button.builder(Component.literal(">"), b -> { page++; rebuildWidgets(); })
					.bounds(cx + 24, by, 20, 20).build()).active = (page + 1) * per < rows.size();
		}
		addRenderableWidget(Button.builder(Component.literal("Done"), b -> onClose()).bounds(cx + 74, by, 80, 20).build());
	}

	private void act(ThrowingRunnable work) {
		status = "…";
		Social.async(() -> {
			work.run();
			return null;
		}).whenComplete((v, err) -> Minecraft.getInstance().execute(() -> {
			if (err != null) status = cause(err);
			reload();
		}));
	}

	interface ThrowingRunnable {
		void run() throws Exception;
	}

	private void addFriend() {
		String name = addBox.getValue().trim();
		if (name.isEmpty()) return;
		status = "Sending request…";
		Social.async(() -> Social.addFriend(name)).whenComplete((r, err) -> Minecraft.getInstance().execute(() -> {
			if (err != null) {
				status = cause(err);
				rebuildWidgets();
				return;
			}
			addBox.setValue("");
			addText = "";
			JsonObject f = r.getAsJsonObject("friend");
			status = Social.str(r, "status").equals("accepted") ? "You and " + Social.str(f, "name") + " are now friends!"
					: "Friend request sent to " + Social.str(f, "name");
			reload();
		}));
	}

	private void join(JsonObject f) {
		String addr = Social.joinAddress(f);
		String version = Social.str(Social.activity(f), "version");
		if (!version.isEmpty() && !version.equals(Compat.mcVersion())) {
			status = Social.str(f, "name") + " is on Minecraft " + version + " - use that version to join";
			return;
		}
		if (Minecraft.getInstance().level != null) {
			status = "Leave your world first (Save and Quit), then click Join";
			return;
		}
		Compat.connect(new TitleScreen(), addr, Social.str(f, "name") + "'s world");
	}

	//? if >=26.1 {
	@Override
	public void extractRenderState(net.minecraft.client.gui.GuiGraphicsExtractor g, int mouseX, int mouseY, float delta) {
		super.extractRenderState(g, mouseX, mouseY, delta);
		drawContent(new Draw(g));
	}
	//?} else {
	/*@Override
	public void render(net.minecraft.client.gui.GuiGraphics g, int mouseX, int mouseY, float delta) {
		//? if <1.20.2
		/^renderBackground(g);^/
		super.render(g, mouseX, mouseY, delta);
		drawContent(new Draw(g));
	}
	*///?}

	private void drawContent(Draw g) {
		int cx = width / 2;
		g.text(font, title.getString(), cx - font.width(title.getString()) / 2, 10, 0xFFFFFFFF);
		g.text(font, status, cx - font.width(status) / 2, 22, 0xFFA0A6B0);
		int per = perPage();
		int y = 64;
		int left = cx - 154;
		for (int i = page * per; i < Math.min(rows.size(), (page + 1) * per); i++) {
			Row r = rows.get(i);
			JsonObject f = r.f;
			boolean online = f.get("online").getAsBoolean();
			String type = Social.str(Social.activity(f), "type");
			int dot = !online ? 0xFF6B717C : type.equals("hosting") ? 0xFFB07CF0 : type.equals("playing") ? 0xFF4F8FD6 : 0xFF3DDC84;
			g.fill(left, y + 6, left + 6, y + 12, r.kind.equals("friend") ? dot : 0xFFE0B44A);
			g.text(font, Social.str(f, "name"), left + 10, y + 1, 0xFFFFFFFF);
			String line = switch (r.kind) {
				case "incoming" -> "Wants to be friends";
				case "outgoing" -> "Request sent";
				default -> Social.describe(f);
			};
			g.text(font, font.plainSubstrByWidth(line, 170), left + 10, y + 11, 0xFF8B919C);
			y += ROW;
		}
		if (inCall()) {
			g.fill(left, height - 52 + 6, left + 6, height - 52 + 12, 0xFF3DDC84);
			g.text(font, font.plainSubstrByWidth(callText(), 170), left + 10, height - 52 + 6, 0xFFFFFFFF);
		}
		if (data != null && rows.isEmpty()) {
			String hint = "No friends yet - add one by their Minecraft username above";
			g.text(font, hint, cx - font.width(hint) / 2, 80, 0xFF8B919C);
		}
	}

	@Override
	public void onClose() {
		Compat.setScreen(parent);
	}
}
