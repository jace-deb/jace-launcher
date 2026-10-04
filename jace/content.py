"""Modrinth and CurseForge clients, content installs and modpack installs.

Both sources are normalised into the same dict shapes so the UI doesn't care
where a project came from:

project: {source, id, title, description, author, downloads, icon_url, url, project_type}
version: {source, id, project_id, name, version_number, game_versions, loaders, date,
          file: {url, filename, sha1} | None, deps: [project_id, ...]}
"""
import json
import tempfile
import zipfile
from pathlib import Path

from jace.config import settings
from jace.instances import Instance, create_instance
from jace.loaders import CURSEFORGE_LOADER, MODRINTH_LOADER
from jace.net import download, file_sha1, get_json, safe_join, session

PROJECT_TYPES = {"mod": "Mods", "modpack": "Modpacks", "resourcepack": "Resource Packs", "shader": "Shaders"}


class ContentError(Exception):
    pass


# =============================================================================
# Modrinth  (https://docs.modrinth.com/api)
# =============================================================================
class Modrinth:
    name = "Modrinth"
    API = "https://api.modrinth.com/v2"
    SORTS = {"Relevance": "relevance", "Downloads": "downloads", "Followers": "follows",
             "Newest": "newest", "Updated": "updated"}

    def available(self):
        return True

    def search(self, query, project_type, game_version=None, loader=None, sort="Relevance", offset=0, limit=20):
        facets = [[f"project_type:{project_type}"]]
        if game_version:
            facets.append([f"versions:{game_version}"])
        if loader and project_type in ("mod", "modpack") and loader in MODRINTH_LOADER:
            facets.append([f"categories:{MODRINTH_LOADER[loader]}"])
        data = get_json(f"{self.API}/search", params={
            "query": query, "facets": json.dumps(facets), "index": self.SORTS.get(sort, "relevance"),
            "offset": offset, "limit": limit})
        return [{
            "source": "modrinth", "id": h["project_id"], "title": h["title"],
            "description": h.get("description", ""), "author": h.get("author", ""),
            "downloads": h.get("downloads", 0), "icon_url": h.get("icon_url") or "",
            "url": f"https://modrinth.com/{h['project_type']}/{h['slug']}",
            "project_type": h["project_type"],
        } for h in data["hits"]], data.get("total_hits", 0)

    def versions(self, project_id, game_version=None, loader=None, project_type="mod"):
        params = {}
        if game_version:
            params["game_versions"] = json.dumps([game_version])
        if loader and project_type == "mod" and loader in MODRINTH_LOADER:
            params["loaders"] = json.dumps([MODRINTH_LOADER[loader]])
        data = get_json(f"{self.API}/project/{project_id}/version", params=params)
        return [self._version(v) for v in data]

    def _version(self, v):
        files = v.get("files", [])
        f = next((x for x in files if x.get("primary")), files[0] if files else None)
        return {
            "source": "modrinth", "id": v["id"], "project_id": v["project_id"], "name": v["name"],
            "version_number": v["version_number"], "game_versions": v.get("game_versions", []),
            "loaders": v.get("loaders", []), "date": v.get("date_published", "")[:10],
            "file": f and {"url": f["url"], "filename": f["filename"], "sha1": f["hashes"].get("sha1")},
            "deps": [d for d in v.get("dependencies", []) if d.get("dependency_type") == "required"],
        }

    def resolve_dep(self, dep, game_version, loader):
        if dep.get("version_id"):
            return self._version(get_json(f"{self.API}/version/{dep['version_id']}"))
        if dep.get("project_id"):
            vs = self.versions(dep["project_id"], game_version, loader)
            return vs[0] if vs else None
        return None


