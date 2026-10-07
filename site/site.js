// Fill the download buttons from the latest GitHub release and highlight the
// visitor's platform. Without JavaScript the buttons still link to the releases page.
const REPO = "jace-deb/jace-launcher";

const PLATFORMS = [
  { id: "windows", suffix: "-windows-x64.exe", label: "Windows", note: "10 / 11" },
  { id: "mac-arm", suffix: "-macos-arm64.app.zip", label: "macOS", note: "Apple Silicon" },
  { id: "mac-intel", suffix: "-macos-x86_64.app.zip", label: "macOS", note: "Intel" },
  { id: "linux", suffix: "-x86_64.AppImage", label: "Linux", note: "AppImage" },
];

function guessPlatform() {
  const ua = navigator.userAgent;
  if (/Windows/i.test(ua)) return "windows";
  if (/Mac OS X|Macintosh/i.test(ua)) return "mac-arm";   // most Macs sold since 2020
  if (/Linux|X11/i.test(ua) && !/Android/i.test(ua)) return "linux";
  return null;
}

async function fillDownloads() {
  const box = document.getElementById("downloads");
  if (!box) return;
  const note = document.getElementById("release-note");
  try {
    const r = await fetch(`https://api.github.com/repos/${REPO}/releases/latest`);
    if (!r.ok) throw new Error(r.status);
    const rel = await r.json();
    const mine = guessPlatform();
    box.innerHTML = "";
    for (const p of PLATFORMS) {
      const asset = rel.assets.find((a) => a.name.endsWith(p.suffix));
      if (!asset) continue;
      const a = document.createElement("a");
      a.className = "btn" + (p.id === mine ? " primary mine" : "");
      a.href = asset.browser_download_url;
      a.innerHTML = `⬇ ${p.label} <small>${p.note} · ${Math.round(asset.size / 1048576)} MB</small>`;
      if (p.id === mine) box.prepend(a); else box.append(a);
    }
    if (note) note.innerHTML = `Version ${rel.tag_name.replace(/^v/, "")} · <a href="${rel.html_url}">release notes</a> · free and open source`;
  } catch {
    if (note) note.innerHTML = `Couldn't load the latest version. <a href="https://github.com/${REPO}/releases/latest">Download from GitHub</a>.`;
  }
}

async function socialStatus() {
  const el = document.getElementById("social-status");
  if (!el) return;
  const dot = el.querySelector(".dot");
  const text = el.querySelector(".status-text");
  try {
    const r = await fetch("https://jace-social.vercel.app/api/v1/health", { cache: "no-store" });
    const d = await r.json();
    if (!r.ok || !d.ok) throw new Error();
    dot.className = "dot up";
    text.innerHTML = `<b>Jace Social is online</b><br><span style="color:var(--muted)">${d.players.toLocaleString()} player${d.players === 1 ? "" : "s"} signed up</span>`;
  } catch {
    dot.className = "dot down";
    text.innerHTML = `<b>Jace Social isn't responding right now</b><br><span style="color:var(--muted)">Friends and chat may be unavailable for a moment.</span>`;
  }
}

fillDownloads();
socialStatus();
