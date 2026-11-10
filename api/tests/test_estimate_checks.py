"""Synthetic API flows for deterministic estimate comparisons and evidence metadata."""

import pytest

from app import services as svc
from app.extraction.adapter import MockExtractionAdapter, get_extraction_adapter
from app.extraction.synthetic import FIXTURES_BY_NAME, render
from app.main import app
from tests.test_documents_api import make_link, upload
from tests.test_extraction_flow import extract, ingest, promote, revise


@pytest.fixture
def case(db, actor):
    row = svc.create_case(db, actor, patient_alias="Synthetic estimate review", currency="INR")
    db.commit()
    return row


def estimate(client, headers, case, *, total="9000.00", confidence="0.980", suffix=b"estimate"):
    class EstimateAdapter(MockExtractionAdapter):
        def extract(self, **kwargs):
            raw = super().extract(**kwargs)
            raw["document_type"] = "ESTIMATE"
            raw["line_items"][0]["line_total"]["value"] = total
            raw["line_items"][0]["line_total"]["confidence"] = confidence
            return raw

    fixture = FIXTURES_BY_NAME["clean_bill"]
    link = make_link(client, headers, case.id, ("ESTIMATE",))
    content = render(fixture) + b"\n% " + suffix
    document = upload(client, link["token"], content, fixture.mime_type, "ESTIMATE")
    assert document.status_code == 201, document.text
    app.dependency_overrides[get_extraction_adapter] = EstimateAdapter
    try:
        return extract(client, headers, document.json()["document_id"])
    finally:
        app.dependency_overrides[get_extraction_adapter] = MockExtractionAdapter


def test_estimate_drift_has_itemised_evidence_and_does_not_change_money(client, db, headers, case):
    bill = extract(client, headers, ingest(client, headers, case, "clean_bill"))
    assert promote(client, headers, bill["id"]).status_code == 201
    est = estimate(client, headers, case)
    before = len(svc.case_ledger(db, case.id))
    response = client.post(f"/api/cases/{case.id}/run-checks", headers=headers)
    assert response.status_code == 200, response.text
    flags = svc.case_flags(db, case.id)
    drift = [f for f in flags if f.flag_type == "ESTIMATE_DRIFT"]
    assert len(drift) == 1
    flag = drift[0]
    assert flag.evidence["item_changes"]
    assert flag.evidence["estimate_document_id"] == est["document_id"]
    assert flag.evidence["estimate_sources"]
    assert flag.evidence["limitations"]
    assert flag.line_item_ids
    assert len(svc.case_ledger(db, case.id)) == before
    again = client.post(f"/api/cases/{case.id}/run-checks", headers=headers)
    assert again.status_code == 200
    assert len(svc.case_flags(db, case.id)) == len(flags)


def test_revised_estimate_changes_current_rule_fingerprint(client, db, headers, case):
    from app.reconciliation.checks import collect_flags

    bill = extract(client, headers, ingest(client, headers, case, "clean_bill"))
    assert promote(client, headers, bill["id"]).status_code == 201
    est = estimate(client, headers, case)
    original = [f for f in collect_flags(db, case) if f.flag_type == "ESTIMATE_DRIFT"]
    assert original
    corrected = revise(
        client,
        headers,
        est["id"],
        corrections=[{"path": "line_items.0.line_total", "value": "1500.00"}],
    )
    assert corrected.status_code == 201, corrected.text
    current = [f for f in collect_flags(db, case) if f.flag_type == "ESTIMATE_DRIFT"]
    assert current == []


def test_low_confidence_estimate_is_a_question_not_automatic_authority(client, db, headers, case):
    bill = extract(client, headers, ingest(client, headers, case, "clean_bill"))
    assert promote(client, headers, bill["id"]).status_code == 201
    estimate(client, headers, case, confidence="0.400")
    response = client.post(f"/api/cases/{case.id}/run-checks", headers=headers)
    assert response.status_code == 200
    drift = [f for f in svc.case_flags(db, case.id) if f.flag_type == "ESTIMATE_DRIFT"]
    assert "low-confidence" in drift[0].explanation
    assert svc.get_buckets(db, case).already_paid == 0


@pytest.mark.parametrize("status", ["NOT_STARTED", "FAILED"])
def test_supplied_unextracted_estimate_blocks_approval(client, db, headers, case, status):
    from app.models import EvidenceDocument
    from app.reconciliation.checks import collect_flags

    bill = extract(client, headers, ingest(client, headers, case, "clean_bill"))
    assert promote(client, headers, bill["id"]).status_code == 201
    for line in svc.case_lines(db, case.id):
        svc.accept_line(db, svc.Actor(case.payer, "test payer"), line.id)
    fixture = FIXTURES_BY_NAME["clean_bill"]
    link = make_link(client, headers, case.id, ("ESTIMATE",))
    response = upload(
        client,
        link["token"],
        render(fixture) + b"\n% pending estimate",
        fixture.mime_type,
        "ESTIMATE",
    )
    assert response.status_code == 201
    document_id = response.json()["document_id"]
    document = db.get(EvidenceDocument, document_id)
    document.extraction_status = status
    db.commit()
    flags = [f for f in collect_flags(db, case) if f.flag_type == "ESTIMATE_DRIFT"]
    assert len(flags) == 1
    assert flags[0].evidence["estimate_statuses"][document_id] == status
    assert "awaits a successful extraction" in flags[0].explanation
    assert svc.approval_blockers(db, case)
    readiness = client.get(f"/api/cases/{case.id}", headers=headers)
    assert readiness.status_code == 200
    assert readiness.json()["approval_readiness"]["ready"] is False
