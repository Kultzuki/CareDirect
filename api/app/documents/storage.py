"""Private file storage. Files live outside every web-served directory.

Keys look like `cases/<case uuid>/<uuid4 hex>`: no original file name and no extension, so a
key reveals nothing about the document and cannot be mistaken for a URL. There is no
download endpoint in this slice.
"""

from __future__ import annotations

import os
import re
import uuid
from pathlib import Path

from app.config import REPO_ROOT, get_settings

_KEY_RE = re.compile(r"^cases/[0-9a-f-]{36}/[0-9a-f]{32}$")
_PUBLIC_PARTS = frozenset({"public", "static"})


class PrivateStorage:
    def __init__(self, root: Path) -> None:
        root = Path(root).resolve()
        web_dir = (REPO_ROOT / "web").resolve()
        if root == web_dir or web_dir in root.parents:
            raise RuntimeError("storage root must not be inside the web app directory")
        if any(part.lower() in _PUBLIC_PARTS for part in root.parts):
            raise RuntimeError("storage root must not be in a public or static directory")
        root.mkdir(parents=True, exist_ok=True)
        self.root = root

    def new_key(self, case_id: uuid.UUID) -> str:
        return f"cases/{case_id}/{uuid.uuid4().hex}"

    def _path(self, key: str) -> Path:
        if not _KEY_RE.fullmatch(key):
            raise ValueError("invalid storage key")
        path = (self.root / key).resolve()
        if self.root not in path.parents:
            raise ValueError("invalid storage key")
        return path

    def put(self, key: str, content: bytes) -> None:
        path = self._path(key)
        if path.exists():
            raise FileExistsError("a file already exists for this storage key")
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write beside the target, then rename: a reader never sees a half-written file.
        temp = path.parent / f".{uuid.uuid4().hex}.tmp"
        try:
            temp.write_bytes(content)
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def discard(self, key: str) -> None:
        """Remove a stored file. Use only to clean up after a failed database write."""
        self._path(key).unlink(missing_ok=True)


def get_storage() -> PrivateStorage:
    """FastAPI dependency. Tests override it with a temporary directory."""
    settings = get_settings()
    if settings.storage_backend != "local":
        raise RuntimeError(f"storage backend '{settings.storage_backend}' is not implemented")
    return PrivateStorage(settings.storage_path)
