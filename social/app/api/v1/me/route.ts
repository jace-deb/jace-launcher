import { supabaseUrl, handler, me, publicProfile } from "@/lib/server";

export const GET = handler(async (req) => {
  const p = await me(req);
  return { ...publicProfile(p), inbox: p.inbox,
           realtime: { url: supabaseUrl(), key: process.env.SUPABASE_PUBLISHABLE_KEY } };
});
