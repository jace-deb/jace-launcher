"""Synced folders: share worlds, resource packs, shaders, screenshots and schematics
between instances.

A synced folder in an instance is a link to  <shared root>/<folder>  (a symlink on
Linux/macOS, a junction on Windows - no admin rights needed). The shared root can be
moved anywhere, e.g. into Dropbox / OneDrive / Google Drive to sync between computers.
"""
import os
import shutil
import sys
from pathlib import Path

from jace.config import DATA_DIR, settings

FOLDERS = {
    "saves": "Worlds",
    "resourcepacks": "Resource packs",
    "shaderpacks": "Shaders",
    "screenshots": "Screenshots",
    "schematics": "Schematics (Litematica)",
}
DEFAULT_SYNCED = ["resourcepacks", "shaderpacks", "screenshots"]


def shared_root() -> Path:
    custom = (settings.get("sync_dir") or "").strip()
    root = Path(custom).expanduser() if custom else DATA_DIR / "shared"
    root.mkdir(parents=True, exist_ok=True)
    return root


def default_folders() -> list[str]:
    value = settings.get("sync_defaults")
    return DEFAULT_SYNCED if value is None else list(value)


def _is_link(p: Path) -> bool:
    return p.is_symlink() or (hasattr(os.path, "isjunction") and os.path.isjunction(p))


def _make_link(link: Path, target: Path):
    if sys.platform == "win32":
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
    else:
        os.symlink(target, link, target_is_directory=True)


def _remove_link(link: Path):
    if sys.platform == "win32" and not link.is_symlink():
        os.rmdir(link)          # removes the junction itself, never what it points to
    else:
        link.unlink()


def is_synced(inst, folder: str) -> bool:
    return _is_link(inst.game_dir / folder)


def status(inst) -> dict[str, bool]:
    return {f: is_synced(inst, f) for f in FOLDERS}


def _free_name(dest_dir: Path, item: Path, tag: str) -> Path:
    """dest_dir/<item name>, or 'name (tag)', 'name (tag 2)'... if that's taken."""
    stem, suffix = (item.stem, item.suffix) if item.is_file() else (item.name, "")
    target, n = dest_dir / item.name, 1
    while target.exists() or target.is_symlink():
        target = dest_dir / f"{stem} ({tag}{'' if n == 1 else f' {n}'}){suffix}"
        n += 1
    return target


def enable(inst, folder: str) -> int:
    """Start syncing a folder. Its current files move into the shared folder (renamed
    if the name is taken). Returns how many items were moved."""
    local = inst.game_dir / folder
    shared = shared_root() / folder
    shared.mkdir(parents=True, exist_ok=True)
    if _is_link(local):
        if Path(os.path.realpath(local)) == shared.resolve():
            return 0
        _remove_link(local)
    moved = 0
    if local.is_dir():
        for item in list(local.iterdir()):
            shutil.move(str(item), str(_free_name(shared, item, inst.name)))
            moved += 1
        local.rmdir()
    local.parent.mkdir(parents=True, exist_ok=True)
    _make_link(local, shared)
    return moved


def disable(inst, folder: str) -> int:
    """Stop syncing. The instance keeps its own copy of what's in the shared folder."""
    local = inst.game_dir / folder
    if not _is_link(local):
        return 0
    shared = Path(os.path.realpath(local))
    _remove_link(local)
    local.mkdir(parents=True, exist_ok=True)
    count = 0
    if shared.is_dir():
        for item in shared.iterdir():
            dest = local / item.name
            if item.is_dir():
                shutil.copytree(item, dest, symlinks=True)
            else:
                shutil.copy2(item, dest)
            count += 1
    return count


def unlink_all(inst):
    """Remove the links (not the shared files) - used before deleting an instance."""
    for f in FOLDERS:
        local = inst.game_dir / f
        if _is_link(local):
            _remove_link(local)


def apply_defaults(inst):
    for f in default_folders():
        enable(inst, f)


def move_shared_root(new_root: Path, instances, status=print):
    """Move all shared files to a new location (e.g. a Dropbox folder) and relink."""
    new_root = Path(new_root).expanduser()
    old_root = shared_root()
    if new_root.resolve() == old_root.resolve():
        return
    new_root.mkdir(parents=True, exist_ok=True)
    linked = [(inst, f) for inst in instances for f in FOLDERS if is_synced(inst, f)]
    for inst, f in linked:
        _remove_link(inst.game_dir / f)
    for f in FOLDERS:
        src = old_root / f
        if not src.is_dir():
            continue
        status(f"Moving {FOLDERS[f].lower()}…")
        dest = new_root / f
        dest.mkdir(parents=True, exist_ok=True)
        for item in list(src.iterdir()):
            shutil.move(str(item), str(_free_name(dest, item, "moved")))
        src.rmdir()
    settings.set("sync_dir", str(new_root))
    for inst, f in linked:
        (new_root / f).mkdir(parents=True, exist_ok=True)
        _make_link(inst.game_dir / f, new_root / f)
    status("Done")
