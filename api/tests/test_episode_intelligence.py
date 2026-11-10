"""Feature A regressions: grouping, source attribution, money, caching and chronology."""

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

from app import services as svc
from app.episode.deepseek import DeepSeekClient
from app.episode.overlap import analyze_episode_overlaps, find_overlaps
from app.episode.records import _base, assess_affinity
from app.models import AuditEvent
from app.states import FlagType
from tests.test_documents_api import make_link, upload
from tests.test_estimate_checks import estimate
from tests.test_extraction_flow import extract, ingest, promote, revise
from tests.test_upload_validation import make_pdf


def record(amount="1000.00", **kwargs):
    item = _base(uuid4(), "BILL", datetime(2026, 11, 9, tzinfo=UTC))
    item.update(provider="Hospital", currency="INR", date="2026-10-26", amount=amount, **kwargs)
    item["lines"] = [
        dict(
            id=f"{item['id']}:1",
            ledger_line_id=str(uuid4()),
            line_number=1,
            description="Consultation",
            code="C1",
            service_date="2026-10-26",
            quantity="1.000",
            unit_price=amount,
            line_total=amount,
            sources=[],
        )
    ]
    return item


@pytest.mark.parametrize(
    "change,value",
    [
        ("service_date", "2026-10-27"),
        ("service_date", None),
        ("quantity", "2.000"),
        ("unit_price", "1100.00"),
        ("code", "OTHER"),
    ],
)
def test_distinct_or_undated_services_are_not_automatically_duplicates(change, value):
    first, second = record(), record()
    second["lines"][0][change] = value
    assert find_overlaps([first, second], "INR") == []


def test_same_date_exact_match_has_sources_and_no_automatic_deduction():
    records = [record(), record()]
    result = analyze_episode_overlaps(None, SimpleNamespace(currency="INR"), records)
    assert result.gross_billed == result.net_billed == Decimal("2000.00")
    assert result.overlap_amount == Decimal("1000.00")
    assert len(result.overlaps) == 1
    assert {s["document_id"] for s in result.overlaps[0].sources} == {r["id"] for r in records}


def test_changed_provider_currency_or_conflicting_membership_excludes_exact_match():
    for override in (
        dict(provider="Another hospital"),
        dict(currency="USD"),
        dict(affinity_status="conflict"),
    ):
        first, second = record(), record()
        second.update(override)
        assert not find_overlaps([first, second], "INR")


def test_package_and_exact_rules_do_not_count_the_same_diagnostic_twice():
    final, diagnostics = record("39000.00"), record("4000.00")
    package = dict(
        final["lines"][0],
        id="package",
        description="Surgery package",
        line_total="35000.00",
        unit_price="35000.00",
    )
    final["lines"][0].update(description="Blood panel", line_total="4000.00", unit_price="4000.00")
    diagnostics["lines"][0].update(description="Blood panel")
    final["lines"].append(package)
    result = analyze_episode_overlaps(None, SimpleNamespace(currency="INR"), [final, diagnostics])
    assert result.overlap_amount == Decimal("4000.00")
    assert result.net_billed == result.gross_billed == Decimal("43000.00")
    assert len(result.overlaps) == 1


def test_package_scope_is_unverified_and_multiple_packages_share_one_exposure():
    packages = [record("35000.00"), record("20000.00")]
    for index, package in enumerate(packages):
        package["lines"][0]["description"] = f"Surgery package {index}"
    diagnostic = record("4000.00")
    diagnostic["lines"][0]["description"] = "Blood panel"
    diagnostic["lines"][0]["service_date"] = "2026-10-22"
    result = analyze_episode_overlaps(
        None, SimpleNamespace(currency="INR"), packages + [diagnostic]
    )
    assert len(result.overlaps) == 2
    assert result.overlap_amount == Decimal("4000.00")
    assert result.net_billed == Decimal("59000.00")
    assert all("unverified" in f.description.lower() for f in result.overlaps)


def test_affinity_requires_evidence_and_checks_provider_local_references():
    unknown = assess_affinity([record()], "INR")[0]
    assert unknown["affinity_status"] == "unknown"
    first, second = record(patient_reference="P1"), record(patient_reference="P1")
    assert all(
        r["affinity_status"] == "consistent" for r in assess_affinity([first, second], "INR")
    )
    second["patient_reference"] = "P2"
    assert all(r["affinity_status"] == "conflict" for r in assess_affinity([first, second], "INR"))
    second["provider"] = "Different hospital"
    assert all(r["affinity_status"] == "unknown" for r in assess_affinity([first, second], "INR"))


