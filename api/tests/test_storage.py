import uuid
from pathlib import Path

import pytest

from app.config import REPO_ROOT, Settings
from app.documents.storage import PrivateStorage, get_storage


@pytest.fixture
def store(tmp_path):
    return PrivateStorage(tmp_path / "storage")


def test_put_get_round_trip(store):
    key = store.new_key(uuid.uuid4())
    store.put(key, b"synthetic bytes")
    assert store.get(key) == b"synthetic bytes"
    assert (store.root / key).read_bytes() == b"synthetic bytes"


def test_keys_carry_no_filename_or_extension(store):
    case_id = uuid.uuid4()
    key = store.new_key(case_id)
    assert key.startswith(f"cases/{case_id}/")
    assert "." not in key
    assert len(key.rsplit("/", 1)[1]) == 32
    assert store.new_key(case_id) != key


@pytest.mark.parametrize(
    "key",
    [
        "../x",
        "cases/../../etc/passwd",
        "/etc/passwd",
        "C:/Windows/win.ini",
        "cases/not-a-uuid/abc",
        f"cases/{uuid.uuid4()}/short",
        f"cases/{uuid.uuid4()}/{uuid.uuid4().hex}.pdf",
        f"cases/{uuid.uuid4()}/{uuid.uuid4().hex}/extra",
        f"other/{uuid.uuid4()}/{uuid.uuid4().hex}",
        "",
    ],
)
def test_bad_keys_refused(store, key):
    with pytest.raises(ValueError, match="invalid storage key"):
        store.put(key, b"x")
    with pytest.raises(ValueError, match="invalid storage key"):
        store.get(key)
    with pytest.raises(ValueError, match="invalid storage key"):
        store.discard(key)


def test_overwrite_refused(store):
    key = store.new_key(uuid.uuid4())
    store.put(key, b"first")
    with pytest.raises(FileExistsError):
        store.put(key, b"second")
    assert store.get(key) == b"first"


def test_no_temp_file_is_left_behind(store):
    key = store.new_key(uuid.uuid4())
    store.put(key, b"x")
    assert [p.name for p in (store.root / key).parent.iterdir()] == [key.rsplit("/", 1)[1]]


def test_discard_removes_the_file_and_tolerates_a_missing_one(store):
    key = store.new_key(uuid.uuid4())
    store.put(key, b"x")
    store.discard(key)
    store.discard(key)
    assert not (store.root / key).exists()


def test_root_inside_the_web_app_refused():
    with pytest.raises(RuntimeError, match="web app"):
        PrivateStorage(REPO_ROOT / "web" / "public" / "uploads")
    with pytest.raises(RuntimeError, match="web app"):
        PrivateStorage(REPO_ROOT / "web" / "storage")


@pytest.mark.parametrize("part", ["public", "Static"])
def test_root_with_a_public_or_static_part_refused(tmp_path, part):
    with pytest.raises(RuntimeError, match="public or static"):
        PrivateStorage(tmp_path / part / "files")


def test_default_storage_root_is_private_and_outside_web():
    root = Settings().storage_path
    assert root == REPO_ROOT / "storage"
    assert (REPO_ROOT / "web").resolve() not in root.parents


def test_absolute_storage_dir_is_used_as_is(tmp_path):
    assert Settings(storage_dir=str(tmp_path)).storage_path == Path(tmp_path)


def test_unknown_backend_refused(monkeypatch):
    monkeypatch.setattr(
        "app.documents.storage.get_settings", lambda: Settings(storage_backend="s3")
    )
    with pytest.raises(RuntimeError, match="not implemented"):
        get_storage()
