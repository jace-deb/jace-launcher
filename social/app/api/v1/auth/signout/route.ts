import { db, handler, me, sha256 } from "@/lib/server";

export const POST = handler(async (req) => {
  const p = await me(req);
  const t = (req.headers.get("authorization") ?? "").slice(7);
  await db().from("sessions").delete().eq("token_hash", sha256(t));
  await db().from("profiles").update({ last_seen: null, activity: null }).eq("uuid", p.uuid);
  return { ok: true };
});
