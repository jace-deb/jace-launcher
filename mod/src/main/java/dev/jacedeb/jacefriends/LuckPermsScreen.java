package dev.jacedeb.jacefriends;

import net.minecraft.client.Minecraft;
import net.minecraft.client.gui.components.Button;
import net.minecraft.client.gui.components.EditBox;
import net.minecraft.client.gui.screens.Screen;
import net.minecraft.network.chat.Component;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;

/**
 * A LuckPerms menu: edit group permissions and players' groups without /lp,
 * and give yourself /lp access (there's no server console in a hosted world to do it).
 */
public class LuckPermsScreen extends Screen {
	private static final int ROW = 24;
	private final Screen parent;
	private final boolean ready;
	private boolean playersTab;
	private String status = "";
	private List<String> groups = new ArrayList<>();
	private int groupIndex;
	private int page;
	private List<String[]> perms = new ArrayList<>();
	private final Map<UUID, String> playerGroups = new HashMap<>();
	private Boolean canUseLp;
	private EditBox nodeBox;
	private String nodeText = "";
	private boolean newValue = true;

	public LuckPermsScreen(Screen parent) {
		super(Component.literal("LuckPerms"));
		this.parent = parent;
		ready = Compat.isModLoaded("luckperms") && Minecraft.getInstance().getSingleplayerServer() != null;
		if (!ready) {
			status = Compat.isModLoaded("luckperms") ? "Open a world first"
					: "Install LuckPerms: Jace Launcher > your instance > Mods > Server add-ons";
			return;
		}
		run(LuckPermsBridge.ensureRoleGroups(), null);
		checkLp();
	}

	private void checkLp() {
		LuckPermsBridge.userHas(WorldPlayers.me(), "luckperms.*").whenComplete((v, err) ->
				Minecraft.getInstance().execute(() -> { canUseLp = err == null && v; refreshUi(); }));
	}

	/** Wait for a LuckPerms change, then refresh (and show any error). */
	private void run(CompletableFuture<?> work, String done) {
		work.whenComplete((v, err) -> Minecraft.getInstance().execute(() -> {
			status = err != null ? FriendsScreen.cause(err) : done != null ? done : status;
			reload();
			refreshUi();
		}));
	}

	private void reload() {
		try {
			groups = LuckPermsBridge.groups();
			groupIndex = Math.max(0, Math.min(groupIndex, groups.size() - 1));
			perms = groups.isEmpty() ? new ArrayList<>() : LuckPermsBridge.permissions(group());
		} catch (RuntimeException e) {
			status = FriendsScreen.cause(e);
		}
		if (playersTab) {
			for (WorldPlayers.Player p : WorldPlayers.list()) {
				LuckPermsBridge.userGroup(p.uuid()).thenAccept(g -> Minecraft.getInstance().execute(() -> {
					playerGroups.put(p.uuid(), g);
					refreshUi();
				}));
			}
		}
	}

	private String group() {
		return groups.isEmpty() ? "default" : groups.get(groupIndex);
	}

	private int perPage() {
		return Math.max(1, (height - 90 - 60) / ROW);
	}

