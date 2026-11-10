"""Upload links and token-scoped upload through the HTTP API. All files are synthetic
bytes built in memory."""

import json
import logging
import secrets
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from app import services as svc
from app.documents import service as docs_service
from app.documents.service import INVALID_LINK, UploadLimits, get_upload_limits, hash_token
from app.errors import Forbidden
from app.main import RedactUploadTokens, app
from app.models import EvidenceDocument, UploadToken
from app.states import DocumentType
from tests.test_upload_validation import make_jpeg, make_pdf, make_png

PDF = "application/pdf"
PNG = "image/png"
JPEG = "image/jpeg"


@pytest.fixture
def case(db, actor):
    c = svc.create_case(db, actor, patient_alias="Patient (synthetic)", currency="INR")
    db.commit()
    return c


def make_link(client, headers, case_id, types=("BILL",), **extra):
    body = {"document_types": list(types), **extra}
    r = client.post(f"/api/cases/{case_id}/upload-links", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def upload(client, token, content, mime=PDF, document_type="BILL", headers=None):
    return client.post(
        f"/api/uploads/{token}",
        params={"document_type": document_type},
        content=content,
        headers={"Content-Type": mime, **(headers or {})},
    )


def stored_files(storage):
    return [p for p in storage.root.rglob("*") if p.is_file()]


def insert_token(db, case, user, **kw):
    raw = secrets.token_urlsafe(32)
    data = {
        "case_id": case.id,
        "token_sha256": hash_token(raw),
        "document_types": ["BILL"],
        "max_uploads": 3,
        "expires_at": datetime.now(UTC) + timedelta(hours=1),
        "created_by": user.id,
    }
    data.update(kw)
    db.add(UploadToken(**data))
    db.flush()
    return raw


# ---------------------------------------------------------------- creating links


def test_payer_creates_a_link_and_the_token_is_never_stored(client, db, headers, case):
    r = client.post(
        f"/api/cases/{case.id}/upload-links",
        json={"document_types": ["BILL", "RECEIPT"], "max_uploads": 4, "ttl_minutes": 30},
        headers=headers,
    )
    assert r.status_code == 201
    assert r.headers["cache-control"] == "no-store"
    body = r.json()
    assert set(body) == {"id", "case_id", "token", "document_types", "max_uploads", "expires_at"}
    token = body["token"]
    assert len(token) == 43
    assert body["case_id"] == str(case.id)
    assert body["document_types"] == ["BILL", "RECEIPT"]
    assert body["max_uploads"] == 4

    expires = datetime.fromisoformat(body["expires_at"])
    assert timedelta(minutes=29) < expires - datetime.now(UTC) <= timedelta(minutes=30)

    row = db.query(UploadToken).one()
    assert row.token_sha256 == hash_token(token)
    assert token not in row.token_sha256
    events = [e for e in svc.case_audit(db, case.id) if e.event_type == "UPLOAD_LINK_CREATED"]
    assert len(events) == 1
    everything = json.dumps(
        [[e.before, e.after, e.details, e.actor_label] for e in svc.case_audit(db, case.id)]
    )
    assert token not in everything


def test_other_payer_cannot_create_a_link(client, headers, other_payer, case):
    r = client.post(
        f"/api/cases/{case.id}/upload-links",
        json={"document_types": ["BILL"]},
        headers={"X-Demo-User-Id": str(other_payer.id)},
    )
    assert r.status_code == 403


def test_link_creation_needs_an_identity(client, case):
    r = client.post(f"/api/cases/{case.id}/upload-links", json={"document_types": ["BILL"]})
    assert r.status_code == 403


@pytest.mark.parametrize(
    "body",
    [
        {"document_types": []},
        {"document_types": ["BILL", "BILL"]},
        {"document_types": ["PROVIDER_SUPPORTING"]},
        {"document_types": ["OTHER"]},
        {"document_types": ["BILL"], "max_uploads": 0},
        {"document_types": ["BILL"], "max_uploads": 51},
        {"document_types": ["BILL"], "ttl_minutes": 0},
        {"document_types": ["BILL"], "ttl_minutes": 1441},
        {"document_types": ["BILL"], "surprise": True},
    ],
)
def test_bad_link_requests_are_422(client, headers, case, body):
    r = client.post(f"/api/cases/{case.id}/upload-links", json=body, headers=headers)
    assert r.status_code == 422


# ---------------------------------------------------------------- link info


def test_link_info_does_not_use_up_an_upload(client, headers, case):
    link = make_link(client, headers, case.id, ("BILL", "RECEIPT"), max_uploads=2)
    for _ in range(3):
        r = client.get(f"/api/uploads/{link['token']}")
        assert r.status_code == 200
    body = r.json()
    assert set(body) == {
        "document_types",
        "uploads_remaining",
        "expires_at",
        "max_upload_bytes",
        "max_pages",
        "allowed_mime_types",
    }
    assert body["document_types"] == ["BILL", "RECEIPT"]
    assert body["uploads_remaining"] == 2
    assert body["max_upload_bytes"] == 20 * 1024 * 1024
    assert body["max_pages"] == 20
    assert body["allowed_mime_types"] == [PDF, JPEG, PNG]
    assert str(case.id) not in r.text
    assert r.headers["cache-control"] == "no-store"


def test_link_info_for_a_bad_token_is_403(client):
    r = client.get(f"/api/uploads/{secrets.token_urlsafe(32)}")
    assert r.status_code == 403
    assert r.json()["message"] == INVALID_LINK


# ---------------------------------------------------------------- uploading


@pytest.mark.parametrize(
    ("content", "mime", "pages"),
    [(make_pdf(3), PDF, 3), (make_png(), PNG, 1), (make_jpeg(), JPEG, 1)],
    ids=["pdf", "png", "jpeg"],
)
def test_upload_is_stored_privately(client, db, storage, headers, case, content, mime, pages):
    link = make_link(client, headers, case.id, max_uploads=2)
    r = upload(client, link["token"], content, mime)
    assert r.status_code == 201, r.text
    body = r.json()
    assert set(body) == {
        "document_id",
        "document_type",
        "mime_type",
        "file_size",
        "page_count",
        "sha256",
        "uploads_remaining",
    }
    assert "case_id" not in body and "storage_key" not in body
    assert body["mime_type"] == mime
    assert body["page_count"] == pages
    assert body["file_size"] == len(content)
    assert body["uploads_remaining"] == 1

    doc = db.get(EvidenceDocument, body["document_id"])
    assert doc.case_id == case.id
    assert doc.sha256 == body["sha256"]
    assert (storage.root / doc.storage_key).read_bytes() == content
    assert doc.storage_key.startswith(f"cases/{case.id}/")
    assert doc.source_type == "MANUAL_ENTRY"
    assert doc.extraction_status == "NOT_STARTED"
    assert len(stored_files(storage)) == 1

    events = [e for e in svc.case_audit(db, case.id) if e.event_type == "DOCUMENT_UPLOADED"]
    assert len(events) == 1
    assert link["token"] not in json.dumps(events[0].after)
    assert doc.sha256 not in json.dumps(events[0].after)


def test_token_is_limited_to_its_own_case(client, db, headers, actor, case):
    second = svc.create_case(db, actor, patient_alias="Second (synthetic)", currency="INR")
    db.commit()
    link = make_link(client, headers, case.id)
    other_link = make_link(client, headers, second.id)
    doc_id = upload(client, link["token"], make_pdf(1)).json()["document_id"]
    assert db.get(EvidenceDocument, doc_id).case_id == case.id

    first = client.get(f"/api/cases/{case.id}/documents", headers=headers).json()
    other = client.get(f"/api/cases/{second.id}/documents", headers=headers).json()
    assert [d["id"] for d in first] == [doc_id]
    assert other == []
    assert other_link["token"] != link["token"]


def test_document_type_outside_the_token_scope_is_403(client, storage, headers, case):
    link = make_link(client, headers, case.id, ("RECEIPT",))
    r = upload(client, link["token"], make_pdf(1), PDF, document_type="BILL")
    assert r.status_code == 403
    assert r.json()["message"] == INVALID_LINK
    assert stored_files(storage) == []


def test_unknown_document_type_value_is_422(client, headers, case):
    link = make_link(client, headers, case.id)
    assert upload(client, link["token"], make_pdf(1), document_type="NOPE").status_code == 422


@pytest.mark.parametrize("kind", ["bad_format", "unknown", "expired", "exhausted"])
def test_every_token_failure_gives_the_same_403(client, db, storage, headers, payer, case, kind):
    if kind == "bad_format":
        token = "short"
    elif kind == "unknown":
        token = secrets.token_urlsafe(32)
    elif kind == "expired":
        token = insert_token(db, case, payer, expires_at=datetime.now(UTC) - timedelta(minutes=1))
    else:
        token = make_link(client, headers, case.id, max_uploads=1)["token"]
        assert upload(client, token, make_pdf(1)).status_code == 201
    allowed_files = 1 if kind == "exhausted" else 0
    r = upload(client, token, make_png(), PNG)
    assert r.status_code == 403
    assert r.json() == {"error": "forbidden", "message": INVALID_LINK}
    assert len(stored_files(storage)) == allowed_files
    assert client.get(f"/api/uploads/{token}").status_code == 403


def test_the_same_file_twice_is_409_and_stores_nothing_new(client, storage, headers, case):
    link = make_link(client, headers, case.id)
    assert upload(client, link["token"], make_pdf(2)).status_code == 201
    r = upload(client, link["token"], make_pdf(2))
    assert r.status_code == 409
    assert "already uploaded" in r.json()["message"]
    assert len(stored_files(storage)) == 1
    # The refused upload did not use up an upload.
    assert client.get(f"/api/uploads/{link['token']}").json()["uploads_remaining"] == 4


def test_declared_type_must_match_the_content(client, storage, headers, case):
    link = make_link(client, headers, case.id)
    r = upload(client, link["token"], make_png(), PDF)
    assert r.status_code == 422
    assert "does not match" in r.json()["message"]
    assert stored_files(storage) == []
    assert client.get(f"/api/uploads/{link['token']}").json()["uploads_remaining"] == 5


def test_text_file_declared_as_pdf_is_422(client, storage, headers, case):
    link = make_link(client, headers, case.id)
    assert upload(client, link["token"], b"just some text", PDF).status_code == 422
    assert upload(client, link["token"], b"<html></html>", "text/html").status_code == 422
    assert stored_files(storage) == []


def test_empty_body_is_422(client, headers, case):
    link = make_link(client, headers, case.id)
    assert upload(client, link["token"], b"", PDF).status_code == 422


def test_too_many_pages_is_422(client, storage, headers, case):
    app.dependency_overrides[get_upload_limits] = lambda: UploadLimits(1024 * 1024, 2)
    link = make_link(client, headers, case.id)
    r = upload(client, link["token"], make_pdf(3), PDF)
    assert r.status_code == 422
    assert "limit is 2" in r.json()["message"]
    assert stored_files(storage) == []


@pytest.mark.parametrize("mode", ["content_length", "streamed"])
def test_oversize_file_is_422(client, storage, headers, case, mode):
    app.dependency_overrides[get_upload_limits] = lambda: UploadLimits(1024, 20)
    link = make_link(client, headers, case.id)
    big = b"%PDF-1.4\n" + b"0" * 2048
    # "streamed" claims a small Content-Length, so only the byte cap while reading can refuse it.
    extra = {"Content-Length": "10"} if mode == "streamed" else None
    r = upload(client, link["token"], big, PDF, headers=extra)
    assert r.status_code == 422
    assert "larger than the 1 KB limit" in r.json()["message"]
    assert stored_files(storage) == []
    assert client.get(f"/api/uploads/{link['token']}").json()["uploads_remaining"] == 5


def test_bad_link_is_refused_before_the_body_is_read(client, headers, case):
    app.dependency_overrides[get_upload_limits] = lambda: UploadLimits(1024, 20)
    big = b"%PDF-1.4\n" + b"0" * 4096
    r = upload(client, secrets.token_urlsafe(32), big, PDF)
    assert r.status_code == 403


def test_upload_does_not_need_an_identity_header(client, headers, case):
    link = make_link(client, headers, case.id)
    # No X-Demo-User-Id on the upload call: the token is the only credential.
    assert upload(client, link["token"], make_pdf(1)).status_code == 201


def test_the_last_upload_slot_cannot_be_taken_twice(client, db, storage, headers, case):
    """A concurrent upload may use the last slot between the cheap check and the locked check.
    The locked check must re-read the row, not trust what the session loaded earlier."""
    link = make_link(client, headers, case.id, max_uploads=1)
    docs_service.check_upload_allowed(db, link["token"], DocumentType.BILL)  # loads the row
    db.execute(text("UPDATE upload_tokens SET use_count = max_uploads"))  # "the other upload"
    with pytest.raises(Forbidden):
        docs_service.receive_upload(
            db,
            storage,
            UploadLimits(1024 * 1024, 20),
            link["token"],
            DocumentType.BILL,
            PDF,
            make_pdf(1),
        )
    assert stored_files(storage) == []


def test_upload_tokens_are_redacted_from_access_logs():
    token = secrets.token_urlsafe(32)
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:1", "POST", f"/api/uploads/{token}?document_type=BILL", "1.1", 201),
        None,
    )
    assert RedactUploadTokens().filter(record) is True
    line = record.getMessage()
    assert token not in line
    assert "/api/uploads/[redacted]?document_type=BILL" in line
    assert "201" in line


