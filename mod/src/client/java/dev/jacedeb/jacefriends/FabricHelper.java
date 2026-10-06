package dev.jacedeb.jacefriends;

import net.fabricmc.loader.api.FabricLoader;

final class FabricHelper {
	private FabricHelper() {}

	static boolean hasE4mc() {
		return FabricLoader.getInstance().isModLoaded("e4mc_minecraft") || FabricLoader.getInstance().isModLoaded("e4mc");
	}
}
