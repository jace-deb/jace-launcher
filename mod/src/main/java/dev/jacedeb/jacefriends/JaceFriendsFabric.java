package dev.jacedeb.jacefriends;

//? if fabric {
import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientLifecycleEvents;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;
import net.fabricmc.fabric.api.client.message.v1.ClientReceiveMessageEvents;
import net.fabricmc.fabric.api.client.screen.v1.ScreenEvents;
import net.fabricmc.fabric.api.client.screen.v1.Screens;
import net.minecraft.client.gui.components.Button;

/** Fabric (and Quilt) entry point. */
public class JaceFriendsFabric implements ClientModInitializer {
	@Override
	public void onInitializeClient() {
		//? if >=26.1 {
		net.fabricmc.fabric.api.client.keymapping.v1.KeyMappingHelper.registerKeyMapping(JaceFriends.createKey());
		//?} else {
		/*net.fabricmc.fabric.api.client.keybinding.v1.KeyBindingHelper.registerKeyBinding(JaceFriends.createKey());
		*///?}
		ClientTickEvents.END_CLIENT_TICK.register(JaceFriends::tick);
		ClientReceiveMessageEvents.GAME.register((message, overlay) -> JaceFriends.onGameMessage(message.getString()));
		ScreenEvents.AFTER_INIT.register((mc, screen, w, h) -> {
			Button b = JaceFriends.friendsButton(screen, w);
			//? if >=26.1 {
			if (b != null) Screens.getWidgets(screen).add(b);
			//?} else {
			/*if (b != null) Screens.getButtons(screen).add(b);
			*///?}
		});
		ClientLifecycleEvents.CLIENT_STOPPING.register(mc -> JaceFriends.stopping());
	}
}
//?}
