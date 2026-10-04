"""Small HTTP helpers shared by the API clients."""
import hashlib
import os
from pathlib import Path

import requests

from jace import USER_AGENT

session = requests.Session()
session.headers["User-Agent"] = USER_AGENT


def get_json(url, **kwargs):
    r = session.get(url, timeout=30, **kwargs)
    r.raise_for_status()
    return r.json()


def download(url: str, dest: Path, sha1: str | None = None, progress=None) -> Path:
    """Download url to dest (atomically), optionally verifying sha1.

    progress(done_bytes, total_bytes) is called while downloading.
    """
    dest = Path(dest)
    if sha1 and dest.is_file() and file_sha1(dest) == sha1:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    with session.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length") or 0)
        done = 0
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(65536):
                f.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    if sha1 and file_sha1(tmp) != sha1:
        tmp.unlink(missing_ok=True)
        raise IOError(f"Checksum mismatch for {dest.name}")
    os.replace(tmp, dest)
    return dest


def file_sha1(path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_join(root: Path, relative: str) -> Path:
    """Join a path from untrusted data (modpack manifests) and refuse escapes."""
    root = Path(root).resolve()
    target = (root / relative).resolve()
    if root != target and root not in target.parents:
        raise ValueError(f"Refusing to write outside instance folder: {relative}")
    return target
