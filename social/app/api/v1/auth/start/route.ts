// Step 1 of sign-in: hand out a one-time "server id". The client then calls
// Mojang's session server with it (exactly what joining a Minecraft server does).
import { randomBytes } from "node:crypto";
import { db, handler } from "@/lib/server";

export const POST = handler(async () => {
  const serverId = randomBytes(15).toString("hex");
  const old = new Date(Date.now() - 10 * 60_000).toISOString();
  await db().from("auth_challenges").delete().lt("created_at", old);     // tidy up
  const { error } = await db().from("auth_challenges").insert({ server_id: serverId });
  if (error) throw error;
  return { server_id: serverId };
});
