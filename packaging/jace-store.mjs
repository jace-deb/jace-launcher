#!/usr/bin/env node
// Jace Store CLI — publish updates from a terminal, CI, or an AI agent.
// Single file, Node.js 18+, no dependencies.
//
//   curl -fsSL https://jace-store-deb.vercel.app/jace-store.mjs -o jace-store.mjs
//   node jace-store.mjs help

import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { basename, dirname, join } from "node:path";

const DEFAULT_SITE = "https://jace-store-deb.vercel.app";
const CONFIG_PATH = join(process.env.XDG_CONFIG_HOME || join(homedir(), ".config"), "jace-store", "config.json");

const HELP = `Jace Store CLI

Auth (pick one):
  jace-store login <token>            Save a token (create one at <site>/dashboard/tokens)
  JACE_STORE_TOKEN=jst_...            Or set it in the environment
  JACE_STORE_URL=https://...          Override the site (default ${DEFAULT_SITE})

Commands:
  whoami                              Show the account the token belongs to
  types                               List project types and their loaders/platforms
  projects                            List your projects
  project <slug>                      Show a project with all versions and files
  create --type <type> --title <t> --summary <s> [--slug s] [--description-file f.md]
         [--categories a,b] [--source-url u] [--issues-url u] [--license MIT]
  update <slug> [--title] [--summary] [--description-file f.md] [--categories a,b]
         [--source-url] [--issues-url] [--license]
  publish <slug> --version <x.y.z> [--name n] [--channel release|beta|alpha]
         [--loaders a,b] [--game-versions 1.21.1,1.21] [--changelog text | --changelog-file f]
         [--file path]... [--link "url|label"]... [--primary-link]
         [--depends modrinth:fabric-api,e4all,modrinth:sodium:optional]
                                      Create a version. Uploaded files come first (the first is
                                      primary) unless --primary-link. Needs at least one file or link.
  add-file <versionId> <path> [--label l] [--primary]
  add-link <versionId> <url> [--label l] [--filename f] [--primary] [--skip-hash]
  edit-version <versionId> [--name] [--version-number] [--changelog | --changelog-file] [--channel]
         [--loaders] [--game-versions] [--depends a,b | --depends none]
  download-mode <slug> latest|all|primary [--version <versionId>]
                                      What the Download button does: newest version, a list of all
                                      versions, or always one primary version
  set-primary <slug> <versionId>      Shortcut for: download-mode <slug> primary --version <id>
  edit-file <fileId> [--label l] [--filename f] [--primary]
  delete-version <versionId>
  delete-file <fileId>

Global flags:
  --json                              Machine-readable output (recommended for AI agents)

Notes:
  - Minecraft projects need --game-versions (and usually --loaders).
  - --depends lists other projects this version needs: "slug" for Jace Store, "modrinth:slug"
    for Modrinth, with an optional ":optional", ":incompatible" or ":embedded" (default required).
    Launchers install required dependencies automatically.
  - Links for Minecraft content must be direct downloads: the server fetches them once to
    compute SHA-1/SHA-512 so launchers can verify them. Other links are hashed when possible.
  - Free Supabase plans cap uploads at 50 MB per file; use --link for bigger files.
`;

// ---------------------------------------------------------------------------
// args

function parseArgs(argv) {
  const pos = [];
  const flags = {};
  const multi = new Set(["file", "link"]);
  const bool = new Set(["json", "primary", "primary-link", "skip-hash", "help"]);
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (!a.startsWith("--")) { pos.push(a); continue; }
    const eq = a.indexOf("=");
    const key = (eq > 0 ? a.slice(2, eq) : a.slice(2));
    let val;
    if (eq > 0) val = a.slice(eq + 1);
    else if (!bool.has(key) && i + 1 < argv.length && !argv[i + 1].startsWith("--")) val = argv[++i];
    else val = true;
    if (multi.has(key)) (flags[key] ??= []).push(val);
    else flags[key] = val;
  }
  return { pos, flags };
}

const list = (v) => (typeof v === "string" ? v.split(",").map((s) => s.trim()).filter(Boolean) : undefined);

// ---------------------------------------------------------------------------
// config + http

