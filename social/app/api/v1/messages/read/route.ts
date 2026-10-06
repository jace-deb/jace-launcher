// POST {with}: mark a friend's messages to me as read
import { body, cleanUuid, db, handler, me } from "@/lib/server";

export const POST = handler(async (req) => {
  const p = await me(req);
  const other = cleanUuid((await body<{ with?: string }>(req)).with);
  await db().from("messages").update({ read_at: new Date().toISOString() })
    .eq("sender", other).eq("recipient", p.uuid).is("read_at", null);
  return { ok: true };
});