# ---------------------------------------------------------------- reading documents


def test_documents_are_listed_without_the_storage_key(client, headers, case):
    link = make_link(client, headers, case.id)
    upload(client, link["token"], make_pdf(1))
    r = client.get(f"/api/cases/{case.id}/documents", headers=headers)
    assert r.status_code == 200
    (doc,) = r.json()
    assert set(doc) == {
        "id",
        "case_id",
        "document_type",
        "mime_type",
        "file_size",
        "page_count",
        "sha256",
        "source_type",
        "extraction_status",
        "uploaded_by_role",
        "created_at",
    }
    assert "storage_key" not in r.text
    assert doc["uploaded_by_role"] == "RELATIVE"
    assert doc["extraction_status"] == "NOT_STARTED"


def test_document_is_visible_to_the_payer_but_not_to_another_payer(
    client, headers, other_payer, case
):
    link = make_link(client, headers, case.id)
    doc_id = upload(client, link["token"], make_pdf(1)).json()["document_id"]
    assert client.get(f"/api/documents/{doc_id}", headers=headers).status_code == 200
    stranger = {"X-Demo-User-Id": str(other_payer.id)}
    assert client.get(f"/api/documents/{doc_id}", headers=stranger).status_code == 403
    assert client.get(f"/api/cases/{case.id}/documents", headers=stranger).status_code == 403


def test_unknown_document_is_404(client, headers):
    r = client.get("/api/documents/00000000-0000-0000-0000-000000000000", headers=headers)
    assert r.status_code == 404
