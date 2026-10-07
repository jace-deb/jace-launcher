package dev.jacedeb.jacefriends;

//? if neoforge {
/*import net.minecraft.client.Minecraft;
import net.minecraft.client.gui.components.Button;
import net.neoforged.bus.api.IEventBus;
import net.neoforged.fml.common.Mod;
import net.neoforged.neoforge.client.event.ClientChatReceivedEvent;
import net.neoforged.neoforge.client.event.RegisterKeyMappingsEvent;
import net.neoforged.neoforge.client.event.ScreenEvent;
import net.neoforged.neoforge.common.NeoForge;

/^* NeoForge entry point (client only). ^/
@Mod("jacefriends")
public class JaceFriendsNeoForge {
	public JaceFriendsNeoForge(IEventBus modBus) {
		//? if >=1.21.9 {
		boolean client = net.neoforged.fml.loading.FMLEnvironment.getDist().isClient();
		//?} else
		/^boolean client = net.neoforged.fml.loading.FMLEnvironment.dist.isClient();^/
		if (!client) return;
		modBus.addListener((RegisterKeyMappingsEvent e) -> e.register(JaceFriends.createKey()));
		//? if >=1.20.5 {
		NeoForge.EVENT_BUS.addListener((net.neoforged.neoforge.client.event.ClientTickEvent.Post e) -> JaceFriends.tick(Minecraft.getInstance()));
		//?} else {
		/^NeoForge.EVENT_BUS.addListener((net.neoforged.neoforge.event.TickEvent.ClientTickEvent e) -> {
			if (e.phase == net.neoforged.neoforge.event.TickEvent.Phase.END) JaceFriends.tick(Minecraft.getInstance());
		});
		^///?}
		NeoForge.EVENT_BUS.addListener((ClientChatReceivedEvent e) -> JaceFriends.onGameMessage(e.getMessage()));
		NeoForge.EVENT_BUS.addListener((ScreenEvent.Init.Post e) -> {
			for (Button b : JaceFriends.screenButtons(e.getScreen(), e.getScreen().width, e.getScreen().height)) e.addListener(b);
		});
		NeoForge.EVENT_BUS.addListener((net.neoforged.neoforge.event.entity.player.PlayerEvent.PlayerLoggedInEvent e) -> {
			if (e.getEntity() instanceof net.minecraft.server.level.ServerPlayer p) JaceFriends.onPlayerJoin(p);
		});
	}
}
*///?}