@pytest.fixture
def case(db, actor):
    item = svc.create_case(
        db,
        actor,
        patient_alias="Father",
        currency="INR",
        episode_title="Knee Replacement — November 2026",
        is_demo=True,
    )
    db.commit()
    return item


def get_episode(client, headers, case):
    response = client.get(f"/api/cases/{case.id}/episode", headers=headers)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    return response.json()


def test_inventory_includes_unextracted_and_unpromoted_documents_and_current_estimate(
    client, headers, case, db
):
    bill_id = ingest(client, headers, case, "clean_bill")
    extract(client, headers, bill_id)
    receipt_id = ingest(client, headers, case, "upi_receipt_mismatch")
    est = estimate(client, headers, case)
    correction = revise(
        client, headers, est["id"], corrections=[{"path": "total", "value": "14000.00"}]
    )
    assert correction.status_code == 201, correction.text
    link = make_link(client, headers, case.id)
    waiting = upload(client, link["token"], make_pdf(1), document_type="BILL")
    assert waiting.status_code == 201
    body = get_episode(client, headers, case)
    assert len(body["documents"]) == 4
    by_id = {d["id"]: d for d in body["documents"]}
    assert by_id[receipt_id]["extraction_status"] == "NOT_STARTED"
    assert not by_id[bill_id]["is_recorded"]
    estimate_doc = by_id[est["document_id"]]
    assert estimate_doc["amount"] == "14000.00"
    assert next(f for f in estimate_doc["sources"] if f["path"] == "total")["state"] == "corrected"
    assert body["recorded_bill_total"] == "0.00"
    assert not svc.case_ledger(db, case.id)


def test_promoted_documents_are_not_listed_or_counted_twice(client, headers, case):
    bill = extract(client, headers, ingest(client, headers, case, "clean_bill"))
    assert promote(client, headers, bill["id"]).status_code == 201
    body = get_episode(client, headers, case)
    assert len(body["documents"]) == 1
    assert body["documents"][0]["is_recorded"]
    assert body["total_billed"] == body["recorded_bill_total"]


def add_bill(db, actor, case, when):
    return svc.add_bill(
        db,
        actor,
        case.id,
        svc.BillInput(
            provider_name="Hospital",
            currency="INR",
            bill_date=when,
            printed_total=Decimal("1000.00"),
            lines=[
                svc.LineInput(
                    line_number=1,
                    description_raw="Consultation",
                    service_date=when,
                    quantity=Decimal("1"),
                    unit_price=Decimal("1000.00"),
                    line_total=Decimal("1000.00"),
                )
            ],
        ),
    )


def test_episode_questions_block_approval_until_review_and_never_change_ledger(
    db, actor, case, client, headers
):
    add_bill(db, actor, case, date(2026, 10, 20))
    add_bill(db, actor, case, date(2026, 10, 20))
    before = len(svc.case_ledger(db, case.id))
    flags = svc.run_checks(db, actor, case.id)
    assert len(flags) == 1 and flags[0].flag_type == FlagType.CROSS_DOCUMENT_OVERLAP
    assert len(svc.case_ledger(db, case.id)) == before
    assert svc.run_checks(db, actor, case.id) == []
    for line in svc.case_lines(db, case.id):
        svc.accept_line(db, actor, line.id)
    assert any("overlap" in text for text in svc.approval_blockers(db, case))
    assert svc.get_buckets(db, case).net_bill_total == Decimal("2000.00")
    dashboard = client.get("/api/dashboard", headers=headers).json()
    assert (
        next(item for item in dashboard["cases"] if item["id"] == str(case.id))["open_questions"]
        == 1
    )


def test_separate_consultation_dates_have_no_overlap_flag(db, actor, case):
    add_bill(db, actor, case, date(2026, 10, 20))
    add_bill(db, actor, case, date(2026, 10, 28))
    assert svc.run_checks(db, actor, case.id) == []
    assert svc.get_buckets(db, case).net_bill_total == Decimal("2000.00")


def test_get_never_calls_model_and_api_rejects_other_payers(client, headers, case, other_payer):
    with patch.object(
        DeepSeekClient, "_call_deepseek", side_effect=AssertionError("GET must stay local")
    ):
        get_episode(client, headers, case)
    unauthorized = {"X-Demo-User-Id": str(other_payer.id)}
    for path, method in (("episode", client.get), ("episode/analyze", client.post)):
        assert method(f"/api/cases/{case.id}/{path}", headers=unauthorized).status_code == 403


