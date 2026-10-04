"""Folder-sync checks (run in CI on every platform; Windows uses junctions)."""
import os
import sys
import tempfile
from pathlib import Path

os.environ["JACE_LAUNCHER_HOME"] = tempfile.mkdtemp()
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jace import sync  # noqa: E402
from jace.instances import create_instance, list_instances  # noqa: E402

a = create_instance("A", "1.21.1")
b = create_instance("B", "1.21.1")
assert sync.is_synced(a, "resourcepacks"), "defaults not applied"
(a.game_dir / "resourcepacks" / "pack.zip").write_text("x")
assert (b.game_dir / "resourcepacks" / "pack.zip").exists(), "not shared between instances"
for inst in (a, b):
    w = inst.game_dir / "saves" / "World"
    w.mkdir(parents=True)
    (w / "level.dat").write_text(inst.name)
sync.enable(a, "saves")
sync.enable(b, "saves")
assert sorted(os.listdir(sync.shared_root() / "saves")) == ["World", "World (B)"], "clash handling"
assert sync.disable(b, "saves") == 2 and not sync.is_synced(b, "saves"), "disable should keep a copy"
sync.move_shared_root(Path(tempfile.mkdtemp()) / "Cloud", list_instances(), lambda s: None)
assert (b.game_dir / "resourcepacks" / "pack.zip").exists(), "links broken after moving shared root"
a.delete()
assert (sync.shared_root() / "saves" / "World" / "level.dat").exists(), "deleting an instance removed shared files"
print("SYNC OK")
