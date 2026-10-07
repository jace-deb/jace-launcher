package dev.jacedeb.jacefriends;

import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import net.minecraft.client.Minecraft;
import net.minecraft.client.gui.components.Button;
import net.minecraft.client.gui.components.EditBox;
import net.minecraft.client.gui.screens.Screen;
import net.minecraft.network.chat.Component;
import net.minecraft.util.FormattedCharSequence;

import java.util.ArrayList;
import java.util.List;

/** Chat with one friend. */
public class ChatScreen extends Screen {
	private final Screen parent;
	private final JsonObject friend;
	private final String uuid;
	private final List<JsonObject> messages = new ArrayList<>();
	private EditBox input;
	private String draft = "";
	private String status = "Loading…";

	public ChatScreen(Screen parent, JsonObject friend) {
		super(Component.literal("Chat with " + Social.str(friend, "name")));
		this.parent = parent;
		this.friend = friend;
		this.uuid = Social.str(friend, "uuid");
		reload();
	}

	public boolean isWith(String other) {
		return uuid.equals(other);
	}

	public void reload() {
		Social.async(() -> {
			JsonObject r = Social.messages(uuid);
			Social.markRead(uuid);
			return r;
		}).whenComplete((r, err) -> Minecraft.getInstance().execute(() -> {
			if (err != null) {
				status = FriendsScreen.cause(err);
				return;
			}
			messages.clear();
			for (JsonElement e : r.getAsJsonArray("messages")) messages.add(e.getAsJsonObject());
			status = Social.describe(friend);
		}));
	}

	@Override
	protected void init() {
		int cx = width / 2;
		if (input != null) draft = input.getValue();
		input = new EditBox(font, cx - 160, height - 30, 256, 20, Component.literal("Message"));
		input.setMaxLength(500);
		input.setHint(Component.literal("Message " + Social.str(friend, "name") + "…"));
		input.setValue(draft);
		addRenderableWidget(input);
		setInitialFocus(input);
		addRenderableWidget(Button.builder(Component.literal("Send"), b -> send()).bounds(cx + 100, height - 30, 60, 20).build());
		addRenderableWidget(Button.builder(Component.literal("< Back"), b -> onClose()).bounds(6, 6, 60, 20).build());
		addRenderableWidget(Button.builder(Component.literal("Call"), b -> Calls.call(friend, s -> status = s)).bounds(width - 66, 6, 60, 20).build());
	}

	private void send() {
		String text = input.getValue().trim();
		if (text.isEmpty()) return;
		input.setValue("");
		Social.async(() -> {
			Social.send(uuid, text);
			return null;
		}).whenComplete((v, err) -> Minecraft.getInstance().execute(() -> {
			if (err != null) {
				status = FriendsScreen.cause(err);
				input.setValue(text);
			} else {
				reload();
			}
		}));
	}

	//? if >=1.21.9 {
	@Override
	public boolean keyPressed(net.minecraft.client.input.KeyEvent event) {
		if (Compat.isEnter(event.input()) && input.isFocused()) {
			send();
			return true;
		}
		return super.keyPressed(event);
	}
	//?} else {
	/*@Override
	public boolean keyPressed(int key, int scanCode, int modifiers) {
		if (Compat.isEnter(key) && input.isFocused()) {
			send();
			return true;
		}
		return super.keyPressed(key, scanCode, modifiers);
	}
	*///?}

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
		g.text(font, status, cx - font.width(status) / 2, 22, 0xFF8B919C);
		int left = cx - 160;
		int wrap = 320;
		int top = 38;
		int y = height - 40;
		// draw newest at the bottom, going up until we run out of room
		for (int i = messages.size() - 1; i >= 0 && y > top; i--) {
			JsonObject m = messages.get(i);
			boolean mine = Social.str(m, "sender").equals(Social.myUuid());
			List<FormattedCharSequence> lines = font.split(Component.literal(Social.str(m, "body")), wrap);
			y -= lines.size() * 10 + 12;
			if (y < top) break;
			g.text(font, mine ? "You" : Social.str(friend, "name"), left, y, mine ? 0xFF3DDC84 : 0xFF4F8FD6);
			int ly = y + 10;
			for (FormattedCharSequence line : lines) {
				g.text(font, line, left, ly, 0xFFE6E8EB);
				ly += 10;
			}
		}
		if (messages.isEmpty() && !status.equals("Loading…")) {
			String hint = "No messages yet - say hi!";
			g.text(font, hint, cx - font.width(hint) / 2, height / 2, 0xFF8B919C);
		}
	}

	@Override
	public void onClose() {
		Compat.setScreen(parent);
		if (parent instanceof FriendsScreen f) f.reload();
	}
}
