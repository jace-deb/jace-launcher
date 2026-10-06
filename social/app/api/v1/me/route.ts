import { handler, me, publicProfile } from "@/lib/server";

export const GET = handler(async (req) => {
  const p = await me(req);
  return { ...publicProfile(p), inbox: p.inbox,
           realtime: { url: process.env.SUPABASE_URL, key: process.env.SUPABASE_PUBLISHABLE_KEY } };
});
