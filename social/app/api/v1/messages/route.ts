// GET ?with=<uuid>&before=<id>: chat history with a friend (newest 50, oldest first)
// POST {to, body}: send a message to a friend
import { ApiError, areFriends, body, cleanUuid, db, handler, me, notify } from "@/lib/server";

export const GET = handler(async (req) => {
  const p = await me(req);
  const params = new URL(req.url).searchParams;
  const other = cleanUuid(params.get("with"));
  let q = db().from("messages").select("id, sender, recipient, body, created_at, read_at")
    .or(`and(sender.eq.${p.uuid},recipient.eq.${other}),and(sender.eq.${other},recipient.eq.${p.uuid})`)
    .order("id", { ascending: false }).limit(50);
  const before = Number(params.get("before"));
  if (before) q = q.lt("id", before);
  const { data, error } = await q;
  if (error) throw error;
  return { messages: (data ?? []).reverse() };
});

export const POST = handler(async (req) => {
  const p = await me(req);
  const b = await body<{ to?: string; body?: string }>(req);
  const to = cleanUuid(b.to);
  const text = String(b.body ?? "").trim();
  if (!text) throw new ApiError(400, "Message is empty");
  if (text.length > 500) throw new ApiError(400, "Messages can be up to 500 characters");
  if (!(await areFriends(p.uuid, to))) throw new ApiError(403, "You can only message friends");
  const minuteAgo = new Date(Date.now() - 60_000).toISOString();
  const { count } = await db().from("messages").select("id", { count: "exact", head: true })
    .eq("sender", p.uuid).gt("created_at", minuteAgo);
  if ((count ?? 0) >= 20) throw new ApiError(429, "Slow down a little - try again in a minute");
  const { data, error } = await db().from("messages").insert({ sender: p.uuid, recipient: to, body: text })
    .select("id, sender, recipient, body, created_at, read_at").single();
  if (error) throw error;
  const { data: o } = await db().from("profiles").select("inbox").eq("uuid", to).single();
  if (o) await notify([o.inbox], "message", { from: p.uuid, name: p.name, id: data.id });
  return { message: data };
});
