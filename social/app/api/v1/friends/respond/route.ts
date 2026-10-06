// POST {uuid, accept}: accept or decline an incoming friend request
import { ApiError, body, cleanUuid, db, handler, me, notify } from "@/lib/server";

export const POST = handler(async (req) => {
  const p = await me(req);
  const b = await body<{ uuid?: string; accept?: boolean }>(req);
  const other = cleanUuid(b.uuid);
  const q = db().from("friendships");
  const { data } = b.accept
    ? await q.update({ status: "accepted" }).eq("requester", other).eq("addressee", p.uuid).eq("status", "pending").select("requester")
    : await q.delete().eq("requester", other).eq("addressee", p.uuid).eq("status", "pending").select("requester");
  if (!data?.length) throw new ApiError(404, "No friend request from that player");
  if (b.accept) {
    const { data: o } = await db().from("profiles").select("inbox").eq("uuid", other).single();
    if (o) await notify([o.inbox], "friends", { kind: "accepted", uuid: p.uuid, name: p.name });
  }
  return { ok: true };
});
