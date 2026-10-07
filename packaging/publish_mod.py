"""Publish every Jace Friends jar to Jace Store (one store version per jar).

    python packaging/publish_mod.py <folder with jars> [--dry-run]

Each jar becomes its own version (e.g. "1.1.0+1.21.1-fabric") tagged with the
Minecraft releases it supports and its loader, so launchers resolve the right one.
Versions already on the store are skipped. Needs Jace Store's dependencies
migration (008) for --depends.
"""
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLI = ROOT / "packaging" / "jace-store.mjs"
SLUG = "jace-friends"
LOADERS = {"fabric": ["fabric", "quilt"], "neoforge": ["neoforge"], "forge": ["forge"]}
# Jace Store lists these on the project page, and Jace Launcher installs them with the mod.
# (e4all is left out where stonecutter.properties.toml has a blank deps.e4all: it doesn't work there)
DEPENDS = {"fabric": ["modrinth:fabric-api"], "neoforge": [], "forge": []}
LOADER_NAMES = {"fabric": "Fabric/Quilt", "neoforge": "NeoForge", "forge": "Forge"}


def releases() -> dict:
    props = tomllib.loads((ROOT / "mod" / "stonecutter.properties.toml").read_text())
    return {k: v["mod"]["mc_releases"] for k, v in props.items() if isinstance(v, dict) and "mod" in v}


def depends(loader: str, mc: str) -> str:
    props = tomllib.loads((ROOT / "mod" / "stonecutter.properties.toml").read_text())
    e4all = props.get(loader, {}).get(mc, {}).get("deps", {}).get("e4all", "")
    return ",".join(DEPENDS[loader] + (["modrinth:e4all"] if e4all else []))


def changelog(version: str) -> str:
    text = (ROOT / "mod" / "CHANGELOG.md").read_text(encoding="utf-8")
    m = re.search(rf"^## {re.escape(version)}\s*\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    return m.group(1).strip() if m else f"Jace Friends {version}"


def published() -> set:
    r = subprocess.run(["node", str(CLI), "project", SLUG, "--json"], capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"Couldn't read the store project: {r.stdout or r.stderr}")
    return {v["version_number"] for v in json.loads(r.stdout).get("versions", [])}


def main():
    folder = Path(sys.argv[1])
    dry = "--dry-run" in sys.argv
    rel = releases()
    have = set() if dry else published()
    jars = sorted(p for p in folder.glob("jacefriends-*.jar") if not p.name.endswith("-sources.jar"))
    if not jars:
        sys.exit("No jars found")
    for jar in jars:
        m = re.fullmatch(r"jacefriends-(fabric|neoforge|forge)-(.+?)\+(.+)\.jar", jar.name)
        if not m:
            print("skipping", jar.name)
            continue
        loader, version, mc = m.groups()
        number = f"{version}+{mc}-{loader}"
        if number in have:
            print(f"{number}: already on Jace Store")
            continue
        games = rel.get(mc, [mc])
        span = games[0] if len(games) == 1 else f"{games[0]}-{games[-1]}"
        cmd = ["node", str(CLI), "publish", SLUG, "--version", number,
               "--name", f"Jace Friends {version} for {LOADER_NAMES[loader]} {span}",
               "--game-versions", ",".join(games), "--loaders", ",".join(LOADERS[loader]),
               "--changelog", changelog(version), "--file", str(jar), "--json"]
        if depends(loader, mc):
            cmd += ["--depends", depends(loader, mc)]
        print(f"{number}: {', '.join(games)} · {', '.join(LOADERS[loader])}", flush=True)
        if dry:
            continue
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit(f"{number}: publish failed: {r.stdout.strip()[-300:] or r.stderr.strip()[-300:]}")


if __name__ == "__main__":
    main()