# =============================================================================
# CurseForge  (https://docs.curseforge.com/rest-api) - needs an API key
# =============================================================================
class CurseForge:
    name = "CurseForge"
    API = "https://api.curseforge.com/v1"
    GAME_ID = 432
    CLASS_IDS = {"mod": 6, "modpack": 4471, "resourcepack": 12, "shader": 6552}
    CLASS_TO_KIND = {v: k for k, v in CLASS_IDS.items()}
    SORTS = {"Relevance": 1, "Downloads": 6, "Followers": 2, "Newest": 11, "Updated": 3}
    LOADER_NAMES = {1: "forge", 4: "fabric", 5: "quilt", 6: "neoforge"}

    def available(self):
        return bool(self._key())

    def _key(self):
        return (settings.get("curseforge_api_key") or "").strip()

    def _get_body(self, path, **params):
        if not self._key():
            raise ContentError("Add a CurseForge API key in Settings to use CurseForge.")
        r = session.get(f"{self.API}{path}", params=params, headers={"x-api-key": self._key()}, timeout=30)
        if r.status_code == 403:
            raise ContentError("CurseForge rejected the API key (403). Check it in Settings.")
        r.raise_for_status()
        return r.json()

    def _get(self, path, **params):
        return self._get_body(path, **params)["data"]

    def _post(self, path, body):
        r = session.post(f"{self.API}{path}", json=body, headers={"x-api-key": self._key()}, timeout=30)
        r.raise_for_status()
        return r.json()["data"]

    def search(self, query, project_type, game_version=None, loader=None, sort="Relevance", offset=0, limit=20):
        params = {"gameId": self.GAME_ID, "classId": self.CLASS_IDS[project_type], "searchFilter": query,
                  "sortField": self.SORTS.get(sort, 1), "sortOrder": "desc", "index": offset, "pageSize": limit}
        if game_version:
            params["gameVersion"] = game_version
        if loader and project_type in ("mod", "modpack") and loader in CURSEFORGE_LOADER:
            params["modLoaderType"] = CURSEFORGE_LOADER[loader]
        body = self._get_body("/mods/search", **params)
        return [{
            "source": "curseforge", "id": m["id"], "title": m["name"], "description": m.get("summary", ""),
            "author": ", ".join(a["name"] for a in m.get("authors", [])[:2]),
            "downloads": int(m.get("downloadCount", 0)), "icon_url": (m.get("logo") or {}).get("thumbnailUrl", ""),
            "url": (m.get("links") or {}).get("websiteUrl", ""), "project_type": project_type,
        } for m in body["data"]], body.get("pagination", {}).get("totalCount", 0)

    def versions(self, project_id, game_version=None, loader=None, project_type="mod"):
        params = {"pageSize": 50}
        if game_version:
            params["gameVersion"] = game_version
        if loader and project_type == "mod" and loader in CURSEFORGE_LOADER:
            params["modLoaderType"] = CURSEFORGE_LOADER[loader]
        return [self._version(f) for f in self._get(f"/mods/{project_id}/files", **params)]

    def _version(self, f):
        sha1 = next((h["value"] for h in f.get("hashes", []) if h.get("algo") == 1), None)
        gv = [g for g in f.get("gameVersions", []) if g[:1].isdigit()]
        loaders = [g.lower() for g in f.get("gameVersions", []) if g.lower() in ("forge", "fabric", "quilt", "neoforge")]
        return {
            "source": "curseforge", "id": f["id"], "project_id": f["modId"], "name": f["displayName"],
            "version_number": f["fileName"], "game_versions": gv, "loaders": loaders,
            "date": f.get("fileDate", "")[:10],
            # downloadUrl is None when the author disabled third-party downloads; we respect that.
            "file": {"url": f["downloadUrl"], "filename": f["fileName"], "sha1": sha1} if f.get("downloadUrl") else None,
            "deps": [{"project_id": d["modId"]} for d in f.get("dependencies", []) if d.get("relationType") == 3],
        }

    def resolve_dep(self, dep, game_version, loader):
        vs = self.versions(dep["project_id"], game_version, loader)
        return vs[0] if vs else None


SOURCES = {"modrinth": Modrinth(), "curseforge": CurseForge()}


