"""Instances: isolated game folders that share the version/library store."""
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import minecraft_launcher_lib as mll

from jace import APP_NAME, APP_VERSION
from jace.config import GAME_ROOT, INSTANCES_DIR, read_json, settings, write_json
from jace.loaders import LOADERS, java_for

CONTENT_FOLDERS = {"mod": "mods", "resourcepack": "resourcepacks", "shader": "shaderpacks",
                   "datapack": "datapacks"}


class Instance:
    def __init__(self, folder: Path):
        self.folder = Path(folder)
        self.data = read_json(self.folder / "instance.json", {})

    # -- properties --
    @property
    def id(self): return self.folder.name
    @property
    def name(self): return self.data.get("name", self.id)
    @property
    def mc_version(self): return self.data.get("mc_version", "")
    @property
    def loader(self): return self.data.get("loader", "vanilla")
    @property
    def loader_version(self): return self.data.get("loader_version", "")
    @property
    def game_dir(self) -> Path: return self.folder / "minecraft"

    def content_dir(self, kind: str) -> Path:
        d = self.game_dir / CONTENT_FOLDERS.get(kind, "mods")
        d.mkdir(parents=True, exist_ok=True)
        return d

    def describe(self) -> str:
        if self.loader == "vanilla":
            return f"Vanilla {self.mc_version}"
        return f"{LOADERS[self.loader].name} {self.loader_version} · {self.mc_version}"

    def save(self):
        write_json(self.folder / "instance.json", self.data)

    # -- install & launch --
    def install(self, callback: dict, force=False):
        if self.data.get("version_id") and not force:
            # still verify/repair the base version quickly (only downloads missing files)
            mll.install.install_minecraft_version(self.data["version_id"], str(GAME_ROOT), callback=callback)
            return
        loader = LOADERS[self.loader]
        vid = loader.install(self.mc_version, self.loader_version, callback)
        self.data["version_id"] = vid
        self.save()

    def _supports_quick_play(self) -> bool:
        """1.20+ joins servers with --quickPlayMultiplayer; older versions use --server."""
        vid = self.data.get("version_id", "")
        while vid:
            data = read_json(GAME_ROOT / "versions" / vid / f"{vid}.json", {})
            if "quickPlayMultiplayer" in json.dumps(data.get("arguments", {})):
                return True
            vid = data.get("inheritsFrom")
        return False

    def build_command(self, account: dict, server: str | None = None) -> list[str]:
        vid = self.data["version_id"]
        mem = int(self.data.get("memory_mb") or settings.get("memory_mb"))
        jvm = [f"-Xmx{mem}M", f"-Xms{min(int(settings.get('min_memory_mb')), mem)}M"]
        extra = (self.data.get("jvm_args") or settings.get("jvm_args") or "").split()
        java = (self.data.get("java_path") or "").strip() or java_for(vid)
        options = {
            "username": account["username"],
            "uuid": account["uuid"],
            "token": account.get("access_token", "0"),
            "jvmArguments": jvm + extra,
            "launcherName": APP_NAME.replace(" ", ""),
            "launcherVersion": APP_VERSION,
            "gameDirectory": str(self.game_dir),
            "executablePath": java,
            "customResolution": True,
            "resolutionWidth": str(settings.get("window_width")),
            "resolutionHeight": str(settings.get("window_height")),
        }
        if server:
            if self._supports_quick_play():
                options["quickPlayMultiplayer"] = server
            else:
                host, _, port = server.partition(":")
                options["server"] = host
                if port:
                    options["port"] = port
        cmd = mll.command.get_minecraft_command(vid, str(GAME_ROOT), options)
        # placeholders the library leaves alone
        xuid = account.get("xuid") or "0"
        return [a.replace("${auth_xuid}", xuid).replace("${clientid}", "0") for a in cmd]

    def launch(self, account: dict, server: str | None = None) -> subprocess.Popen:
        self.game_dir.mkdir(parents=True, exist_ok=True)
        cmd = self.build_command(account, server)
        self.data["last_played"] = time.time()
        self.save()
        kwargs = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        return subprocess.Popen(cmd, cwd=self.game_dir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, text=True, errors="replace", bufsize=1, **kwargs)

    # -- content --
    def list_content(self, kind: str) -> list[Path]:
        d = self.content_dir(kind)
        return sorted((p for p in d.iterdir() if p.is_file() or kind != "mod"), key=lambda p: p.name.lower())

    def delete(self):
        shutil.rmtree(self.folder)


def list_instances() -> list[Instance]:
    out = [Instance(p) for p in INSTANCES_DIR.iterdir() if (p / "instance.json").is_file()]
    return sorted(out, key=lambda i: -i.data.get("last_played", i.data.get("created", 0)))


def create_instance(name: str, mc_version: str, loader: str = "vanilla", loader_version: str = "",
                    extra: dict | None = None) -> Instance:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._") or "instance"
    folder, n = INSTANCES_DIR / slug, 1
    while folder.exists():
        n += 1
        folder = INSTANCES_DIR / f"{slug}_{n}"
    folder.mkdir(parents=True)
    inst = Instance(folder)
    inst.data = {"name": name, "mc_version": mc_version, "loader": loader,
                 "loader_version": loader_version, "created": time.time(), **(extra or {})}
    inst.save()
    inst.game_dir.mkdir(parents=True, exist_ok=True)
    return inst
