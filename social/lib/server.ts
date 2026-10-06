// Shared server helpers: database client, auth, live notifications, responses.
import { createHash, randomBytes } from "node:crypto";
import { createClient, type SupabaseClient } from "@supabase/supabase-js";

export const ONLINE_WINDOW_MS = 3 * 60 * 1000;   // heartbeat every 2 min, offline after 3
const SESSION_DAYS = 30;

let _db: SupabaseClient | null = null;
export function db(): SupabaseClient {
  if (!_db) {
    const url = process.env.SUPABASE_URL;
    const key = process.env.SUPABASE_SECRET_KEY;
    if (!url || !key) throw new ApiError(500, "Server is missing SUPABASE_URL / SUPABASE_SECRET_KEY");
    _db = createClient(url, key, { auth: { persistSession: false, autoRefreshToken: false } });
  }
  return _db;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

export type Profile = {
  uuid: string; name: string; inbox: string;
  activity: Activity | null; last_seen: string | null; signed_up: string | null;
};
export type Activity = {
  type: "launcher" | "playing" | "hosting";
  instance?: string; version?: string; server?: string; world?: string; address?: string;
};

export const token = () => randomBytes(32).toString("base64url");
export const sha256 = (s: string) => createHash("sha256").update(s).digest("hex");

/** Wrap a route handler: JSON errors, CORS-free (clients aren't browsers). */
export function handler(fn: (req: Request) => Promise<unknown>) {
  return async (req: Request) => {
    try {
      return Response.json(await fn(req));
    } catch (e) {
      if (e instanceof ApiError) return Response.json({ error: e.message }, { status: e.status });
      console.error(e);
      return Response.json({ error: "Server error" }, { status: 500 });
    }
  };
}

export async function body<T>(req: Request): Promise<T> {
  try { return (await req.json()) as T; } catch { throw new ApiError(400, "Expected a JSON body"); }
}

/** The signed-in player for this request (Authorization: Bearer <token>). */
export async function me(req: Request): Promise<Profile> {
  const auth = req.headers.get("authorization") ?? "";
  const t = auth.startsWith("Bearer ") ? auth.slice(7) : "";
  if (!t) throw new ApiError(401, "Not signed in");
  const { data } = await db().from("sessions").select("uuid, expires_at, profiles(*)")
    .eq("token_hash", sha256(t)).maybeSingle();
  if (!data || new Date(data.expires_at) < new Date()) throw new ApiError(401, "Session expired - sign in again");
  return data.profiles as unknown as Profile;
}

export async function createSession(uuid: string) {
  const t = token();
  const expires = new Date(Date.now() + SESSION_DAYS * 86400_000).toISOString();
  const { error } = await db().from("sessions").insert({ token_hash: sha256(t), uuid, expires_at: expires });
  if (error) throw error;
  return { token: t, expires_at: expires };
}

/** Find or create a profile row (players can be added as friends before they sign up). */
export async function ensureProfile(uuid: string, name: string, signingUp = false): Promise<Profile> {
  const { data: existing } = await db().from("profiles").select("*").eq("uuid", uuid).maybeSingle();
  if (existing) {
    const patch: Partial<Profile> = {};
    if (existing.name !== name) patch.name = name;
    if (signingUp && !existing.signed_up) patch.signed_up = new Date().toISOString();
    if (Object.keys(patch).length) await db().from("profiles").update(patch).eq("uuid", uuid);
    return { ...existing, ...patch } as Profile;
  }
  const row = { uuid, name, inbox: token(), signed_up: signingUp ? new Date().toISOString() : null };
  const { data, error } = await db().from("profiles").insert(row).select("*").single();
  if (error) throw error;
  return data as Profile;
}

/** Look up a Minecraft player by username (Mojang). */
export async function mojangLookup(name: string): Promise<{ uuid: string; name: string }> {
  if (!/^[A-Za-z0-9_]{1,16}$/.test(name)) throw new ApiError(400, "That isn't a valid Minecraft username");
  const r = await fetch(`https://api.mojang.com/users/profiles/minecraft/${encodeURIComponent(name)}`);
  if (r.status === 404 || r.status === 204) throw new ApiError(404, `No Minecraft player called "${name}"`);
  if (!r.ok) throw new ApiError(502, "Couldn't reach Mojang - try again");
  const d = await r.json();
  return { uuid: d.id, name: d.name };
}

/**
 * Live notification to players' private channels (Supabase Realtime broadcast).
 * Payloads only say *what changed* - never message text - so a leaked channel
 * name reveals nothing private; clients fetch details through the API.
 */
export async function notify(inboxes: string[], event: string, payload: Record<string, unknown>) {
  const url = process.env.SUPABASE_URL;
  const key = process.env.SUPABASE_SECRET_KEY;
  if (!url || !key || !inboxes.length) return;
  try {
    await fetch(`${url}/realtime/v1/api/broadcast`, {
      method: "POST",
      headers: { "Content-Type": "application/json", apikey: key, Authorization: `Bearer ${key}` },
      body: JSON.stringify({ messages: inboxes.map((topic) => ({ topic, event, payload, private: false })) }),
    });
  } catch (e) {
    console.error("realtime notify failed", e);   // notifications are best-effort
  }
}

export function isOnline(p: Pick<Profile, "last_seen">) {
  return !!p.last_seen && Date.now() - new Date(p.last_seen).getTime() < ONLINE_WINDOW_MS;
}

/** Public view of a player (what friends see). */
export function publicProfile(p: Profile) {
  const online = isOnline(p);
  return {
    uuid: p.uuid, name: p.name, online, uses_jace: !!p.signed_up,
    activity: online ? p.activity : null, last_seen: p.last_seen,
  };
}

/** Accepted friends of a player, as profile rows. */
export async function friendsOf(uuid: string): Promise<Profile[]> {
  const { data, error } = await db().from("friendships")
    .select("requester, addressee, a:profiles!friendships_requester_fkey(*), b:profiles!friendships_addressee_fkey(*)")
    .eq("status", "accepted").or(`requester.eq.${uuid},addressee.eq.${uuid}`);
  if (error) throw error;
  return (data ?? []).map((r) => (r.requester === uuid ? r.b : r.a) as unknown as Profile);
}

export async function areFriends(a: string, b: string): Promise<boolean> {
  const { data } = await db().from("friendships").select("status")
    .or(`and(requester.eq.${a},addressee.eq.${b}),and(requester.eq.${b},addressee.eq.${a})`).maybeSingle();
  return data?.status === "accepted";
}

export function cleanUuid(u: unknown): string {
  const s = String(u ?? "").replace(/-/g, "").toLowerCase();
  if (!/^[0-9a-f]{32}$/.test(s)) throw new ApiError(400, "Bad player id");
  return s;
}
