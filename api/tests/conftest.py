"""Test fixtures. Database tests run against the separate `caredirect_test` database.

Each DB test runs inside an outer transaction that is rolled back afterwards
(SQLAlchemy `join_transaction_mode="create_savepoint"`), so service-level
commits become savepoints and the append-only triggers stay fully active.
"""

from __future__ import annotations

import os

from app.config import Settings

# Point the app at the test database before any app module creates its engine.
os.environ["DATABASE_URL"] = Settings().test_database_url
# Local developer keys must never turn regression tests into live provider calls.
# Tests which exercise a configured provider pass synthetic keys and mock its transport.
os.environ["DEEPSEEK_API_KEY"] = " "
os.environ["GEMINI_API_KEY"] = " "

from collections.abc import Iterator  # noqa: E402

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app import services as svc  # noqa: E402
from app.config import REPO_ROOT  # noqa: E402
from app.db import get_db  # noqa: E402
from app.documents.storage import PrivateStorage, get_storage  # noqa: E402
from app.extraction.adapter import MockExtractionAdapter, get_extraction_adapter  # noqa: E402
from app.main import app  # noqa: E402
from app.states import UserRole  # noqa: E402

TEST_URL = os.environ["DATABASE_URL"]


@pytest.fixture(scope="session")
def engine():
    assert TEST_URL.endswith("/caredirect_test"), "refusing to run tests on a non-test database"
    cfg = Config(str(REPO_ROOT / "api" / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "api" / "alembic"))
    cfg.attributes["database_url"] = TEST_URL
    # Reset only the dedicated test schema. Financial migration downgrade correctly
    # refuses to erase persisted adjustments, so it is not a test-data reset tool.
    reset = create_engine(TEST_URL)
    with reset.begin() as connection:
        connection.exec_driver_sql("DROP SCHEMA public CASCADE")
        connection.exec_driver_sql("CREATE SCHEMA public")
    reset.dispose()
    command.upgrade(cfg, "head")
    eng = create_engine(TEST_URL)
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine) -> Iterator[Session]:
    conn = engine.connect()
    outer = conn.begin()
    session = Session(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)
    try:
        yield session
    finally:
        session.close()
        outer.rollback()
        conn.close()


@pytest.fixture
def storage(tmp_path) -> PrivateStorage:
    return PrivateStorage(tmp_path / "storage")


@pytest.fixture
def client(db: Session, storage: PrivateStorage) -> Iterator[TestClient]:
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[get_extraction_adapter] = MockExtractionAdapter
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def payer(db: Session):
    return svc.create_user(db, "Test Payer", UserRole.PAYER, email="payer@test.invalid")


@pytest.fixture
def other_payer(db: Session):
    return svc.create_user(db, "Other Payer", UserRole.PAYER, email="other@test.invalid")


@pytest.fixture
def actor(payer) -> svc.Actor:
    return svc.Actor(user=payer, label="PAYER:Test Payer")


@pytest.fixture
def headers(payer) -> dict[str, str]:
    return {"X-Demo-User-Id": str(payer.id)}
