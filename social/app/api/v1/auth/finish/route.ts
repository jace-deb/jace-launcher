// Step 2 of sign-in: ask Mojang whether this player really joined our server id.
// Only the real owner of the Minecraft account can make that true, and we never
// see their Microsoft password or Minecraft token.
import { supabaseUrl, ApiError, body, createSession, db, ensureProfile, handler } from "@/lib/server";

export const POST = handler(async (req) => {
  const { name, server_id } = await body<{ name?: string; server_id?: string }>(req);
  if (!name || !server_id) throw new ApiError(400, "name and server_id are required");
  const { data: challenge } = await db().from("auth_challenges").delete().eq("server_id", server_id)
    .select("created_at").maybeSingle();
  if (!challenge || Date.now() - new Date(challenge.created_at).getTime() > 5 * 60_000)
    throw new ApiError(400, "Sign-in expired - try again");

  const r = await fetch("https://sessionserver.mojang.com/session/minecraft/hasJoined?" +
    new URLSearchParams({ username: name, serverId: server_id }));
  if (r.status !== 200) throw new ApiError(401, "Minecraft couldn't confirm this account. Sign in with Microsoft again.");
  const mc = await r.json() as { id: string; name: string };

  const profile = await ensureProfile(mc.id, mc.name, true);
  const session = await createSession(profile.uuid);
  return {
    ...session,
    uuid: profile.uuid, name: profile.name, inbox: profile.inbox,
    realtime: { url: supabaseUrl(), key: process.env.SUPABASE_PUBLISHABLE_KEY },
  };
});
