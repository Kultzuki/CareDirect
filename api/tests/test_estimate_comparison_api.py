"""HTTP contract tests with an isolated store; never reset the other agent's test DB."""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api import estimate_comparison as api
from app.api.cases import current_actor
from app.db import get_db
from app.errors import Forbidden
from app.main import app
from tests.test_estimate_comparison import doc, line


@pytest.fixture
def comparison_http(monkeypatch):
    case_id = uuid4()
    documents = [
        SimpleNamespace(
            id=uuid4(),
            case_id=case_id,
            document_type=kind,
            extraction_status="EXTRACTED",
            created_at=datetime.now(UTC),
        )
        for kind in ("ESTIMATE", "BILL")
    ]
    snapshots = [
        doc([line("Room", amount)], amount, document_id=str(d.id))
        for d, amount in zip(documents, ("100.00", "150.00"), strict=True)
    ]
    calls = []
    store = SimpleNamespace(
        scalars=lambda _query: documents, scalar=lambda _query: SimpleNamespace(provider="mock")
    )
    monkeypatch.setattr(api, "_visible_case", lambda db, actor, case: calls.append(case))
    monkeypatch.setattr(api, "_load", lambda db, row: snapshots.pop(0))
    monkeypatch.setattr(api, "snapshot", lambda loaded: loaded)
    old = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = lambda: store
    app.dependency_overrides[current_actor] = lambda: SimpleNamespace()
    try:
        with TestClient(app) as client:
            yield client, case_id, documents, calls, store
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(old)


def test_comparison_endpoint_selects_unique_pair_and_checks_case_access(comparison_http):
    client, case_id, documents, calls, _ = comparison_http
    response = client.get(f"/api/cases/{case_id}/estimate-comparison")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["difference"] == "50.00"
    assert body["estimate_document_id"] == str(documents[0].id)
    assert body["extraction_providers"] == {"ESTIMATE": "mock", "BILL": "mock"}
    assert calls == [case_id]


def test_ambiguous_estimates_require_selection(comparison_http):
    client, case_id, documents, _, _ = comparison_http
    documents.append(
        SimpleNamespace(
            id=uuid4(),
            case_id=case_id,
            document_type="ESTIMATE",
            extraction_status="EXTRACTED",
            created_at=datetime.now(UTC),
        )
    )
    response = client.get(f"/api/cases/{case_id}/estimate-comparison")
    assert response.json()["status"] == "select_documents"
    assert response.json()["rows"] == []
    response = client.get(
        f"/api/cases/{case_id}/estimate-comparison",
        params={
            "estimate_document_id": str(documents[0].id),
            "final_document_id": str(documents[1].id),
        },
    )
    assert response.json()["difference"] == "50.00"


def test_unextracted_document_and_foreign_or_wrong_type_selection(comparison_http):
    client, case_id, documents, _, _ = comparison_http
    documents[0].extraction_status = "NOT_STARTED"
    assert client.get(f"/api/cases/{case_id}/estimate-comparison").json()["status"] == (
        "awaiting_extraction"
    )
    for invalid in (uuid4(), documents[1].id):
        response = client.get(
            f"/api/cases/{case_id}/estimate-comparison",
            params={"estimate_document_id": str(invalid)},
        )
        assert response.status_code == 422


def test_forbidden_case_reveals_no_documents(comparison_http, monkeypatch):
    client, case_id, _, _, store = comparison_http

    def denied(*args):
        raise Forbidden("case membership required")

    def unexpected_query(*args):
        pytest.fail("documents queried before authorization")

    monkeypatch.setattr(api, "_visible_case", denied)
    store.scalars = unexpected_query
    response = client.get(f"/api/cases/{case_id}/estimate-comparison")
    assert response.status_code == 403
    assert "documents" not in response.json()


def test_comparison_requires_actor_header(comparison_http):
    client, case_id, _, _, _ = comparison_http
    del app.dependency_overrides[current_actor]
    response = client.get(f"/api/cases/{case_id}/estimate-comparison")
    assert response.status_code == 403
