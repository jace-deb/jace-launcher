package dev.jacedeb.jacefriends;

import net.luckperms.api.LuckPerms;
import net.luckperms.api.LuckPermsProvider;
import net.luckperms.api.model.group.Group;
import net.luckperms.api.model.user.User;
import net.luckperms.api.node.Node;
import net.luckperms.api.node.NodeType;
import net.luckperms.api.node.types.InheritanceNode;
import net.luckperms.api.node.types.PermissionNode;

import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;

/**
 * Talks to LuckPerms through its API, so the menus work without /lp (in a singleplayer
 * or hosted world there's no server console to give anyone /lp access in the first place).
 * Only touch this class when LuckPerms is installed: it's the only one that loads LuckPerms classes.
 */
final class LuckPermsBridge {
	/** Groups Jace Friends' roles map to (see Roles). */
	static final String[] ROLE_GROUPS = {"jace_visitor", "jace_builder", "jace_admin"};

	private LuckPermsBridge() {}

	private static LuckPerms api() {
		try {
			return LuckPermsProvider.get();
		} catch (IllegalStateException e) {
			throw new Social.SocialException("LuckPerms starts with the world - open a world first");
		}
	}

	/** Make sure the role groups exist (default always does). */
	static CompletableFuture<Void> ensureRoleGroups() {
		LuckPerms lp = api();
		List<CompletableFuture<Group>> all = new ArrayList<>();
		for (String g : ROLE_GROUPS) all.add(lp.getGroupManager().createAndLoadGroup(g));
		return CompletableFuture.allOf(all.toArray(new CompletableFuture[0]));
	}

	static List<String> groups() {
		List<String> out = new ArrayList<>();
		for (Group g : api().getGroupManager().getLoadedGroups()) out.add(g.getName());
		out.sort((a, b) -> rank(a) != rank(b) ? rank(a) - rank(b) : a.compareTo(b));
		return out;
	}

	private static int rank(String g) {
		if (g.equals("default")) return 0;
		for (int i = 0; i < ROLE_GROUPS.length; i++) if (g.equals(ROLE_GROUPS[i])) return i + 1;
		return 10;
	}

	/** A group's own permissions as {node, "true"/"false"}. */
	static List<String[]> permissions(String group) {
		Group g = api().getGroupManager().getGroup(group);
		List<String[]> out = new ArrayList<>();
		if (g == null) return out;
		for (PermissionNode n : g.getNodes(NodeType.PERMISSION)) out.add(new String[]{n.getPermission(), String.valueOf(n.getValue())});
		out.sort((a, b) -> a[0].compareTo(b[0]));
		return out;
	}

	/** Set (true/false) or remove (null) a permission on a group; creates the group if needed. */
	static CompletableFuture<Void> setGroupPermission(String group, String node, Boolean value) {
		LuckPerms lp = api();
		return lp.getGroupManager().createAndLoadGroup(group).thenCompose(g -> {
			g.data().clear(n -> isPermission(n, node));
			if (value != null) g.data().add(PermissionNode.builder(node).value(value).build());
			return lp.getGroupManager().saveGroup(g);
		});
	}

	static CompletableFuture<Boolean> groupHas(String group, String node) {
		return api().getGroupManager().loadGroup(group).thenApply(g -> g.isPresent()
				&& g.get().getCachedData().getPermissionData().checkPermission(node).asBoolean());
	}

	/** Set (true/false) or remove (null) a permission on one player. */
	static CompletableFuture<Void> setUserPermission(UUID player, String node, Boolean value) {
		return api().getUserManager().modifyUser(player, u -> {
			u.data().clear(n -> isPermission(n, node));
			if (value != null) u.data().add(PermissionNode.builder(node).value(value).build());
		});
	}

	/** Does the player have this permission (directly or through a group)? */
	static CompletableFuture<Boolean> userHas(UUID player, String node) {
		return api().getUserManager().loadUser(player)
				.thenApply(u -> u.getCachedData().getPermissionData().checkPermission(node).asBoolean());
	}

	static CompletableFuture<String> userGroup(UUID player) {
		return api().getUserManager().loadUser(player).thenApply(User::getPrimaryGroup);
	}

	/** Put the player in exactly this group (replacing their other groups). */
	static CompletableFuture<Void> setUserGroup(UUID player, String group) {
		return api().getGroupManager().createAndLoadGroup(group).thenCompose(g ->
				api().getUserManager().modifyUser(player, u -> {
					u.data().clear(NodeType.INHERITANCE::matches);
					u.data().add(InheritanceNode.builder(group).build());
				}));
	}

	private static boolean isPermission(Node n, String node) {
		return n instanceof PermissionNode p && p.getPermission().equals(node);
	}
}
