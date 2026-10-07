package dev.jacedeb.jacefriends;

import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import net.minecraft.client.Minecraft;
import net.minecraft.client.gui.components.Button;
import net.minecraft.client.gui.screens.Screen;
import net.minecraft.client.server.IntegratedServer;
import net.minecraft.network.chat.Component;
import net.minecraft.server.level.ServerPlayer;

import java.net.ServerSocket;
import java.util.ArrayList;
import java.util.List;

/** Host your singleplayer world for friends and choose what each of them can do. */
public class HostScreen extends Screen {
	private static final int ROW = 24;
	private final Screen parent;
	private final List<JsonObject> friends = new ArrayList<>();
	private String status = "Loading friends…";
	private int page;

	public HostScreen(Screen parent) {
		super(Component.literal("Host world"));
		this.parent = parent;
		Social.async(() -> {
			if (!Social.signedIn()) JaceFriends.startLive(Social.signIn());
			return Social.friends();
		}).whenComplete((d, err) -> Minecraft.getInstance().execute(() -> {
			if (err != null) {
				status = FriendsScreen.cause(err);
			} else {
				for (JsonElement e : d.getAsJsonArray("friends")) friends.add(e.getAsJsonObject());
				friends.sort((a, b) -> Social.str(a, "name").compareToIgnoreCase(Social.str(b, "name")));
				status = "";
			}
			rebuildWidgets();
		}));
	}

	private int perPage() {
		return Math.max(1, (height - 64 - 60) / ROW);
	}

	@Override
	protected void init() {
		int cx = width / 2;
		int right = cx + 154;
		addRenderableWidget(roleButton("default", "Everyone else", right - 80, 36));

		int per = perPage();
		page = Math.min(page, Math.max(0, (friends.size() - 1) / per));
		int y = 64;
		for (int i = page * per; i < Math.min(friends.size(), (page + 1) * per); i++) {
			JsonObject f = friends.get(i);
			addRenderableWidget(roleButton(Social.str(f, "uuid"), Social.str(f, "name"), right - 80, y));
			y += ROW;
		}

		int by = height - 28;
		IntegratedServer sp = minecraft.getSingleplayerServer();
		if (sp != null && !sp.isPublished()) {
			addRenderableWidget(Button.builder(Component.literal("Start hosting"), b -> host()).bounds(cx - 154, by, 110, 20).build());
		}
		if (friends.size() > per) {
			addRenderableWidget(Button.builder(Component.literal("<"), b -> { page--; rebuildWidgets(); })
					.bounds(cx + 2, by, 20, 20).build()).active = page > 0;
			addRenderableWidget(Button.builder(Component.literal(">"), b -> { page++; rebuildWidgets(); })
					.bounds(cx + 24, by, 20, 20).build()).active = (page + 1) * per < friends.size();
		}
		addRenderableWidget(Button.builder(Component.literal("Done"), b -> onClose()).bounds(cx + 74, by, 80, 20).build());
	}

	private Button roleButton(String uuid, String name, int x, int y) {
		Roles.Role role = Roles.of(uuid);
		return Button.builder(Component.literal(role.label), b -> {
			Roles.set(uuid, role.next());
			reapply(name);
			rebuildWidgets();
		}).bounds(x, y, 80, 20).build();
	}

	/** If that friend is already in the world, give them the new role now. */
	private void reapply(String name) {
		IntegratedServer sp = minecraft.getSingleplayerServer();
		if (sp == null || !sp.isPublished()) return;
		sp.execute(() -> {
			for (ServerPlayer p : sp.getPlayerList().getPlayers()) {
				if (name.equals("Everyone else") || p.getName().getString().equalsIgnoreCase(name)) Roles.apply(sp, p, false);
			}
		});
	}

	private void host() {
		IntegratedServer sp = minecraft.getSingleplayerServer();
		if (sp == null) return;
		int port;
		try (ServerSocket s = new ServerSocket(0)) {
			port = s.getLocalPort();
		} catch (Exception e) {
			port = 25565;
		}
		status = Compat.publishLan(sp, port) ? "World opened! Waiting for e4all to give it an address…" : "Couldn't open the world";
		rebuildWidgets();
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
		int left = cx - 154;
		g.text(font, title.getString(), cx - font.width(title.getString()) / 2, 10, 0xFFFFFFFF);
		String top = status;
		IntegratedServer sp = minecraft.getSingleplayerServer();
		if (top.isEmpty() || (sp != null && sp.isPublished())) {
			top = sp != null && sp.isPublished()
					? (JaceFriends.hostingAddress != null ? "Hosting at " + JaceFriends.hostingAddress + " - friends click Join" : "Hosting - getting an address…")
					: "Choose what friends can do, then start hosting";
		}
		g.text(font, top, cx - font.width(top) / 2, 22, 0xFFA0A6B0);
		g.text(font, "Everyone else", left, 42, 0xFFFFFFFF);
		int per = perPage();
		int y = 64;
		for (int i = page * per; i < Math.min(friends.size(), (page + 1) * per); i++) {
			g.text(font, Social.str(friends.get(i), "name"), left, y + 6, 0xFFFFFFFF);
			y += ROW;
		}
		String help = Compat.isModLoaded("luckperms")
				? "LuckPerms groups: jace_visitor, jace_builder, jace_admin"
				: "Visitor: look only · Builder: build · Admin: op";
		g.text(font, help, cx - font.width(help) / 2, height - 44, 0xFF8B919C);
	}

	@Override
	public void onClose() {
		Compat.setScreen(parent);
	}
}
