import uuid
from io import BytesIO

import pytest
from PIL import Image
from pypdf import PdfReader
from sqlalchemy import func, select

from app import services as svc
from app.demo_samples import SAMPLE_NAMES, sample_bytes
from app.models import CareCase, DocumentExtraction, EvidenceDocument, LedgerEntry
from app.states import UserRole


@pytest.fixture
def demo_headers(db):
    payer = svc.create_user(
        db, "Designated synthetic payer", UserRole.PAYER, email="payer@demo.invalid", is_demo=True
    )
    return {"X-Demo-User-Id": str(payer.id)}


def test_designated_identity_and_samples(client, db, demo_headers):
    svc.create_user(db, "Another demo payer", UserRole.PAYER, is_demo=True)
    assert client.get("/api/demo/identity").json()["id"] == demo_headers["X-Demo-User-Id"]
    for name in SAMPLE_NAMES:
        response = client.get(f"/api/demo/samples/{name}", headers=demo_headers)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        content, _ = sample_bytes(name)
        if name.endswith("pdf"):
            text = PdfReader(BytesIO(content)).pages[0].extract_text()
            assert "SYNTHETIC" in text and "USD" in text
        else:
            with Image.open(BytesIO(content)) as image:
                image.load()
                assert image.width >= 1200


def test_fresh_runs_preserve_history_and_replay_is_idempotent(client, db, demo_headers):
    body = {"mode": "EMPTY", "request_id": str(uuid.uuid4())}
    first = client.post("/api/demo/runs", headers=demo_headers, json=body)
    assert first.status_code == 201, first.text
    assert client.post("/api/demo/runs", headers=demo_headers, json=body).json() == first.json()
    second = client.post(
        "/api/demo/runs",
        headers=demo_headers,
        json={"mode": "EMPTY", "request_id": str(uuid.uuid4())},
    )
    assert second.status_code == 201
    assert first.json()["case_id"] != second.json()["case_id"]
    assert (
        db.scalar(
            select(func.count())
            .select_from(CareCase)
            .where(CareCase.payer_user_id == uuid.UUID(demo_headers["X-Demo-User-Id"]))
        )
        == 2
    )


def test_prepared_run_stops_before_human_review_and_financial_effects(client, db, demo_headers):
    body = {"mode": "PREPARED", "request_id": str(uuid.uuid4())}
    response = client.post("/api/demo/runs", headers=demo_headers, json=body)
    assert response.status_code == 201, response.text
    assert client.post("/api/demo/runs", headers=demo_headers, json=body).json() == response.json()
    case_id = uuid.UUID(response.json()["case_id"])
    assert (
        db.scalar(
            select(func.count())
            .select_from(EvidenceDocument)
            .where(EvidenceDocument.case_id == case_id)
        )
        == 3
    )
    assert (
        db.scalar(
            select(func.count())
            .select_from(DocumentExtraction)
            .where(DocumentExtraction.case_id == case_id)
        )
        == 3
    )
    assert (
        db.scalar(
            select(func.count()).select_from(LedgerEntry).where(LedgerEntry.case_id == case_id)
        )
        == 0
    )


def test_demo_routes_refuse_non_demo_and_arbitrary_sample(client, headers, demo_headers):
    assert (
        client.post(
            "/api/demo/runs",
            headers=headers,
            json={"mode": "EMPTY", "request_id": str(uuid.uuid4())},
        ).status_code
        == 403
    )
    assert client.get("/api/demo/samples/unknown.pdf", headers=demo_headers).status_code == 404