# =============================================================================
# Installing content into an instance
# =============================================================================
def install_version(inst: Instance, version: dict, kind: str, with_deps=True, status=None, _seen=None) -> list[str]:
    """Download a project version into the instance; returns installed file names.

    Installed files are recorded in instance.json so a project is never present
    twice (updating replaces the old file, and existing dependencies are skipped)."""
    status = status or (lambda s: None)
    _seen = _seen if _seen is not None else set()
    pid = str(version["project_id"])
    if pid in _seen:
        return []
    _seen.add(pid)
    f = version["file"]
    if not f:
        raise ContentError(f"'{version['name']}' can't be downloaded by launchers (the author disabled it). "
                           "Download it from the website and drop it into the instance folder.")
    folder = inst.content_dir(kind)
    records = inst.data.setdefault("content", {})
    # remove an older version of the same project
    for fname, rec in list(records.items()):
        if str(rec.get("project_id")) == pid and fname != f["filename"]:
            for candidate in (folder / fname, folder / (fname + ".disabled")):
                candidate.unlink(missing_ok=True)
            del records[fname]
    status(f"Downloading {f['filename']}")
    download(f["url"], safe_join(folder, f["filename"]), sha1=f["sha1"])
    records[f["filename"]] = {"source": version["source"], "project_id": pid, "version_id": str(version["id"]),
                              "kind": kind}
    inst.save()
    installed = [f["filename"]]
    if with_deps and kind == "mod":
        src = SOURCES[version["source"]]
        if len(_seen) == 1:
            identify_mods(inst)      # also count mods that were added by hand as installed
        for dep in version["deps"]:
            dep_pid = str(dep.get("project_id") or "")
            if dep_pid and _has_project(inst, dep_pid):
                continue
            try:
                # prefer the newest compatible build over the exact pinned version
                dv = src.resolve_dep({"project_id": dep_pid} if dep_pid else dep, inst.mc_version, inst.loader)
            except Exception:
                dv = None
            if dv and dv["file"] and not _has_project(inst, str(dv["project_id"])):
                installed += install_version(inst, dv, kind, True, status, _seen)
    return installed


def _has_project(inst: Instance, pid: str) -> bool:
    folder = inst.content_dir("mod")
    return any(str(r.get("project_id")) == pid and ((folder / n).exists() or (folder / (n + ".disabled")).exists())
               for n, r in inst.data.get("content", {}).items())


# -- Mod updates and dependencies ----------------------------------------------------

def _mod_files(inst: Instance) -> dict[str, Path]:
    """Installed mod jars by name (a disabled mod is listed under its normal name)."""
    out = {}
    for p in inst.content_dir("mod").iterdir():
        if p.is_file() and (p.name.endswith(".jar") or p.name.endswith(".jar.disabled")):
            out[p.name.removesuffix(".disabled")] = p
    return out


def identify_mods(inst: Instance) -> dict[str, dict]:
    """Work out which project every mod jar belongs to. Modrinth can identify a jar
    from its hash, so this also covers mods that were added by hand; launcher
    records cover CurseForge installs. Newly identified jars are recorded."""
    files = _mod_files(inst)
    sha = {name: file_sha1(path) for name, path in files.items()}
    info = {name: {"path": files[name], "sha1": h, "source": None, "project_id": None, "version": None}
            for name, h in sha.items()}
    if sha:
        r = session.post(f"{Modrinth.API}/version_files", json={"hashes": list(sha.values()), "algorithm": "sha1"},
                         timeout=30)
        if r.ok:
            by_hash = {h: n for n, h in sha.items()}
            for h, v in r.json().items():
                name = by_hash.get(h)
                if name:
                    info[name].update(source="modrinth", project_id=v["project_id"], version_id=v["id"],
                                      version=SOURCES["modrinth"]._version(v))
    records = inst.data.setdefault("content", {})
    for name, i in info.items():
        rec = records.get(name)
        if i["source"] is None and rec and rec.get("kind", "mod") == "mod":
            i.update(source=rec["source"], project_id=str(rec["project_id"]), version_id=str(rec.get("version_id")))
        elif i["source"] == "modrinth" and (not rec or str(rec.get("project_id")) != i["project_id"]):
            records[name] = {"source": "modrinth", "project_id": i["project_id"], "version_id": i["version_id"],
                             "kind": "mod"}
    inst.save()
    return info


def _project_titles(ids: list[str]) -> dict[str, str]:
    if not ids:
        return {}
    try:
        data = get_json(f"{Modrinth.API}/projects", params={"ids": json.dumps(ids)})
        return {p["id"]: p["title"] for p in data}
    except Exception:  # noqa: BLE001 - titles are only cosmetic
        return {}