def test_timeline_distinguishes_upload_and_service_dates_and_unknowns(
    client, headers, case, db, actor
):
    add_bill(db, actor, case, None)
    ingest(client, headers, case, "upi_receipt_mismatch")
    body = get_episode(client, headers, case)
    dated = [e["event_date"] for e in body["timeline"] if e["event_date"]]
    assert dated == sorted(dated)
    assert all(len(d) == 10 for d in dated)
    assert any(
        e["event_type"] == "UPLOAD" and e["date_basis"] == "uploaded_at" for e in body["timeline"]
    )
    assert any(e["event_date"] is None and e["date_basis"] == "unknown" for e in body["timeline"])


def test_ai_output_is_cached_audited_and_invalidated_by_evidence_changes(client, headers, case, db):
    ingest(client, headers, case, "clean_bill")
    initial = get_episode(client, headers, case)
    fake = dict(
        provider="deepseek",
        model="synthetic-model",
        analysis_status="model_advice",
        episode_title="Suggested title",
        clinical_summary="Synthetic advice",
        affinity_explanation="Insufficient evidence",
        belongs_together=None,
        key_findings=[],
        payer_recommendations=[],
        document_assessments=[],
    )
    with (
        patch.object(DeepSeekClient, "_call_deepseek", return_value=fake) as call,
        patch.object(
            DeepSeekClient, "is_configured", new_callable=lambda: property(lambda self: True)
        ),
    ):
        initial = get_episode(client, headers, case)
        path = f"/api/cases/{case.id}/episode/analyze"
        response = client.post(
            path, headers=headers, json={"input_fingerprint": initial["input_fingerprint"]}
        )
        assert response.status_code == 200, response.text
        assert response.json()["ai_insights"]["provider"] == "deepseek"
        assert client.post(path, headers=headers).status_code == 200
        assert get_episode(client, headers, case)["ai_insights"]["provider"] == "deepseek"
        assert call.call_count == 1
        json.dumps(call.call_args.args)
        assert "sources" not in json.dumps(call.call_args.args)
        audits = list(
            db.scalars(select(AuditEvent).where(AuditEvent.event_type == "EPISODE_ANALYZED"))
        )
        assert len(audits) == 1
        # New upload invalidates cached advice without an automatic model retry.
        ingest(client, headers, case, "upi_receipt_mismatch")
        assert get_episode(client, headers, case)["ai_insights"]["analysis_status"] == "stale"
        stale = client.post(
            path, headers=headers, json={"input_fingerprint": initial["input_fingerprint"]}
        )
        assert stale.status_code == 409
        assert call.call_count == 1


def test_episode_metadata_edits_are_audited_and_do_not_touch_finances(client, headers, case, db):
    response = client.post(
        f"/api/cases/{case.id}/episode/details",
        headers=headers,
        json={"episode_title": " Updated title ", "clinical_context": "Treatment context"},
    )
    assert response.status_code == 200
    assert response.json()["episode_title"] == "Updated title"
    assert not svc.case_ledger(db, case.id)
    assert any(a.event_type == "EPISODE_DETAILS_UPDATED" for a in svc.case_audit(db, case.id))
    assert (
        client.post(
            f"/api/cases/{case.id}/episode/details", headers=headers, json={"episode_title": " "}
        ).status_code
        == 422
    )


def test_client_payload_and_output_validation_are_bounded_and_fail_closed():
    client = DeepSeekClient(
        api_key="synthetic-not-real", base_url="https://api.goedelmachines.com/v1"
    )
    output = dict(
        episode_title="Episode",
        clinical_summary="Only supplied evidence is reviewed.",
        belongs_together=None,
        affinity_explanation="Insufficient evidence",
        key_findings=[],
        payer_recommendations=[],
        document_assessments=[
            dict(document_id="doc", status="insufficient_evidence", reason="No patient reference")
        ],
    )
    response = MagicMock()
    response.json.return_value = {
        "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(output)}}]
    }
    with patch("httpx.Client.post", return_value=response) as call:
        result = client.analyze_episode({}, [{"id": "doc"}], [], [])
        assert result["provider"] == "deepseek"
        payload = call.call_args.kwargs["json"]
        assert payload["model"] == client.model
        assert payload["chat_template_kwargs"] == {"thinking": False}
        assert payload["max_tokens"] <= 8000
        for invalid in (
            [],
            {**output, "belongs_together": "true"},
            {**output, "document_assessments": []},
            {**output, "payable_now": "0.00"},
        ):
            response.json.return_value["choices"][0]["message"]["content"] = json.dumps(invalid)
            failed = client.analyze_episode({}, [{"id": "doc"}], [], [])
            assert failed["provider"] == "deterministic-heuristic"
            assert failed["belongs_together"] is None
            assert failed["analysis_status"] == "provider_unavailable"
    with patch("httpx.Client.post", side_effect=httpx.ConnectError("Synthetic failure")):
        assert client.analyze_episode({}, [], [], [])["analysis_status"] == "provider_unavailable"
