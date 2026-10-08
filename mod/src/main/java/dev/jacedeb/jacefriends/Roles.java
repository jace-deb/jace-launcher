package dev.jacedeb.jacefriends;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import net.minecraft.client.Minecraft;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerPlayer;

import java.nio.file.Files;
import java.nio.file.Path;

/**
 * Roles for players who join a world you host:
 *   Visitor - adventure mode (can look around, can't build)
 *   Builder - survival mode
 *   Admin   - operator
 * Friends get their own role; everyone else gets the default role. Applied with
 * normal commands when a player joins, so it works the same on every version.
 * If LuckPerms is installed, players are also put in jace_visitor / jace_builder /
 * jace_admin groups so you can give each group custom permissions.
 */
public final class Roles {
	public enum Role {
		VISITOR("Visitor"), BUILDER("Builder"), ADMIN("Admin");
		public final String label;
		Role(String label) { this.label = label; }
		public Role next() { return values()[(ordinal() + 1) % values().length]; }
	}

	private static JsonObject data;

	private Roles() {}

	private static Path file() {
		return Minecraft.getInstance().gameDirectory.toPath().resolve("config").resolve("jacefriends-roles.json");
	}

	private static synchronized JsonObject data() {
		if (data == null) {
			try {
				data = JsonParser.parseString(Files.readString(file())).getAsJsonObject();
			} catch (Exception e) {
				data = new JsonObject();
			}
		}
		return data;
	}

	private static synchronized void save() {
		try {
			Files.createDirectories(file().getParent());
			Files.writeString(file(), data().toString());
		} catch (Exception ignored) {
			// roles just won't persist this time
		}
	}

	public static Role of(String uuid) {
		JsonObject d = data();
		String key = d.has(uuid) ? uuid : "default";
		try {
			return Role.valueOf(d.has(key) ? d.get(key).getAsString() : "BUILDER");
		} catch (IllegalArgumentException e) {
			return Role.BUILDER;
		}
	}

	public static Role defaultRole() {
		return of("default");
	}

	/** Does everyone with this role get WorldEdit when they join? (Admins always do.) */
	public static boolean worldEdit(Role role) {
		JsonObject d = data();
		return role == Role.ADMIN || (d.has("worldedit:" + role.name()) && d.get("worldedit:" + role.name()).getAsBoolean());
	}

	public static void setWorldEdit(Role role, boolean on) {
		data().addProperty("worldedit:" + role.name(), on);
		save();
	}

	public static void set(String uuid, Role role) {
		data().addProperty(uuid, role.name());
		save();
	}

	/** Called (on the server thread) when someone joins a world we're hosting. */
	public static void apply(MinecraftServer server, ServerPlayer player, boolean joined) {
		String uuid = player.getUUID().toString().replace("-", "");
		if (uuid.equals(Social.myUuid())) return;            // that's us, the host
		String name = player.getName().getString();
		Role role = of(uuid);
		switch (role) {
			case VISITOR -> run(server, "gamemode adventure " + name);
			case BUILDER -> run(server, "gamemode survival " + name);
			case ADMIN -> { }
		}
		// Admins are operators. WorldEdit can also be switched on per role (see WorldEditScreen).
		boolean we = worldEdit(role);
		if (WorldEditScreen.usesLuckPerms()) {
			Compat.setOp(server, player, role == Role.ADMIN);
			try {
				LuckPermsBridge.setUserPermission(player.getUUID(), "worldedit.*", we ? Boolean.TRUE : null);
			} catch (RuntimeException ignored) {
				// LuckPerms not started yet
			}
		} else {
			Compat.setOp(server, player, role == Role.ADMIN || we);
		}
		if (Compat.isModLoaded("luckperms")) {
			try {
				LuckPermsBridge.ensureRoleGroups()
						.thenCompose(v -> LuckPermsBridge.setUserGroup(player.getUUID(), "jace_" + role.name().toLowerCase()));
			} catch (RuntimeException ignored) {
				// LuckPerms not started yet: they keep their old group
			}
		}
		Minecraft.getInstance().execute(() -> Compat.toast(joined ? "Friend joined" : "Role changed", name + (joined ? " joined as " : " is now ") + role.label));
	}

	private static void run(MinecraftServer server, String command) {
		try {
			Compat.runCommand(server, command);
		} catch (Exception ignored) {
			// e.g. LuckPerms group already exists
		}
	}
}
