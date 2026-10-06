"""Publish a GitHub release to Jace Store as raw download links.

    python packaging/publish_store.py v1.0.9 [v1.0.8 ...] [--dry-run]

Each release file becomes a labelled direct-download link (no re-upload: the
files stay on GitHub). The changelog comes from CHANGELOG.md. Needs Node and a
Jace Store token (JACE_STORE_TOKEN, or `node packaging/jace-store.mjs login`).
"""
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from jace import GITHUB_REPO  # noqa: E402

CLI = ROOT / "packaging" / "jace-store.mjs"
SLUG = "jace-launcher"

# (filename ending, label, platform); first match wins, and this order is the
# order downloads are listed on the store (the first one is the main download)
FILES = [
    ("-windows-x64.exe", "Windows", "windows"),
    ("-windows-x64-setup.exe", "Windows (installer)", "windows"),
    ("-windows-x64-portable.zip", "Windows (portable)", "windows"),
    ("-macos-arm64.app.zip", "macOS (Apple Silicon)", "macos"),
    ("-macos-x86_64.app.zip", "macOS (Intel)", "macos"),
    ("-macos-arm64.dmg", "macOS (Apple Silicon)", "macos"),
    ("-macos-x86_64.dmg", "macOS (Intel)", "macos"),
    ("-x86_64.AppImage", "Linux", "linux"),
]


def release(tag: str) -> dict:
    req = urllib.request.Request(f"https://api.github.com/repos/{GITHUB_REPO}/releases/tags/{tag}",
                                 headers={"Accept": "application/vnd.github+json", "User-Agent": "jace-store-publish"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def changelog(version: str) -> str:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    m = re.search(rf"^## {re.escape(version)}\s*\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    return m.group(1).strip() if m else f"See {release_url(version)}"


def release_url(version: str) -> str:
    return f"https://github.com/{GITHUB_REPO}/releases/tag/v{version}"


def links_for(rel: dict) -> tuple[list[str], list[str]]:
    links, platforms = [], []
    assets = rel.get("assets", [])
    for ending, label, plat in FILES:
        for a in assets:
            if a["name"].endswith(ending) and not any(a["browser_download_url"] in link for link in links):
                links.append(f"{a['browser_download_url']}|{label}")
                if plat not in platforms:
                    platforms.append(plat)
    return links, platforms


def published_versions() -> set[str]:
    res = subprocess.run(["node", str(CLI), "project", SLUG, "--json"], capture_output=True, text=True)
    if res.returncode != 0:
        sys.exit(f"Couldn't read the Jace Store project: {res.stdout.strip() or res.stderr.strip()}")
    return {v["version_number"] for v in json.loads(res.stdout).get("versions", [])}


def publish(tag: str, dry_run=False, existing: set[str] | None = None) -> None:
    version = tag.lstrip("v")
    if existing is not None and version in existing:
        print(f"{tag}: already on Jace Store, skipping")
        return
    links, platforms = links_for(release(tag))
    if not links:
        sys.exit(f"{tag}: no downloadable files in the GitHub release")
    cmd = ["node", str(CLI), "publish", SLUG, "--version", version, "--name", f"Jace Launcher {version}",
           "--loaders", ",".join(platforms), "--changelog", changelog(version), "--json"]
    for link in links:
        cmd += ["--link", link]
    print(f"{tag}: {len(links)} download(s) for {', '.join(platforms)}", flush=True)
    if dry_run:
        print("  " + "\n  ".join(links))
        return
    res = subprocess.run(cmd, capture_output=True, text=True)
    out = json.loads(res.stdout or "{}") if res.stdout.strip().startswith("{") else {}
    if res.returncode != 0:
        sys.exit(f"{tag}: publish failed: {out.get('error') or res.stderr.strip()}")
    print(f"  published: {out.get('page_url', '')}")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        sys.exit(__doc__)
    dry = "--dry-run" in sys.argv
    existing = None if dry else published_versions()
    for t in args:
        publish(t if t.startswith("v") else f"v{t}", dry_run=dry, existing=existing)
