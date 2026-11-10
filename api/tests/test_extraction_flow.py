"""End to end: upload a synthetic fixture through a token, extract it with the mock provider,
review it, and add it to the case. Covers the five required fixtures and the review gate."""

import json
import uuid

import pytest
from sqlalchemy import select

from app import services as svc
from app.extraction.adapter import MockExtractionAdapter, get_adapter, get_extraction_adapter
from app.extraction.schema import parse_extraction
from app.extraction.synthetic import FIXTURES, FIXTURES_BY_NAME, render
from app.main import app
from app.models import DocumentExtraction, EvidenceDocument, ExtractionRevision
from app.states import UserRole
from tests.test_documents_api import make_link, upload
from tests.test_upload_validation import make_pdf

NAMES = [f.name for f in FIXTURES]


@pytest.fixture
def case(db, actor):
    c = svc.create_case(db, actor, patient_alias="Patient (synthetic)", currency="INR")
    db.commit()
    return c


@pytest.fixture
def relative(db):
    return svc.create_user(db, "Test Relative", UserRole.RELATIVE, email="rel@test.invalid")


def ingest(client, headers, case, name, as_type=None):
    fixture = FIXTURES_BY_NAME[name]
    link = make_link(client, headers, case.id, ("BILL", "RECEIPT"), max_uploads=10)
    r = upload(
        client, link["token"], render(fixture), fixture.mime_type, as_type or fixture.document_type
    )
    assert r.status_code == 201, r.text
    return r.json()["document_id"]