def check_mod_updates(inst: Instance, info: dict | None = None) -> list[dict]:
    """Mods with a newer compatible version: [{filename, title, current, latest}]."""
    info = info if info is not None else identify_mods(inst)
    updates = []
    mr = {i["sha1"]: n for n, i in info.items() if i["source"] == "modrinth"}
    if mr:
        body = {"hashes": list(mr), "algorithm": "sha1", "game_versions": [inst.mc_version]}
        if inst.loader in MODRINTH_LOADER:
            body["loaders"] = [MODRINTH_LOADER[inst.loader]]
        r = session.post(f"{Modrinth.API}/version_files/update", json=body, timeout=30)
        if r.ok:
            for h, v in r.json().items():
                name = mr.get(h)
                if name and v["id"] != info[name]["version_id"]:
                    updates.append({"filename": name, "project_id": v["project_id"],
                                    "current": info[name]["version"]["version_number"],
                                    "latest": SOURCES["modrinth"]._version(v)})
    cf = SOURCES["curseforge"]
    if cf.available():
        for name, i in info.items():
            if i["source"] != "curseforge":
                continue
            try:
                vs = cf.versions(i["project_id"], inst.mc_version, inst.loader)
            except Exception:  # noqa: BLE001
                continue
            if vs and str(vs[0]["id"]) != str(i.get("version_id")):
                updates.append({"filename": name, "project_id": i["project_id"], "current": name,
                                "latest": vs[0]})
    titles = _project_titles([u["project_id"] for u in updates if u["latest"]["source"] == "modrinth"])
    for u in updates:
        u["title"] = titles.get(u["project_id"]) or u["latest"]["name"]
    return updates


def missing_dependencies(inst: Instance, info: dict | None = None) -> list[dict]:
    """Required dependencies of installed mods that aren't installed:
    [{project_id, title, version, needed_by}]."""
    info = info if info is not None else identify_mods(inst)
    installed = {str(i["project_id"]) for i in info.values() if i["project_id"]}
    needed: dict[str, list[str]] = {}
    for name, i in info.items():
        if i["version"]:
            for dep in i["version"]["deps"]:
                pid = str(dep.get("project_id") or "")
                if pid and pid not in installed:
                    needed.setdefault(pid, []).append(name)
    titles = _project_titles(list(needed))
    out = []
    for pid, by in needed.items():
        try:
            vs = SOURCES["modrinth"].versions(pid, inst.mc_version, inst.loader)
        except Exception:  # noqa: BLE001
            vs = []
        out.append({"project_id": pid, "title": titles.get(pid, pid), "version": vs[0] if vs else None,
                    "needed_by": by})
    return out


def install_missing_dependencies(inst: Instance, status=None) -> list[str]:
    installed = []
    for _ in range(3):                    # dependencies can have dependencies of their own
        missing = [m for m in missing_dependencies(inst) if m["version"] and m["version"]["file"]]
        if not missing:
            break
        for m in missing:
            installed += install_version(inst, m["version"], "mod", True, status)
    return installed


def update_mods(inst: Instance, updates: list[dict], status=None) -> list[str]:
    """Install the newer versions (plus any new dependencies), replacing the old jars."""
    done = []
    files = _mod_files(inst)
    for u in updates:
        old = files.get(u["filename"])
        was_disabled = bool(old and old.name.endswith(".disabled"))
        new_name = u["latest"]["file"]["filename"] if u["latest"]["file"] else None
        if not new_name:
            continue
        done += install_version(inst, u["latest"], "mod", True, status)
        if old and old.exists() and old.name.removesuffix(".disabled") != new_name:
            old.unlink()
            inst.data.get("content", {}).pop(u["filename"], None)
        new_path = inst.content_dir("mod") / new_name
        if was_disabled and new_path.exists():
            new_path.rename(new_path.with_name(new_name + ".disabled"))
    inst.save()
    return done


# -- Modpacks ------------------------------------------------------------------

def _extract_overrides(zf: zipfile.ZipFile, prefixes, target: Path):
    for info in zf.infolist():
        for pre in prefixes:
            if info.filename.startswith(pre + "/") and not info.is_dir():
                rel = info.filename[len(pre) + 1:]
                dest = safe_join(target, rel)
                dest.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, open(dest, "wb") as out:
                    out.write(src.read())


