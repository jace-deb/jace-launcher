"""Minecraft versions and mod loaders.

Every loader exposes the same small interface:
    game_versions(include_unstable) -> list[str]
    loader_versions(mc_version)      -> list[str]   (newest first)
    install(mc, loader_version, callback) -> version id to launch
"""
import os
import re
import sys

import minecraft_launcher_lib as mll

from jace.config import GAME_ROOT, settings, write_json
from jace.net import download, get_json

ROOT = str(GAME_ROOT)
MOJANG_MANIFEST = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"

_cache: dict = {}


def _cached(key, fn):
    if key not in _cache:
        _cache[key] = fn()
    return _cache[key]


def mojang_versions() -> list[dict]:
    """All Java Edition versions: releases, snapshots, betas and alphas."""
    return _cached("mojang", lambda: get_json(MOJANG_MANIFEST)["versions"])


def _version_key(v: str):
    return tuple(int(p) for p in re.findall(r"\d+", v))


def java_for(version_id: str) -> str:
    """Java executable to use for an installed version (user override first)."""
    custom = (settings.get("java_path") or "").strip()
    if custom:
        return custom
    info = mll.runtime.get_version_runtime_information(version_id, ROOT)
    if info:
        path = mll.runtime.get_executable_path(info["name"], ROOT)
        if path:
            return path
    return mll.utils.get_java_executable()


def install_vanilla(mc: str, callback: dict) -> str:
    mll.install.install_minecraft_version(mc, ROOT, callback=callback)
    return mc


class Vanilla:
    id, name = "vanilla", "Vanilla"
    needs_loader_version = False

    def game_versions(self, include_unstable=True):
        return [v["id"] for v in mojang_versions()]

    def loader_versions(self, mc):
        return []

    def install(self, mc, loader_version, callback):
        return install_vanilla(mc, callback)


class FabricLike:
    """Fabric, Quilt and Legacy Fabric share the same meta-server design, so we
    write the loader's profile JSON straight into versions/ and let the normal
    installer fetch libraries. No Java-based installer needed."""
    needs_loader_version = True

    def __init__(self, id, name, meta):
        self.id, self.name, self.meta = id, name, meta

    def game_versions(self, include_unstable=True):
        data = _cached(f"{self.id}-games", lambda: get_json(f"{self.meta}/versions/game"))
        return [v["version"] for v in data if include_unstable or v.get("stable", True)]

    def loader_versions(self, mc):
        data = _cached(f"{self.id}-loader-{mc}", lambda: get_json(f"{self.meta}/versions/loader/{mc}"))
        versions = sorted((d["loader"]["version"] for d in data), key=_version_key, reverse=True)
        # stable releases first, betas after (sort is stable, so order is kept)
        return sorted(versions, key=lambda v: any(t in v for t in ("beta", "pre", "rc", "alpha")))

    def install(self, mc, loader_version, callback):
        install_vanilla(mc, callback)
        profile = get_json(f"{self.meta}/versions/loader/{mc}/{loader_version}/profile/json")
        vid = profile["id"]
        write_json(GAME_ROOT / "versions" / vid / f"{vid}.json", profile)
        _fetch_maven_natives(profile.get("libraries", []))
        mll.install.install_minecraft_version(vid, ROOT, callback=callback)
        return vid


def _fetch_maven_natives(libraries):
    """Legacy Fabric ships LWJGL natives as plain maven coordinates with a
    `natives` map but no `downloads` block; minecraft-launcher-lib can extract
    them but won't download them, so fetch the native jars up front."""
    os_key = {"win32": "windows", "darwin": "osx"}.get(sys.platform, "linux")
    arch = "64" if sys.maxsize > 2 ** 32 else "32"
    for lib in libraries:
        classifier = (lib.get("natives") or {}).get(os_key)
        if not classifier or "downloads" in lib or "url" not in lib:
            continue
        group, name, version = lib["name"].split(":")[:3]
        classifier = classifier.replace("${arch}", arch)
        rel = f"{group.replace('.', '/')}/{name}/{version}/{name}-{version}-{classifier}.jar"
        dest = GAME_ROOT / "libraries" / rel
        if not dest.is_file():
            download(lib["url"].rstrip("/") + "/" + rel, dest)


class ForgeLike:
    """Forge and NeoForge run their own installer processors, which need Java.
    We install vanilla first so Mojang's matching Java runtime is available."""
    needs_loader_version = True

    def __init__(self, id, name):
        self.id, self.name = id, name
        self._impl = mll.mod_loader.get_mod_loader(id)

    def game_versions(self, include_unstable=True):
        return _cached(f"{self.id}-games", lambda: self._impl.get_minecraft_versions(not include_unstable))

    def loader_versions(self, mc):
        return _cached(f"{self.id}-loader-{mc}", lambda: self._impl.get_loader_versions(mc, False))

    def install(self, mc, loader_version, callback):
        install_vanilla(mc, callback)
        java = java_for(mc)
        callback.get("setStatus", lambda s: None)(f"Running {self.name} installer...")
        self._impl.install(mc, ROOT, callback=callback, java=java, loader_version=loader_version)
        vid = self._impl.get_installed_version(mc, loader_version)
        if not os.path.isfile(GAME_ROOT / "versions" / vid / f"{vid}.json"):
            raise RuntimeError(f"{self.name} installer finished but {vid} was not created")
        mll.install.install_minecraft_version(vid, ROOT, callback=callback)
        return vid


LOADERS = {
    "vanilla": Vanilla(),
    "fabric": FabricLike("fabric", "Fabric", "https://meta.fabricmc.net/v2"),
    "quilt": FabricLike("quilt", "Quilt", "https://meta.quiltmc.org/v3"),
    "forge": ForgeLike("forge", "Forge"),
    "neoforge": ForgeLike("neoforge", "NeoForge"),
    "legacyfabric": FabricLike("legacyfabric", "Legacy Fabric", "https://meta.legacyfabric.net/v2"),
}

# Names used by Modrinth / CurseForge for each loader
MODRINTH_LOADER = {"fabric": "fabric", "quilt": "quilt", "forge": "forge",
                   "neoforge": "neoforge", "legacyfabric": "legacy-fabric"}
CURSEFORGE_LOADER = {"forge": 1, "fabric": 4, "quilt": 5, "neoforge": 6, "legacyfabric": 4}
