package dev.jacedeb.jacefriends;

import net.minecraft.client.gui.Font;
import net.minecraft.util.FormattedCharSequence;

/** Text/rectangle drawing over whichever GUI drawing API this Minecraft version has. */
public final class Draw {
	//? if >=26.1 {
	private final net.minecraft.client.gui.GuiGraphicsExtractor g;

	public Draw(net.minecraft.client.gui.GuiGraphicsExtractor g) {
		this.g = g;
	}

	public void text(Font font, String s, int x, int y, int color) {
		g.text(font, s, x, y, color);
	}

	public void text(Font font, FormattedCharSequence s, int x, int y, int color) {
		g.text(font, s, x, y, color);
	}
	//?} else {
	/*private final net.minecraft.client.gui.GuiGraphics g;

	public Draw(net.minecraft.client.gui.GuiGraphics g) {
		this.g = g;
	}

	public void text(Font font, String s, int x, int y, int color) {
		g.drawString(font, s, x, y, color);
	}

	public void text(Font font, FormattedCharSequence s, int x, int y, int color) {
		g.drawString(font, s, x, y, color);
	}
	*///?}

	public void fill(int x1, int y1, int x2, int y2, int color) {
		g.fill(x1, y1, x2, y2, color);
	}
}