	@Override
	protected void init() {
		int cx = width / 2;
		int left = cx - 154;
		int right = cx + 154;
		int by = height - 28;
		addRenderableWidget(Button.builder(Component.literal("Done"), b -> onClose()).bounds(right - 80, by, 80, 20).build());
		if (!ready) return;
		if (groups.isEmpty()) reload();

		Button groupsTab = addRenderableWidget(Button.builder(Component.literal("Groups"), b -> { playersTab = false; page = 0; reload(); refreshUi(); })
				.bounds(left, 34, 70, 20).build());
		Button playersTabBtn = addRenderableWidget(Button.builder(Component.literal("Players"), b -> { playersTab = true; page = 0; reload(); refreshUi(); })
				.bounds(left + 74, 34, 70, 20).build());
		groupsTab.active = playersTab;
		playersTabBtn.active = !playersTab;
		Button lp = addRenderableWidget(Button.builder(Component.literal(Boolean.TRUE.equals(canUseLp) ? "You can use /lp" : "Let me use /lp"), b ->
				run(LuckPermsBridge.setUserPermission(WorldPlayers.me(), "luckperms.*", true).thenRun(this::checkLp),
						"Done - you can now use /lp in chat")).bounds(right - 110, 34, 110, 20).build());
		lp.active = !Boolean.TRUE.equals(canUseLp);

		int per = perPage();
		int y = 86;
		if (!playersTab) {
			addRenderableWidget(Button.builder(Component.literal("<"), b -> { groupIndex = (groupIndex + groups.size() - 1) % Math.max(1, groups.size()); page = 0; reload(); refreshUi(); })
					.bounds(left, 60, 20, 20).build());
			addRenderableWidget(Button.builder(Component.literal(">"), b -> { groupIndex = (groupIndex + 1) % Math.max(1, groups.size()); page = 0; reload(); refreshUi(); })
					.bounds(left + 150, 60, 20, 20).build());
			page = Math.min(page, Math.max(0, (perms.size() - 1) / per));
			for (int i = page * per; i < Math.min(perms.size(), (page + 1) * per); i++) {
				String node = perms.get(i)[0];
				boolean value = Boolean.parseBoolean(perms.get(i)[1]);
				addRenderableWidget(Button.builder(Component.literal(value ? "Allow" : "Deny"), b ->
						run(LuckPermsBridge.setGroupPermission(group(), node, !value), null)).bounds(right - 124, y, 60, 20).build());
				addRenderableWidget(Button.builder(Component.literal("Remove"), b ->
						run(LuckPermsBridge.setGroupPermission(group(), node, null), "Removed " + node)).bounds(right - 60, y, 60, 20).build());
				y += ROW;
			}
			// add a permission
			if (nodeBox != null) nodeText = nodeBox.getValue();
			nodeBox = new EditBox(font, left, height - 54, 180, 20, Component.literal("Permission"));
			nodeBox.setHint(Component.literal("permission, e.g. worldedit.*"));
			nodeBox.setMaxLength(200);
			nodeBox.setValue(nodeText);
			addRenderableWidget(nodeBox);
			addRenderableWidget(Button.builder(Component.literal(newValue ? "Allow" : "Deny"), b -> { newValue = !newValue; refreshUi(); })
					.bounds(left + 184, height - 54, 56, 20).build());
			addRenderableWidget(Button.builder(Component.literal("Add"), b -> {
				String node = nodeBox.getValue().trim();
				if (node.isEmpty() || node.contains(" ")) { status = "Type a permission without spaces"; return; }
				nodeText = "";
				nodeBox.setValue("");
				run(LuckPermsBridge.setGroupPermission(group(), node, newValue), (newValue ? "Allowed " : "Denied ") + node + " for " + group());
			}).bounds(left + 244, height - 54, 64, 20).build());
			pager(perms.size(), per, cx, by);
		} else {
			List<WorldPlayers.Player> players = WorldPlayers.list();
			page = Math.min(page, Math.max(0, (players.size() - 1) / per));
			for (int i = page * per; i < Math.min(players.size(), (page + 1) * per); i++) {
				WorldPlayers.Player p = players.get(i);
				String current = playerGroups.getOrDefault(p.uuid(), "…");
				addRenderableWidget(Button.builder(Component.literal(current), b -> {
					if (groups.isEmpty()) return;
					int at = groups.indexOf(current);
					String next = groups.get((at + 1) % groups.size());
					run(LuckPermsBridge.setUserGroup(p.uuid(), next), p.name() + " is now in " + next);
				}).bounds(right - 110, y, 110, 20).build());
				y += ROW;
			}
			pager(players.size(), per, cx, by);
		}
	}

	private void pager(int total, int per, int cx, int by) {
		if (total <= per) return;
		addRenderableWidget(Button.builder(Component.literal("<"), b -> { page--; refreshUi(); })
				.bounds(cx - 22, by, 20, 20).build()).active = page > 0;
		addRenderableWidget(Button.builder(Component.literal(">"), b -> { page++; refreshUi(); })
				.bounds(cx + 2, by, 20, 20).build()).active = (page + 1) * per < total;
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
		String top = status.isEmpty() ? (playersTab ? "Click a player's group to change it" : "Permissions for the selected group") : status;
		g.text(font, font.plainSubstrByWidth(top, 308), cx - Math.min(308, font.width(top)) / 2, 22, 0xFFA0A6B0);
		if (!ready) return;
		int per = perPage();
		int y = 86;
		if (!playersTab) {
			String name = group();
			g.text(font, name, left + 85 - font.width(name) / 2, 66, 0xFF3DDC84);
			for (int i = page * per; i < Math.min(perms.size(), (page + 1) * per); i++) {
				g.text(font, font.plainSubstrByWidth(perms.get(i)[0], 180), left, y + 6, 0xFFFFFFFF);
				y += ROW;
			}
			if (perms.isEmpty()) g.text(font, "No permissions in this group yet", left, y + 6, 0xFF8B919C);
		} else {
			List<WorldPlayers.Player> players = WorldPlayers.list();
			for (int i = page * per; i < Math.min(players.size(), (page + 1) * per); i++) {
				WorldPlayers.Player p = players.get(i);
				g.text(font, p.name() + (p.host() ? " (you)" : ""), left, y + 6, 0xFFFFFFFF);
				y += ROW;
			}
		}
	}

	/** Redraw the buttons, unless the screen isn't open yet (LuckPerms can answer instantly). */
	private void refreshUi() {
		if (minecraft != null) rebuildWidgets();
	}

	@Override
	public void onClose() {
		Compat.setScreen(parent);
	}
}