async function loadConfig() {
  try { return JSON.parse(await readFile(CONFIG_PATH, "utf8")); } catch { return {}; }
}

async function context() {
  const cfg = await loadConfig();
  const site = (process.env.JACE_STORE_URL || cfg.site || DEFAULT_SITE).replace(/\/$/, "");
  const token = process.env.JACE_STORE_TOKEN || cfg.token;
  return { site, token };
}

class CliError extends Error {}

async function api(ctx, method, path, body) {
  if (!ctx.token) throw new CliError("No token. Run `jace-store login <token>` or set JACE_STORE_TOKEN.");
  const res = await fetch(`${ctx.site}/api/cli${path}`, {
    method,
    headers: { Authorization: `Bearer ${ctx.token}`, ...(body ? { "Content-Type": "application/json" } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  let data;
  try { data = JSON.parse(text); } catch { data = { error: text.slice(0, 300) }; }
  if (!res.ok) throw new CliError(`${method} ${path} failed (${res.status}): ${data.error ?? res.statusText}`);
  return data;
}

async function uploadFile(ctx, versionId, filePath, { label, primary } = {}, log) {
  const bytes = await readFile(filePath);
  const filename = basename(filePath);
  log(`  hashing ${filename} (${fmtBytes(bytes.length)})`);
  const sha1 = createHash("sha1").update(bytes).digest("hex");
  const sha512 = createHash("sha512").update(bytes).digest("hex");
  const { upload_url, path } = await api(ctx, "POST", `/versions/${versionId}/upload-url`, { filename });
  log(`  uploading ${filename}`);
  const put = await fetch(upload_url, {
    method: "PUT",
    headers: { "Content-Type": "application/octet-stream", "x-upsert": "true" },
    body: bytes,
  });
  if (!put.ok) {
    const msg = await put.text().catch(() => "");
    throw new CliError(`Upload of ${filename} failed (${put.status}): ${msg.slice(0, 300)}`);
  }
  return api(ctx, "POST", `/versions/${versionId}/files`, {
    kind: "upload", path, filename, sha1, sha512, size: bytes.length, label, primary,
  });
}

function parseLink(spec) {
  const i = spec.lastIndexOf("|");
  return i > 0 && !spec.slice(i + 1).includes("/") ? { url: spec.slice(0, i), label: spec.slice(i + 1) } : { url: spec };
}

const fmtBytes = (n) => (n == null ? "?" : n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1048576).toFixed(1)} MB`);

async function textFlag(flags, inline, file) {
  if (typeof flags[file] === "string") return readFile(flags[file], "utf8");
  if (typeof flags[inline] === "string") return flags[inline];
  return undefined;
}

// ---------------------------------------------------------------------------
// commands

async function main() {
  const { pos, flags } = parseArgs(process.argv.slice(2));
  const cmd = pos.shift() ?? "help";
  const json = !!flags.json;
  const log = (...a) => { if (!json) console.error(...a); };
  const out = (data, human) => {
    if (json) console.log(JSON.stringify(data, null, 2));
    else console.log(human ? human(data) : JSON.stringify(data, null, 2));
  };
  const need = (v, what) => { if (!v || v === true) throw new CliError(`Missing ${what}. See \`jace-store help\`.`); return v; };
  const ctx = await context();

  switch (cmd) {
    case "help": case "--help": case "-h":
      console.log(HELP.replaceAll("<site>", ctx.site));
      return;

    case "login": {
      const token = need(pos[0], "<token>");
      if (!token.startsWith("jst_")) throw new CliError("Tokens start with jst_. Create one at " + ctx.site + "/dashboard/tokens");
      const me = await api({ ...ctx, token }, "GET", "/me");
      const cfg = await loadConfig();
      await mkdir(dirname(CONFIG_PATH), { recursive: true });
      await writeFile(CONFIG_PATH, JSON.stringify({ ...cfg, token, site: flags.site || cfg.site }, null, 2), { mode: 0o600 });
      out({ ok: true, username: me.username, config: CONFIG_PATH }, (d) => `Logged in as ${d.username}. Token saved to ${d.config}`);
      return;
    }

    case "whoami":
      out(await api(ctx, "GET", "/me"), (d) => `${d.username} (${d.id}) on ${ctx.site}`);
      return;

    case "types": {
      const [types, loaders] = await Promise.all([
        fetch(`${ctx.site}/api/v2/tag/project_type`).then((r) => r.json()),
        fetch(`${ctx.site}/api/v2/tag/loader`).then((r) => r.json()),
      ]);
      const byType = Object.fromEntries(types.map((t) => [t, loaders.filter((l) => l.supported_project_types.includes(t)).map((l) => l.name)]));
      out(byType, (d) => Object.entries(d).map(([t, ls]) => `${t.padEnd(14)} ${ls.join(", ")}`).join("\n"));
      return;
    }

    case "projects":
      out(await api(ctx, "GET", "/projects"), (rows) =>
        rows.length ? rows.map((p) => `${p.slug.padEnd(28)} ${p.type.padEnd(13)} ${String(p.downloads).padStart(7)} dl  ${p.title}`).join("\n") : "No projects yet.");
      return;

    case "project": {
      const p = await api(ctx, "GET", `/projects/${encodeURIComponent(need(pos[0], "<slug>"))}`);
      out(p, (d) => [
        `${d.title} (${d.slug}, ${d.type}) ${d.page_url}`,
        `  download button: ${d.download_mode}${d.download_mode === "primary" ? ` (${d.primary_version_id})` : ""}`,
        ...d.versions.map((v) => [
          `  ${v.version_number}  [${v.release_channel}]  id=${v.id}  ${v.game_versions.join(",")} ${v.loaders.join(",")}`,
          ...v.files.map((f) => `     ${f.external ? "link" : "file"} ${f.primary ? "*" : " "} ${f.label ? f.label + " · " : ""}${f.filename} (${fmtBytes(f.size)}) id=${f.id}`),
        ].join("\n")),
      ].join("\n"));
      return;
    }

    case "create": {
      const body = {
        type: need(flags.type, "--type"),
        title: need(flags.title, "--title"),
        summary: need(flags.summary, "--summary"),
        slug: flags.slug,
        description: await textFlag(flags, "description", "description-file"),
        categories: list(flags.categories),
        source_url: flags["source-url"],
        issues_url: flags["issues-url"],
        license: flags.license,
      };
      out(await api(ctx, "POST", "/projects", body), (d) => `Created ${d.slug}: ${d.page_url}`);
      return;
    }

    case "update": {
      const slug = need(pos[0], "<slug>");
      const body = {};
      for (const [flag, key] of [["title", "title"], ["summary", "summary"], ["source-url", "source_url"], ["issues-url", "issues_url"], ["license", "license"]]) {
        if (typeof flags[flag] === "string") body[key] = flags[flag];
      }
      const desc = await textFlag(flags, "description", "description-file");
      if (desc !== undefined) body.description = desc;
      if (flags.categories) body.categories = list(flags.categories);
      out(await api(ctx, "PATCH", `/projects/${encodeURIComponent(slug)}`, body), (d) => `Updated ${d.slug}`);
      return;
    }

    case "publish": {
      const slug = need(pos[0], "<slug>");
      const files = flags.file ?? [];
      const links = (flags.link ?? []).map(parseLink);
      if (!files.length && !links.length) throw new CliError("publish needs at least one --file or --link");
      for (const f of files) await readFile(f).catch(() => { throw new CliError(`Can't read ${f}`); });

      const primaryLink = !!flags["primary-link"] || !files.length;
      log(`Creating version ${flags.version} of ${slug}…`);
      const version = await api(ctx, "POST", `/projects/${encodeURIComponent(slug)}/versions`, {
        version_number: need(flags.version, "--version"),
        name: flags.name,
        channel: flags.channel,
        loaders: list(flags.loaders),
        game_versions: list(flags["game-versions"]),
        changelog: await textFlag(flags, "changelog", "changelog-file"),
        ...(flags.depends ? { dependencies: list(flags.depends) } : {}),
      });
      const added = [];
      try {
        for (const [i, f] of files.entries()) added.push(await uploadFile(ctx, version.id, f, { primary: !primaryLink && i === 0 }, log));
        for (const [i, l] of links.entries()) {
          log(`  adding link ${l.url}`);
          added.push(await api(ctx, "POST", `/versions/${version.id}/files`, { kind: "link", ...l, primary: primaryLink && i === 0 }));
        }
      } catch (e) {
        log("  failed, rolling back the version");
        await api(ctx, "DELETE", `/versions/${version.id}`).catch(() => {});
        throw e;
      }
      out({ ...version, files: added }, (d) => `Published ${d.version_number} (${added.length} file${added.length === 1 ? "" : "s"}): ${d.page_url}`);
      return;
    }

    case "add-file":
      out(await uploadFile(ctx, need(pos[0], "<versionId>"), need(pos[1], "<path>"), { label: flags.label, primary: !!flags.primary }, log),
        (f) => `Added ${f.filename} (${f.id})`);
      return;

    case "add-link":
      out(await api(ctx, "POST", `/versions/${need(pos[0], "<versionId>")}/files`, {
        kind: "link", url: need(pos[1], "<url>"), label: flags.label, filename: flags.filename,
        primary: !!flags.primary, skip_hash: !!flags["skip-hash"],
      }), (f) => `Added link ${f.label ?? f.filename} (${f.id})${f.sha1 ? "" : " [unverified]"}`);
      return;

    case "edit-version": {
      const id = need(pos[0], "<versionId>");
      const body = {};
      if (typeof flags.name === "string") body.name = flags.name;
      if (typeof flags["version-number"] === "string") body.version_number = flags["version-number"];
      if (typeof flags.channel === "string") body.channel = flags.channel;
      if (flags.loaders) body.loaders = list(flags.loaders);
      if (flags["game-versions"]) body.game_versions = list(flags["game-versions"]);
      if (flags.depends) body.dependencies = flags.depends === "none" ? [] : list(flags.depends);
      const cl = await textFlag(flags, "changelog", "changelog-file");
      if (cl !== undefined) body.changelog = cl;
      out(await api(ctx, "PATCH", `/versions/${id}`, body), (d) => `Updated version ${d.version_number}`);
      return;
    }

    case "download-mode": {
      const slug = need(pos[0], "<slug>");
      const mode = need(pos[1], "latest|all|primary");
      if (!["latest", "all", "primary"].includes(mode)) throw new CliError("mode must be latest, all or primary");
      const body = { download_mode: mode };
      if (mode === "primary") body.primary_version_id = need(flags.version, "--version <versionId>");
      out(await api(ctx, "PATCH", `/projects/${encodeURIComponent(slug)}`, body), (d) => `Download button for ${d.slug}: ${d.download_mode}`);
      return;
    }

    case "set-primary": {
      const slug = need(pos[0], "<slug>");
      const body = { download_mode: "primary", primary_version_id: need(pos[1], "<versionId>") };
      out(await api(ctx, "PATCH", `/projects/${encodeURIComponent(slug)}`, body), (d) => `Primary version of ${d.slug} set`);
      return;
    }

    case "edit-file": {
      const body = {};
      if (typeof flags.label === "string") body.label = flags.label;
      if (typeof flags.filename === "string") body.filename = flags.filename;
      if (flags.primary) body.primary = true;
      out(await api(ctx, "PATCH", `/files/${need(pos[0], "<fileId>")}`, body), (f) => `Updated ${f.label ?? f.filename}`);
      return;
    }

    case "delete-version":
      out(await api(ctx, "DELETE", `/versions/${need(pos[0], "<versionId>")}`), (d) => `Deleted version ${d.deleted}`);
      return;

    case "delete-file":
      out(await api(ctx, "DELETE", `/files/${need(pos[0], "<fileId>")}`), (d) => `Deleted file ${d.deleted}`);
      return;

    default:
      throw new CliError(`Unknown command "${cmd}". Run \`jace-store help\`.`);
  }
}

main().catch((e) => {
  const msg = e instanceof CliError ? e.message : (e?.stack ?? String(e));
  if (process.argv.includes("--json")) console.log(JSON.stringify({ error: msg }));
  console.error(`error: ${msg}`);
  process.exit(1);
});
