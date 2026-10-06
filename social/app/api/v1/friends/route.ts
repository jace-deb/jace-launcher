// GET: friends (with online status + what they're doing), incoming and outgoing requests
// POST {name}: send a friend request (works even if they haven't used Jace Launcher yet)
// DELETE ?uuid=: remove a friend or cancel/decline a request
import {
  ApiError, body, cleanUuid, db, ensureProfile, friendsOf, handler, me, mojangLookup, notify, publicProfile,
  type Profile,
} from "@/lib/server";

export const GET = handler(async (req) => {
  const p = await me(req);
  const [friends, pending] = await Promise.all([
    friendsOf(p.uuid),
    db().from("friendships")
      .select("requester, addressee, created_at, a:profiles!friendships_requester_fkey(*), b:profiles!friendships_addressee_fkey(*)")
      .eq("status", "pending").or(`requester.eq.${p.uuid},addressee.eq.${p.uuid}`),
  ]);
  if (pending.error) throw pending.error;
  const { data: unread } = await db().from("messages").select("sender").eq("recipient", p.uuid).is("read_at", null);
  const unreadBy: Record<string, number> = {};
  for (const m of unread ?? []) unreadBy[m.sender] = (unreadBy[m.sender] ?? 0) + 1;
  return {
    friends: friends.map((f) => ({ ...publicProfile(f), unread: unreadBy[f.uuid] ?? 0 })),
    incoming: (pending.data ?? []).filter((r) => r.addressee === p.uuid).map((r) => publicProfile(r.a as unknown as Profile)),
    outgoing: (pending.data ?? []).filter((r) => r.requester === p.uuid).map((r) => publicProfile(r.b as unknown as Profile)),
  };
});

export const POST = handler(async (req) => {
  const p = await me(req);
  const { name } = await body<{ name?: string }>(req);
  const target = await mojangLookup(String(name ?? "").trim());
  if (target.uuid === p.uuid) throw new ApiError(400, "That's you!");
  const other = await ensureProfile(target.uuid, target.name);

  const { data: existing } = await db().from("friendships").select("*")
    .or(`and(requester.eq.${p.uuid},addressee.eq.${other.uuid}),and(requester.eq.${other.uuid},addressee.eq.${p.uuid})`)
    .maybeSingle();
  if (existing?.status === "accepted") throw new ApiError(409, `You're already friends with ${other.name}`);
  if (existing?.requester === p.uuid) throw new ApiError(409, `You already sent ${other.name} a request`);
  if (existing) {                                   // they asked us first: accept
    await db().from("friendships").update({ status: "accepted" }).eq("requester", other.uuid).eq("addressee", p.uuid);
    await notify([other.inbox], "friends", { kind: "accepted", uuid: p.uuid, name: p.name });
    return { status: "accepted", friend: publicProfile(other) };
  }
  const { error } = await db().from("friendships").insert({ requester: p.uuid, addressee: other.uuid, status: "pending" });
  if (error) throw error;
  await notify([other.inbox], "friends", { kind: "request", uuid: p.uuid, name: p.name });
  return { status: "pending", friend: publicProfile(other) };
});

export const DELETE = handler(async (req) => {
  const p = await me(req);
  const other = cleanUuid(new URL(req.url).searchParams.get("uuid"));
  const { data } = await db().from("friendships").delete()
    .or(`and(requester.eq.${p.uuid},addressee.eq.${other}),and(requester.eq.${other},addressee.eq.${p.uuid})`)
    .select("requester");
  const { data: o } = await db().from("profiles").select("inbox").eq("uuid", other).maybeSingle();
  if (data?.length && o) await notify([o.inbox], "friends", { kind: "removed", uuid: p.uuid });
  return { ok: true };
});
