"""The JSON shapes the web app depends on. If one of these key sets changes, the web client
must change with it, so the test pins them exactly."""

import pytest

from app import services as svc
from app.extraction.synthetic import FIXTURES_BY_NAME, render
from tests.test_documents_api import make_link, upload

UPLOAD_LINK = {"id", "case_id", "token", "document_types", "max_uploads", "expires_at"}
LINK_INFO = {
    "document_types",
    "uploads_remaining",
    "expires_at",
    "max_upload_bytes",
    "max_pages",
    "allowed_mime_types",
}
UPLOAD_RECEIPT = {
    "document_id",
    "document_type",
    "mime_type",
    "file_size",
    "page_count",
    "sha256",
    "uploads_remaining",
}
DOCUMENT = {
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
EXTRACTION_VIEW = {
    "id",
    "document_id",
    "case_id",
    "document_type",
    "extracted_document_type",
    "schema_version",
    "provider",
    "model",
    "prompt_version",
    "is_mock",
    "low_confidence_threshold",
    "created_at",
    "actor_label",
    "fields",
    "review_required",
    "promotion_blockers",
    "can_promote",
    "promoted_to",
    "revisions",
    "original_payload",
}
FIELD = {
    "path",
    "label",
    "group",
    "line_index",
    "line_number",
    "name",
    "kind",
    "value",
    "original_value",
    "model_confidence",
    "source",
    "state",
    "needs_review",
}
SOURCE = {"document_id", "page", "snippet", "bbox"}
REVISION = {
    "revision_number",
    "corrections",
    "confirmed_paths",
    "reason",
    "actor_label",
    "created_at",
}
REVISION_CORRECTION = {"path", "value", "source"}
PROMOTED_TO = {"bill_id", "external_payment_id"}
PROMOTE = {"bill", "external_payment"}


@pytest.fixture
def case(db, actor):
    c = svc.create_case(db, actor, patient_alias="Patient (synthetic)", currency="INR")
    db.commit()
    return c


def test_every_response_has_exactly_the_documented_keys(client, headers, case):
    link = make_link(client, headers, case.id, ("BILL",))
    assert set(link) == UPLOAD_LINK
    assert set(client.get(f"/api/uploads/{link['token']}").json()) == LINK_INFO

    fixture = FIXTURES_BY_NAME["photographed_bill"]
    r = upload(client, link["token"], render(fixture), fixture.mime_type)
    assert set(r.json()) == UPLOAD_RECEIPT
    doc_id = r.json()["document_id"]

    assert set(client.get(f"/api/documents/{doc_id}", headers=headers).json()) == DOCUMENT
    (listed,) = client.get(f"/api/cases/{case.id}/documents", headers=headers).json()
    assert set(listed) == DOCUMENT

    view = client.post(f"/api/documents/{doc_id}/extract", headers=headers).json()
    assert set(view) == EXTRACTION_VIEW
    assert all(set(f) == FIELD for f in view["fields"])
    sourced = [f for f in view["fields"] if f["source"] is not None]
    assert sourced and all(set(f["source"]) == SOURCE for f in sourced)
    assert any(f["source"] is None for f in view["fields"])  # invoice_date is unreadable
    assert view["promoted_to"] is None

    body = {
        "corrections": [{"path": "line_items.0.line_total", "value": "1200.00", "source": None}],
        "confirmed_paths": ["provider_identifier"],
        "reason": "Checked against the paper bill",
    }
    r = client.post(f"/api/extractions/{view['id']}/revisions", json=body, headers=headers)
    revised = r.json()
    assert set(revised) == EXTRACTION_VIEW
    (revision,) = revised["revisions"]
    assert set(revision) == REVISION
    assert all(set(c) == REVISION_CORRECTION for c in revision["corrections"])

    again = client.get(f"/api/documents/{doc_id}/extraction", headers=headers).json()
    assert set(again) == EXTRACTION_VIEW

    promoted = client.post(f"/api/extractions/{view['id']}/promote", headers=headers)
    assert set(promoted.json()) == PROMOTE
    assert promoted.json()["external_payment"] is None
    after = client.get(f"/api/documents/{doc_id}/extraction", headers=headers).json()
    assert set(after["promoted_to"]) == PROMOTED_TO


def test_decimal_values_are_always_strings(client, headers, case):
    link = make_link(client, headers, case.id, ("BILL",))
    fixture = FIXTURES_BY_NAME["clean_bill"]
    doc_id = upload(client, link["token"], render(fixture), fixture.mime_type).json()["document_id"]
    view = client.post(f"/api/documents/{doc_id}/extract", headers=headers).json()
    for field in view["fields"]:
        for key in ("value", "original_value", "model_confidence"):
            assert field[key] is None or isinstance(field[key], str)
    assert isinstance(view["low_confidence_threshold"], str)
    bill = client.post(f"/api/extractions/{view['id']}/promote", headers=headers).json()["bill"]
    assert isinstance(bill["printed_total"], str)
    for line in bill["line_items"]:
        for key in ("line_total", "unit_price", "quantity", "extraction_confidence"):
            assert isinstance(line[key], str)
