// GET: ICE servers for a voice call. STUN always; TURN relay (for players behind
// strict NATs) from Cloudflare Realtime when CLOUDFLARE_TURN_KEY_ID and
// CLOUDFLARE_TURN_API_TOKEN are set. Credentials are short-lived.
import { handler, me } from "@/lib/server";

type IceServer = { urls: string | string[]; username?: string; credential?: string };

export const GET = handler(async (req) => {
  await me(req);
  const servers: IceServer[] = [{ urls: ["stun:stun.cloudflare.com:3478", "stun:stun.l.google.com:19302"] }];
  const keyId = process.env.CLOUDFLARE_TURN_KEY_ID;
  const apiToken = process.env.CLOUDFLARE_TURN_API_TOKEN;
  if (keyId && apiToken) {
    try {
      const r = await fetch(`https://rtc.live.cloudflare.com/v1/turn/keys/${keyId}/credentials/generate-ice-servers`, {
        method: "POST",
        headers: { Authorization: `Bearer ${apiToken}`, "Content-Type": "application/json" },
        body: JSON.stringify({ ttl: 6 * 3600 }),
      });
      if (r.ok) {
        const d = await r.json();
        const list: IceServer[] = Array.isArray(d.iceServers) ? d.iceServers : d.iceServers ? [d.iceServers] : [];
        // keep only TURN entries (we already have STUN); port 53 is blocked by many browsers/networks
        for (const s of list) {
          const urls = (Array.isArray(s.urls) ? s.urls : [s.urls]).filter((u) => u.startsWith("turn") && !u.includes(":53"));
          if (urls.length) servers.push({ urls, username: s.username, credential: s.credential });
        }
      } else {
        console.error("Cloudflare TURN credentials failed", r.status);
      }
    } catch (e) {
      console.error("Cloudflare TURN credentials failed", e);
    }
  }
  return { ice_servers: servers, relay: servers.length > 1 };
});
