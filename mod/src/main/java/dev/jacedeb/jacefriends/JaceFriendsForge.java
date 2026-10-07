package dev.jacedeb.jacefriends;

//? if forge {
/*import net.minecraft.client.Minecraft;
import net.minecraft.client.gui.components.Button;
import net.minecraftforge.api.distmarker.Dist;
import net.minecraftforge.client.event.ClientChatReceivedEvent;
import net.minecraftforge.client.event.RegisterKeyMappingsEvent;
import net.minecraftforge.client.event.ScreenEvent;
import net.minecraftforge.common.MinecraftForge;
import net.minecraftforge.event.TickEvent;
import net.minecraftforge.fml.common.Mod;
import net.minecraftforge.fml.javafmlmod.FMLJavaModLoadingContext;
import net.minecraftforge.fml.loading.FMLEnvironment;

/^* Forge (1.20.1) entry point (client only). ^/
@Mod("jacefriends")
public class JaceFriendsForge {
	public JaceFriendsForge() {
		if (FMLEnvironment.dist != Dist.CLIENT) return;
		FMLJavaModLoadingContext.get().getModEventBus()
				.addListener((RegisterKeyMappingsEvent e) -> e.register(JaceFriends.createKey()));
		MinecraftForge.EVENT_BUS.addListener((TickEvent.ClientTickEvent e) -> {
			if (e.phase == TickEvent.Phase.END) JaceFriends.tick(Minecraft.getInstance());
		});
		MinecraftForge.EVENT_BUS.addListener((ClientChatReceivedEvent e) -> JaceFriends.onGameMessage(e.getMessage()));
		MinecraftForge.EVENT_BUS.addListener((ScreenEvent.Init.Post e) -> {
			for (Button b : JaceFriends.screenButtons(e.getScreen(), e.getScreen().width, e.getScreen().height)) e.addListener(b);
		});
		MinecraftForge.EVENT_BUS.addListener((net.minecraftforge.event.entity.player.PlayerEvent.PlayerLoggedInEvent e) -> {
			if (e.getEntity() instanceof net.minecraft.server.level.ServerPlayer p) JaceFriends.onPlayerJoin(p);
		});
	}
}
*///?}
