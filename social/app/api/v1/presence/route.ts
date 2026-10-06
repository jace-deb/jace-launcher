// POST {activity} every ~2 minutes while the launcher or game is open.
// activity: {type: launcher|playing|hosting, instance?, version?, server?, world?, address?} or null to go offline.
import { ApiError, body, db, friendsOf, handler, isOnline, me, notify, type Activity } from "@/lib/server";

const clip = (v: unknown, n = 80) => (typeof v === "string" ? v.slice(0, n) : undefined);

export const POST = handler(async (req) => {
  const p = await me(req);
  const b = await body<{ activity?: Activity | null; offline?: boolean }>(req);
  let activity: Activity | null = null;
  if (!b.offline && b.activity) {
    if (!["launcher", "playing", "hosting"].includes(b.activity.type)) throw new ApiError(400, "Bad activity type");
    activity = {
      type: b.activity.type, instance: clip(b.activity.instance), version: clip(b.activity.version, 32),
      server: clip(b.activity.server, 255), world: clip(b.activity.world), address: clip(b.activity.address, 255),
    };
  }
  const wasOnline = isOnline(p);
  const last_seen = b.offline ? null : new Date().toISOString();
  await db().from("profiles").update({ activity, last_seen }).eq("uuid", p.uuid);
  // tell friends only when something visible changed (keeps notifications low)
  if (wasOnline === !!b.offline || JSON.stringify(p.activity) !== JSON.stringify(activity)) {
    const friends = await friendsOf(p.uuid);
    await notify(friends.map((f) => f.inbox), "presence", { uuid: p.uuid });
  }
  return { ok: true };
});