def install_mrpack(path: Path, callback: dict, name: str | None = None) -> Instance:
    """Install a Modrinth .mrpack file as a new instance."""
    set_status = callback.get("setStatus", lambda s: None)
    with zipfile.ZipFile(path) as zf:
        index = json.loads(zf.read("modrinth.index.json"))
        deps = index["dependencies"]
        mc = deps["minecraft"]
        loader, lver = "vanilla", ""
        for key, lid in (("fabric-loader", "fabric"), ("quilt-loader", "quilt"), ("forge", "forge"), ("neoforge", "neoforge")):
            if key in deps:
                loader, lver = lid, deps[key]
        inst = create_instance(name or index.get("name", path.stem), mc, loader, lver,
                               {"modpack": {"source": "modrinth", "version": index.get("versionId", "")}})
        files = [f for f in index.get("files", []) if (f.get("env") or {}).get("client") != "unsupported"]
        callback.get("setMax", lambda n: None)(len(files))
        for i, f in enumerate(files):
            set_status(f"Downloading {Path(f['path']).name} ({i + 1}/{len(files)})")
            download(f["downloads"][0], safe_join(inst.game_dir, f["path"]), sha1=f["hashes"].get("sha1"))
            callback.get("setProgress", lambda n: None)(i + 1)
        set_status("Extracting overrides")
        _extract_overrides(zf, ("overrides", "client-overrides"), inst.game_dir)
    return inst


def install_curseforge_zip(path: Path, callback: dict, name: str | None = None) -> tuple[Instance, list[str]]:
    """Install a CurseForge modpack zip. Returns (instance, files_that_need_manual_download)."""
    cf: CurseForge = SOURCES["curseforge"]
    set_status = callback.get("setStatus", lambda s: None)
    with zipfile.ZipFile(path) as zf:
        manifest = json.loads(zf.read("manifest.json"))
        mc = manifest["minecraft"]["version"]
        loader, lver = "vanilla", ""
        for ml in manifest["minecraft"].get("modLoaders", []):
            if ml.get("primary", True):
                lid, _, ver = ml["id"].partition("-")
                loader, lver = lid, ver
        inst = create_instance(name or manifest.get("name", path.stem), mc, loader, lver,
                               {"modpack": {"source": "curseforge", "version": manifest.get("version", "")}})
        entries = manifest.get("files", [])
        manual = []
        if entries:
            set_status("Resolving mod files")
            file_ids = [e["fileID"] for e in entries]
            files = []
            for i in range(0, len(file_ids), 100):
                files += cf._post("/mods/files", {"fileIds": file_ids[i:i + 100]})
            mods = {}
            mod_ids = list({f["modId"] for f in files})
            for i in range(0, len(mod_ids), 100):
                for m in cf._post("/mods", {"modIds": mod_ids[i:i + 100]}):
                    mods[m["id"]] = m
            callback.get("setMax", lambda n: None)(len(files))
            for i, f in enumerate(files):
                kind = cf.CLASS_TO_KIND.get(mods.get(f["modId"], {}).get("classId"), "mod")
                if not f.get("downloadUrl"):
                    site = (mods.get(f["modId"], {}).get("links") or {}).get("websiteUrl", "")
                    manual.append(f"{f['fileName']}  ->  {site}/files/{f['id']}")
                    continue
                set_status(f"Downloading {f['fileName']} ({i + 1}/{len(files)})")
                download(f["downloadUrl"], safe_join(inst.content_dir(kind), f["fileName"]))
                callback.get("setProgress", lambda n: None)(i + 1)
        set_status("Extracting overrides")
        _extract_overrides(zf, (manifest.get("overrides", "overrides"),), inst.game_dir)
    return inst, manual


def install_modpack_version(version: dict, callback: dict, name: str):
    """Download a modpack version from Modrinth/CurseForge and install it."""
    if not version["file"]:
        raise ContentError("This modpack can't be downloaded by launchers (the author disabled it).")
    tmp = Path(tempfile.mkdtemp()) / version["file"]["filename"]
    callback.get("setStatus", lambda s: None)("Downloading modpack")
    download(version["file"]["url"], tmp, sha1=version["file"]["sha1"])
    return import_modpack_file(tmp, callback, name)


def import_modpack_file(path: Path, callback: dict, name: str | None = None):
    """Install a local .mrpack or CurseForge .zip -> (instance, manual_files)."""
    path = Path(path)
    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
    if "modrinth.index.json" in names:
        inst, manual = install_mrpack(path, callback, name), []
    elif "manifest.json" in names:
        inst, manual = install_curseforge_zip(path, callback, name)
    else:
        raise ContentError("Not a Modrinth (.mrpack) or CurseForge modpack.")
    inst.install(callback)  # install Minecraft + the mod loader
    return inst, manual
