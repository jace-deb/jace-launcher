package dev.jacedeb.jacefriends;

import net.minecraft.client.Minecraft;
import net.minecraft.client.gui.components.Button;
import net.minecraft.client.gui.screens.Screen;
import net.minecraft.client.server.IntegratedServer;
import net.minecraft.network.chat.Component;
import net.minecraft.server.level.ServerPlayer;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * Turn WorldEdit on or off for each player, and for each role (friends who join later).
 *
 * In singleplayer / hosted worlds, "Allow Cheats" never puts you on the ops list, and the
 * newest WorldEdit only checks that list, so //wand says you don't have permission even
 * though you can run other commands. "On" puts the player on the ops list. On Fabric with
 * LuckPerms it gives the worldedit.* permission instead (no operator powers needed).
 */
public class WorldEditScreen extends Screen {
	private static final int ROW = 24;
	private final Screen parent;
	private final String problem;
	private String status = "";
	private final Map<UUID, Boolean> state = new HashMap<>();
	private List<WorldPlayers.Player> players = List.of();

	public WorldEditScreen(Screen parent) {
		super(Component.literal("WorldEdit permissions"));
		this.parent = parent;
		if (!Compat.isModLoaded("worldedit")) {
			problem = "Install WorldEdit: Jace Launcher > your instance > Mods > Server add-ons";
		} else if (Minecraft.getInstance().getSingleplayerServer() == null) {
			problem = "Open a world first";
		} else {
			problem = null;
			refresh();
		}
	}

	/** WorldEdit asks LuckPerms only on Fabric; elsewhere it checks the ops list. */
	static boolean usesLuckPerms() {
		boolean fabric;
		//? if fabric {
		fabric = true;
		//?} else
		/*fabric = false;*/
		return fabric && Compat.isModLoaded("luckperms");
	}

	private void refresh() {
		players = WorldPlayers.list();
		IntegratedServer sp = Minecraft.getInstance().getSingleplayerServer();
		if (sp == null) return;
		if (usesLuckPerms()) {
			for (WorldPlayers.Player p : players) {
				LuckPermsBridge.userHas(p.uuid(), "worldedit.*").whenComplete((v, err) -> Minecraft.getInstance().execute(() -> {
					if (err != null) status = FriendsScreen.cause(err);
					else state.put(p.uuid(), v);
					refreshUi();
				}));
			}
		} else {
			sp.execute(() -> {
				Map<UUID, Boolean> ops = new HashMap<>();
				for (ServerPlayer p : new ArrayList<>(sp.getPlayerList().getPlayers())) ops.put(p.getUUID(), Compat.isOp(sp, p));
				Minecraft.getInstance().execute(() -> { state.putAll(ops); refreshUi(); });
			});
		}
	}

	private void toggle(WorldPlayers.Player who, boolean on) {
		IntegratedServer sp = Minecraft.getInstance().getSingleplayerServer();
		if (sp == null) return;
		String done = "WorldEdit " + (on ? "on" : "off") + " for " + who.name();
		if (usesLuckPerms()) {
			LuckPermsBridge.setUserPermission(who.uuid(), "worldedit.*", on ? Boolean.TRUE : null)
					.whenComplete((v, err) -> Minecraft.getInstance().execute(() -> {
						status = err != null ? FriendsScreen.cause(err) : done;
						refresh();
					}));
			return;
		}
		sp.execute(() -> {
			ServerPlayer p = sp.getPlayerList().getPlayer(who.uuid());
			if (p != null) Compat.setOp(sp, p, on);
			Minecraft.getInstance().execute(() -> {
				status = p == null ? who.name() + " left the world" : done + (on ? " (they're now an operator)" : "");
				refresh();
			});
		});
	}

	@Override
	protected void init() {
		int cx = width / 2;
		int right = cx + 154;
		addRenderableWidget(Button.builder(Component.literal("Done"), b -> onClose()).bounds(right - 80, height - 28, 80, 20).build());
		if (problem != null) return;
		int y = 48;
		for (WorldPlayers.Player p : players) {
			Boolean on = state.get(p.uuid());
			addRenderableWidget(Button.builder(Component.literal(on == null ? "…" : on ? "On" : "Off"),
					b -> toggle(p, on == null || !on)).bounds(right - 60, y, 60, 20).build());
			y += ROW;
			if (y > height - 140) break;
		}
		y += 14;
		for (Roles.Role r : new Roles.Role[]{Roles.Role.BUILDER, Roles.Role.VISITOR}) {
			boolean on = Roles.worldEdit(r);
			addRenderableWidget(Button.builder(Component.literal(on ? "On" : "Off"), b -> {
				Roles.setWorldEdit(r, !on);
				status = "Friends who join as " + r.label + " will " + (on ? "not get" : "get") + " WorldEdit";
				refreshUi();
			}).bounds(right - 60, y, 60, 20).build());
			y += ROW;
		}
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
		String top = problem != null ? problem : status.isEmpty() ? "Who can use WorldEdit (//wand, //set, ...)" : status;
		g.text(font, font.plainSubstrByWidth(top, 308), cx - Math.min(308, font.width(top)) / 2, 22, 0xFFA0A6B0);
		if (problem != null) return;
		int y = 48;
		for (WorldPlayers.Player p : players) {
			g.text(font, p.name() + (p.host() ? " (you)" : ""), left, y + 6, 0xFFFFFFFF);
			y += ROW;
			if (y > height - 140) break;
		}
		g.text(font, "Friends who join later (Admins always get it)", left, y + 2, 0xFF8B919C);
		y += 14;
		for (Roles.Role r : new Roles.Role[]{Roles.Role.BUILDER, Roles.Role.VISITOR}) {
			g.text(font, r.label + "s", left, y + 6, 0xFFFFFFFF);
			y += ROW;
		}
		if (!usesLuckPerms()) {
			String note = "\"On\" makes the player an operator - that's how WorldEdit checks here";
			g.text(font, font.plainSubstrByWidth(note, 308), left, height - 44, 0xFF8B919C);
		}
	}

	/** Redraw the buttons, unless the screen isn't open yet. */
	private void refreshUi() {
		if (minecraft != null) rebuildWidgets();
	}

	@Override
	public void onClose() {
		Compat.setScreen(parent);
	}
}
