"""Paths and persistent settings."""
import json
import os
import sys
import threading
from pathlib import Path


def _default_data_dir() -> Path:
    override = os.environ.get("JACE_LAUNCHER_HOME")
    if override:
        return Path(override)
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home())) / ".jacelauncher"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "JaceLauncher"
    return Path.home() / ".jacelauncher"


DATA_DIR = _default_data_dir()
# Shared Minecraft root: versions, libraries, assets and Java runtimes live here
# so every instance can reuse them.
GAME_ROOT = DATA_DIR / "game"
INSTANCES_DIR = DATA_DIR / "instances"
SKINS_DIR = DATA_DIR / "skins"
CACHE_DIR = DATA_DIR / "cache"
SETTINGS_FILE = DATA_DIR / "settings.json"
ACCOUNTS_FILE = DATA_DIR / "accounts.json"

for _d in (DATA_DIR, GAME_ROOT, INSTANCES_DIR, SKINS_DIR, CACHE_DIR):
    _d.mkdir(parents=True, exist_ok=True)


DEFAULT_SETTINGS = {
    "memory_mb": 4096,
    "min_memory_mb": 512,
    "java_path": "",          # empty = use Mojang's bundled runtime for the version
    "jvm_args": "",
    "window_width": 854,
    "window_height": 480,
    "close_on_launch": False,
    "show_snapshots": False,
    "show_old_versions": False,
    "curseforge_api_key": "",
    "azure_client_id": "",    # optional: your own Azure app for Microsoft login
}


def read_json(path: Path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


class Settings:
    _lock = threading.Lock()

    def __init__(self):
        self.data = dict(DEFAULT_SETTINGS)
        self.data.update(read_json(SETTINGS_FILE, {}))

    def get(self, key):
        return self.data.get(key, DEFAULT_SETTINGS.get(key))

    def set(self, key, value):
        with self._lock:
            self.data[key] = value
            write_json(SETTINGS_FILE, self.data)

    def update(self, values: dict):
        with self._lock:
            self.data.update(values)
            write_json(SETTINGS_FILE, self.data)


settings = Settings()