def extract(client, headers, doc_id):
    r = client.post(f"/api/documents/{doc_id}/extract", headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def revise(client, headers, extraction_id, **body):
    body.setdefault("corrections", [])
    body.setdefault("confirmed_paths", [])
    body.setdefault("reason", "Checked against the paper document")
    return client.post(f"/api/extractions/{extraction_id}/revisions", json=body, headers=headers)


def promote(client, headers, extraction_id):
    return client.post(f"/api/extractions/{extraction_id}/promote", headers=headers)


def by_path(view):
    return {f["path"]: f for f in view["fields"]}


def flags(client, headers, case_id):
    r = client.post(f"/api/cases/{case_id}/run-checks", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["flags_created"]


# ---------------------------------------------------------------- every fixture


@pytest.mark.parametrize("name", NAMES)
def test_extraction_is_stored_exactly_as_the_validated_mock_output(client, db, headers, case, name):
    doc_id = ingest(client, headers, case, name)
    view = extract(client, headers, doc_id)

    row = db.get(DocumentExtraction, view["id"])
    document = db.get(EvidenceDocument, doc_id)
    raw = MockExtractionAdapter().extract(
        document_id=document.id,
        document_type=str(document.document_type),
        mime_type=document.mime_type,
        content=render(FIXTURES_BY_NAME[name]),
        page_count=document.page_count,
    )
    expected = parse_extraction(raw, document_id=document.id, page_count=document.page_count)
    assert row.payload == expected.model_dump(mode="json")
    assert view["original_payload"] == row.payload
    assert (row.provider, row.model, row.prompt_version) == ("mock", "mock-replay-v1", "none")
    assert view["is_mock"] is True
    assert view["low_confidence_threshold"] == "0.900"
    assert document.extraction_status == "EXTRACTED"

    again = client.post(f"/api/documents/{doc_id}/extract", headers=headers)
    assert again.status_code == 409
    assert "already extracted" in again.json()["message"]
    assert (
        client.get(f"/api/documents/{doc_id}/extraction", headers=headers).json()["id"]
        == (view["id"])
    )


def test_extraction_view_matches_the_contract_for_the_clean_bill(client, headers, case):
    view = extract(client, headers, ingest(client, headers, case, "clean_bill"))
    fields = by_path(view)
    assert len(view["fields"]) == 6 + 4 * 6 + 4
    assert [f["path"] for f in view["fields"][:2]] == ["provider_name", "provider_identifier"]
    total = fields["line_items.2.line_total"]
    assert total["label"] == "Line 3 line total"
    assert (total["group"], total["line_index"], total["line_number"]) == ("line_item", 2, 3)
    assert (total["kind"], total["value"], total["state"]) == ("money", "10000.00", "extracted")
    assert total["original_value"] == "10000.00" and total["needs_review"] is False
    assert total["model_confidence"] == "0.980"
    assert total["source"]["page"] == 1 and "Room charges" in total["source"]["snippet"]
    assert fields["line_items.2.quantity"]["value"] == "2.000"
    assert fields["subtotal"]["source"]["page"] == 2
    assert fields["advance_paid"]["value"] == "4000.00"
    assert view["review_required"] == [] and view["promotion_blockers"] == []
    assert view["can_promote"] is True and view["promoted_to"] is None
    assert view["revisions"] == []


def test_a_file_the_mock_does_not_know_fails_cleanly_and_can_be_retried(client, db, headers, case):
    link = make_link(client, headers, case.id)
    doc_id = upload(client, link["token"], make_pdf(1)).json()["document_id"]

    for _ in range(2):  # the second call proves a FAILED document may be retried
        r = client.post(f"/api/documents/{doc_id}/extract", headers=headers)
        assert r.status_code == 422
        assert "no recorded output" in r.json()["message"]
    assert db.get(EvidenceDocument, doc_id).extraction_status == "FAILED"
    assert db.scalar(select(DocumentExtraction)) is None
    assert client.get(f"/api/documents/{doc_id}/extraction", headers=headers).status_code == 404
    failures = [e for e in svc.case_audit(db, case.id) if e.event_type == "EXTRACTION_FAILED"]
    assert len(failures) == 2


def test_output_that_breaks_the_schema_is_rejected_without_leaking_its_values(
    client, db, headers, case
):
    secret = "SECRET-TEXT-FROM-THE-DOCUMENT"

    class Leaky:
        provider, model, prompt_version = "mock", "mock-replay-v1", "none"

        def extract(self, **kwargs):
            out = MockExtractionAdapter().extract(**kwargs)
            out["patient_name"] = secret
            out["total"]["value"] = 2700.5  # a float, not a decimal string
            return out

    app.dependency_overrides[get_extraction_adapter] = Leaky
    doc_id = ingest(client, headers, case, "clean_bill")
    r = client.post(f"/api/documents/{doc_id}/extract", headers=headers)
    assert r.status_code == 422
    assert secret not in r.text
    assert db.get(EvidenceDocument, doc_id).extraction_status == "FAILED"
    (event,) = [e for e in svc.case_audit(db, case.id) if e.event_type == "EXTRACTION_FAILED"]
    assert "patient_name: extra_forbidden" in event.details["errors"]
    assert secret not in json.dumps(event.details)


def test_a_real_provider_cannot_be_used(client, headers, case):
    doc_id = ingest(client, headers, case, "clean_bill")
    app.dependency_overrides[get_extraction_adapter] = lambda: get_adapter("openai")
    r = client.post(f"/api/documents/{doc_id}/extract", headers=headers)
    assert r.status_code == 409
    assert "not enabled" in r.json()["message"]


def test_audit_events_carry_no_document_text(client, db, headers, case):
    doc_id = ingest(client, headers, case, "clean_bill")
    view = extract(client, headers, doc_id)
    revise(client, headers, view["id"], confirmed_paths=["provider_name"])
    events = [e for e in svc.case_audit(db, case.id) if e.event_type.startswith("EXTRACTION")]
    assert [e.event_type for e in events] == ["EXTRACTION_RECORDED", "EXTRACTION_REVISED"]
    text = json.dumps([[e.before, e.after, e.details] for e in events])
    assert "Synthetic City Hospital" not in text and "INV-SYN" not in text


def test_extract_and_revise_write_no_ledger_entry(client, db, headers, case):
    assert svc.case_ledger(db, case.id) == []
    view = extract(client, headers, ingest(client, headers, case, "photographed_bill"))
    revise(client, headers, view["id"], confirmed_paths=["provider_identifier"])
    assert svc.case_ledger(db, case.id) == []
    assert promote(client, headers, view["id"]).status_code == 409
    assert svc.case_ledger(db, case.id) == []


# ---------------------------------------------------------------- clean bill


def test_clean_bill_is_added_to_the_case_and_the_checks_find_nothing(client, db, headers, case):
    doc_id = ingest(client, headers, case, "clean_bill")
    view = extract(client, headers, doc_id)

    r = promote(client, headers, view["id"])
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["external_payment"] is None
    bill = body["bill"]
    assert bill["source_type"] == "AI_EXTRACTED"
    assert bill["source_document_ref"] == f"evidence_document:{doc_id}"
    assert (bill["bill_number"], bill["bill_date"]) == ("INV-SYN-1001", "2026-11-01")
    assert (bill["printed_total"], bill["printed_advance_paid"]) == ("25000.00", "4000.00")
    assert bill["printed_balance_due"] is None
    assert [ln["line_total"] for ln in bill["line_items"]] == [
        "1500.00",
        "2000.00",
        "10000.00",
        "11500.00",
    ]
    assert [ln["quantity"] for ln in bill["line_items"]] == ["1.000", "1.000", "2.000", "1.000"]
    assert all(ln["source_type"] == "AI_EXTRACTED" for ln in bill["line_items"])
    assert all(ln["status"] == "PENDING_REVIEW" for ln in bill["line_items"])
    assert bill["line_items"][2]["extraction_confidence"] == "0.950"
    assert bill["line_items"][2]["source_page"] == 1
    assert "Room charges" in bill["line_items"][2]["source_text"]

    assert flags(client, headers, case.id) == []

    after = client.get(f"/api/documents/{doc_id}/extraction", headers=headers).json()
    assert after["promoted_to"]["bill_id"] == bill["id"]
    assert after["can_promote"] is False and after["promotion_blockers"] == []


def test_promoted_charges_cannot_go_to_approval_until_the_payer_reviews_them(
    client, db, headers, case
):
    view = extract(client, headers, ingest(client, headers, case, "clean_bill"))
    promote(client, headers, view["id"])
    detail = client.get(f"/api/cases/{case.id}", headers=headers).json()
    assert detail["buckets"]["pending_review"] == "25000.00"
    assert detail["approval_readiness"]["ready"] is False
    assert any("not yet reviewed" in b for b in detail["approval_readiness"]["blockers"])
    assert len(svc.case_ledger(db, case.id)) == 4


def test_promoting_twice_is_refused(client, db, headers, case):
    view = extract(client, headers, ingest(client, headers, case, "clean_bill"))
    assert promote(client, headers, view["id"]).status_code == 201
    again = promote(client, headers, view["id"])
    assert again.status_code == 409
    assert "already added" in again.json()["message"]
    assert len(svc.case_ledger(db, case.id)) == 4


# ---------------------------------------------------------------- photographed bill


def test_photographed_bill_cannot_be_added_until_the_doubtful_values_are_reviewed(
    client, db, headers, case
):
    doc_id = ingest(client, headers, case, "photographed_bill")
    view = extract(client, headers, doc_id)
    fields = by_path(view)

    assert set(view["review_required"]) == {"provider_identifier", "line_items.0.line_total"}
    assert fields["line_items.0.line_total"]["value"] == "1700.00"
    assert fields["line_items.0.line_total"]["model_confidence"] == "0.550"
    assert fields["line_items.0.line_total"]["needs_review"] is True
    assert fields["provider_identifier"]["model_confidence"] == "0.700"
    assert fields["invoice_date"]["value"] is None
    assert fields["invoice_date"]["needs_review"] is False
    assert view["can_promote"] is False

    refused = promote(client, headers, view["id"])
    assert refused.status_code == 409
    message = refused.json()["message"]
    assert "Line 1 line total needs review (model confidence 0.550)" in message
    assert "Provider identifier needs review (model confidence 0.700)" in message
    assert svc.case_ledger(db, case.id) == []

    fixed = revise(
        client,
        headers,
        view["id"],
        corrections=[{"path": "line_items.0.line_total", "value": "1200", "source": None}],
        confirmed_paths=["provider_identifier"],
        reason="Checked against the paper bill",
    )
    assert fixed.status_code == 201, fixed.text
    after = fixed.json()
    fields = by_path(after)
    total = fields["line_items.0.line_total"]
    assert (total["value"], total["original_value"]) == ("1200.00", "1700.00")
    assert (total["state"], total["model_confidence"], total["needs_review"]) == (
        "corrected",
        "0.550",
        False,
    )
    assert fields["provider_identifier"]["state"] == "confirmed"
    assert after["review_required"] == [] and after["can_promote"] is True
    assert after["original_payload"] == view["original_payload"]

    promoted = promote(client, headers, view["id"])
    assert promoted.status_code == 201, promoted.text
    bill = promoted.json()["bill"]
    assert bill["line_items"][0]["line_total"] == "1200.00"
    assert bill["bill_date"] is None  # the date was unreadable and stays null
    assert bill["printed_total"] == "3700.00"
    # The model's own confidence is kept, never replaced by the human's.
    assert bill["line_items"][0]["extraction_confidence"] == "0.550"
    assert flags(client, headers, case.id) == []


def test_a_missing_value_can_be_supplied_only_with_its_source(client, headers, case):
    view = extract(client, headers, ingest(client, headers, case, "photographed_bill"))
    no_source = revise(
        client,
        headers,
        view["id"],
        corrections=[{"path": "invoice_date", "value": "2026-11-02", "source": None}],
    )
    assert no_source.status_code == 422
    assert "page and snippet" in no_source.json()["message"]

    ok = revise(
        client,
        headers,
        view["id"],
        corrections=[
            {
                "path": "invoice_date",
                "value": "2026-11-02",
                "source": {"page": 1, "snippet": "Invoice Date: 2026-11-02"},
            }
        ],
    )
    assert ok.status_code == 201, ok.text
    date_field = by_path(ok.json())["invoice_date"]
    assert date_field["value"] == "2026-11-02" and date_field["original_value"] is None
    assert date_field["model_confidence"] is None  # no confidence is invented for a person
    assert date_field["state"] == "corrected"
    assert date_field["source"]["snippet"] == "Invoice Date: 2026-11-02"


def test_an_unchanged_correction_is_recorded_as_a_confirmation(client, headers, case):
    view = extract(client, headers, ingest(client, headers, case, "photographed_bill"))
    r = revise(
        client,
        headers,
        view["id"],
        corrections=[{"path": "provider_identifier", "value": "SYN-REG-0001", "source": None}],
    )
    assert r.status_code == 201
    assert by_path(r.json())["provider_identifier"]["state"] == "confirmed"
    assert r.json()["revisions"][0]["corrections"] == []
    assert r.json()["revisions"][0]["confirmed_paths"] == ["provider_identifier"]


def test_revisions_are_numbered_and_leave_the_original_untouched(client, db, headers, case):
    view = extract(client, headers, ingest(client, headers, case, "photographed_bill"))
    stored = json.dumps(db.get(DocumentExtraction, view["id"]).payload, sort_keys=True)

    first = revise(client, headers, view["id"], confirmed_paths=["provider_identifier"])
    second = revise(
        client,
        headers,
        view["id"],
        corrections=[{"path": "line_items.0.line_total", "value": "1200.00", "source": None}],
        reason="Second look",
    )
    assert first.status_code == second.status_code == 201
    assert [r["revision_number"] for r in second.json()["revisions"]] == [1, 2]
    assert second.json()["revisions"][1]["reason"] == "Second look"
    assert json.dumps(db.get(DocumentExtraction, view["id"]).payload, sort_keys=True) == stored
    rows = db.scalars(select(ExtractionRevision).order_by(ExtractionRevision.revision_number))
    assert [r.revision_number for r in rows] == [1, 2]
    events = [e.event_type for e in svc.case_audit(db, case.id)]
    assert events.count("EXTRACTION_REVISED") == 2


@pytest.mark.parametrize(
    "body",
    [
        {"corrections": [{"path": "nope", "value": "1", "source": None}]},
        {"corrections": [{"path": "line_items.9.line_total", "value": "1", "source": None}]},
        {"corrections": [{"path": "line_items.0.line_total", "value": "12.345", "source": None}]},
        {"corrections": [{"path": "line_items.0.line_total", "value": "abc", "source": None}]},
        {"corrections": [{"path": "line_items.0.quantity", "value": "0", "source": None}]},
        {"corrections": [{"path": "invoice_date", "value": "02/11/2026", "source": None}]},
        {"corrections": [{"path": "currency", "value": "RUPEE", "source": None}]},
        {"corrections": [{"path": "invoice_number", "value": "X" * 81, "source": None}]},
        {"confirmed_paths": ["nope"]},
        {"corrections": [], "confirmed_paths": []},
        {"confirmed_paths": ["provider_name", "provider_name"]},
        {
            "corrections": [{"path": "provider_name", "value": "Other", "source": None}],
            "confirmed_paths": ["provider_name"],
        },
        {
            "corrections": [
                {"path": "provider_name", "value": "A", "source": None},
                {"path": "provider_name", "value": "B", "source": None},
            ]
        },
        {"confirmed_paths": ["provider_name"], "reason": "   "},
        {"confirmed_paths": ["provider_name"], "reason": ""},
        {
            "corrections": [
                {
                    "path": "line_items.0.line_total",
                    "value": "1.00",
                    "source": {"page": 7, "snippet": "x"},
                }
            ]
        },
        {
            "corrections": [
                {"path": "line_items.0.line_total", "value": "1.00", "source": {"page": 1}}
            ]
        },
    ],
    ids=lambda b: str(sorted(b))[:40],
)
def test_bad_revisions_are_422(client, headers, case, body):
    view = extract(client, headers, ingest(client, headers, case, "photographed_bill"))
    assert revise(client, headers, view["id"], **body).status_code == 422


@pytest.mark.parametrize("value", [1200.5, 1200, True])
def test_a_json_number_is_not_accepted_as_a_correction_value(client, headers, case, value):
    view = extract(client, headers, ingest(client, headers, case, "photographed_bill"))
    body = {"corrections": [{"path": "line_items.0.line_total", "value": value, "source": None}]}
    assert revise(client, headers, view["id"], **body).status_code == 422


def test_unknown_keys_in_a_revision_are_refused(client, headers, case):
    view = extract(client, headers, ingest(client, headers, case, "photographed_bill"))
    for body in (
        {"confirmed_paths": ["provider_name"], "reason": "x", "extra": 1},
        {"corrections": [{"path": "total", "value": "1", "source": None, "confidence": "1"}]},
        {"corrections": [{"path": "total", "value": "1", "source": {"page": 1, "url": "x"}}]},
    ):
        body.setdefault("reason", "x")
        r = client.post(f"/api/extractions/{view['id']}/revisions", json=body, headers=headers)
        assert r.status_code == 422


# ---------------------------------------------------------------- duplicates and arithmetic


def test_duplicate_rows_are_added_as_extracted_and_the_check_flags_them(client, headers, case):
    view = extract(client, headers, ingest(client, headers, case, "duplicate_rows"))
    assert view["review_required"] == []
    assert promote(client, headers, view["id"]).status_code == 201
    found = flags(client, headers, case.id)
    assert [f["flag_type"] for f in found] == ["POSSIBLE_EXACT_DUPLICATE"]
    assert found[0]["amount_involved"] == "2000.00"


def test_arithmetic_mismatch_is_added_as_printed_and_the_check_flags_it(client, headers, case):
    view = extract(client, headers, ingest(client, headers, case, "arithmetic_mismatch"))
    assert view["review_required"] == []
    fields = by_path(view)
    assert fields["line_items.0.line_total"]["value"] == "1600.00"
    assert fields["total"]["value"] == "2700.00"
    assert promote(client, headers, view["id"]).status_code == 201
    found = flags(client, headers, case.id)
    assert {f["flag_type"] for f in found} == {"ARITHMETIC_MISMATCH"}
    assert {f["evidence"]["kind"] for f in found} == {"LINE_TOTAL", "BILL_TOTAL"}


# ---------------------------------------------------------------- UPI receipt


def test_upi_receipt_that_does_not_match_the_bill_is_held_for_clarification(
    client, db, headers, case
):
    bill_view = extract(client, headers, ingest(client, headers, case, "clean_bill"))
    assert promote(client, headers, bill_view["id"]).status_code == 201

    receipt_view = extract(client, headers, ingest(client, headers, case, "upi_receipt_mismatch"))
    fields = by_path(receipt_view)
    assert fields["receipt.amount"]["value"] == "4500.00"
    assert fields["receipt.payment_method"]["value"] == "UPI"
    assert fields["receipt.amount"]["label"] == "Receipt amount"
    assert fields["provider_name"]["value"] is None
    assert receipt_view["can_promote"] is True

    r = promote(client, headers, receipt_view["id"])
    assert r.status_code == 201, r.text
    payment = r.json()["external_payment"]
    assert r.json()["bill"] is None
    assert (payment["method"], payment["amount"], payment["currency"]) == ("UPI", "4500.00", "INR")
    assert (payment["reference"], payment["paid_on"]) == ("SYNUPI0000123", "2026-10-29")
    assert payment["source_type"] == "AI_EXTRACTED" and payment["status"] == "SUBMITTED"

    done = client.post(f"/api/external-payments/{payment['id']}/reconcile", headers=headers)
    assert done.status_code == 200
    assert done.json()["status"] == "NEEDS_CLARIFICATION"
    problems = " ".join(done.json()["match_basis"]["problems"])
    assert "exceeds the printed advance" in problems
    assert "does not match the provider name" in problems

    mismatches = [
        f
        for f in client.get(f"/api/cases/{case.id}/flags", headers=headers).json()
        if f["flag_type"] == "ADVANCE_PAYMENT_MISMATCH"
    ]
    assert len(mismatches) == 1
    buckets = client.get(f"/api/cases/{case.id}/buckets", headers=headers).json()
    assert buckets["already_paid"] == "0.00"


# ---------------------------------------------------------------- guards


def test_document_type_chosen_at_upload_must_match_what_the_model_read(client, headers, case):
    doc_id = ingest(client, headers, case, "clean_bill", as_type="RECEIPT")
    view = extract(client, headers, doc_id)
    assert view["document_type"] == "RECEIPT" and view["extracted_document_type"] == "BILL"
    assert view["can_promote"] is False
    assert any("differs from the type the model read" in b for b in view["promotion_blockers"])
    assert promote(client, headers, view["id"]).status_code == 409


def test_a_bill_in_another_currency_is_blocked(client, db, headers, payer, actor):
    usd_case = svc.create_case(db, actor, patient_alias="USD (synthetic)", currency="USD")
    db.commit()
    view = extract(client, headers, ingest(client, headers, usd_case, "clean_bill"))
    assert any("differs from the case currency USD" in b for b in view["promotion_blockers"])
    assert promote(client, headers, view["id"]).status_code == 409


def test_other_payer_cannot_see_extract_revise_or_promote(client, headers, other_payer, case):
    doc_id = ingest(client, headers, case, "photographed_bill")
    view = extract(client, headers, doc_id)
    stranger = {"X-Demo-User-Id": str(other_payer.id)}
    assert client.post(f"/api/documents/{doc_id}/extract", headers=stranger).status_code == 403
    assert client.get(f"/api/documents/{doc_id}/extraction", headers=stranger).status_code == 403
    assert (
        revise(client, stranger, view["id"], confirmed_paths=["provider_name"]).status_code == 403
    )
    assert promote(client, stranger, view["id"]).status_code == 403


def test_unrelated_relative_cannot_read_extract_revise_or_promote(client, headers, relative, case):
    doc_id = ingest(client, headers, case, "clean_bill")
    helper = {"X-Demo-User-Id": str(relative.id)}
    assert client.post(f"/api/documents/{doc_id}/extract", headers=helper).status_code == 403
    view = extract(client, headers, doc_id)
    assert client.get(f"/api/documents/{doc_id}/extraction", headers=helper).status_code == 403
    assert revise(client, helper, view["id"], confirmed_paths=["provider_name"]).status_code == 403
    assert promote(client, helper, view["id"]).status_code == 403
    assert promote(client, headers, view["id"]).status_code == 201


def test_unknown_ids_are_404(client, headers):
    ghost = uuid.uuid4()
    assert client.post(f"/api/documents/{ghost}/extract", headers=headers).status_code == 404
    assert client.get(f"/api/documents/{ghost}/extraction", headers=headers).status_code == 404
    assert revise(client, headers, ghost, confirmed_paths=["total"]).status_code == 404
    assert promote(client, headers, ghost).status_code == 404


def test_estimates_are_not_added_to_the_ledger(client, db, headers, case):
    fixture = FIXTURES_BY_NAME["clean_bill"]
    link = make_link(client, headers, case.id, ("ESTIMATE",))
    r = upload(client, link["token"], render(fixture), fixture.mime_type, "ESTIMATE")
    view = extract(client, headers, r.json()["document_id"])
    assert any("Estimates are not added" in b for b in view["promotion_blockers"])
    assert promote(client, headers, view["id"]).status_code == 409
    assert svc.case_ledger(db, case.id) == []
