// Public status for the website: is the service up, and how many players use it.
// No personal data.
import { db, handler } from "@/lib/server";

export const GET = handler(async () => {
  const { count, error } = await db().from("profiles").select("uuid", { count: "exact", head: true })
    .not("signed_up", "is", null);
  if (error) throw error;
  return { ok: true, service: "jace-social", players: count ?? 0, time: new Date().toISOString() };
});
