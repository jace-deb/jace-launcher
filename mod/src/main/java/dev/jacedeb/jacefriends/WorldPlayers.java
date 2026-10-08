package dev.jacedeb.jacefriends;

import net.minecraft.client.Minecraft;
import net.minecraft.client.server.IntegratedServer;
import net.minecraft.server.level.ServerPlayer;

import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

/** Players in the world you're hosting (you first), for the permission menus. */
final class WorldPlayers {
	record Player(UUID uuid, String name, boolean host) {}

	private WorldPlayers() {}

	static UUID me() {
		String s = Compat.profileUuid();
		return UUID.fromString(s.replaceFirst("(\\w{8})(\\w{4})(\\w{4})(\\w{4})(\\w{12})", "$1-$2-$3-$4-$5"));
	}

	static List<Player> list() {
		List<Player> out = new ArrayList<>();
		UUID me = me();
		out.add(new Player(me, Minecraft.getInstance().getUser().getName(), true));
		IntegratedServer sp = Minecraft.getInstance().getSingleplayerServer();
		if (sp == null) return out;
		for (ServerPlayer p : new ArrayList<>(sp.getPlayerList().getPlayers())) {
			if (!p.getUUID().equals(me)) out.add(new Player(p.getUUID(), p.getName().getString(), false));
		}
		return out;
	}
}
