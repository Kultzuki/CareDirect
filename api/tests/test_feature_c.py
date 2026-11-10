"""Feature C: advisory matches, deterministic gates and unchanged accounting."""

import json
from copy import deepcopy
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from app import services as svc
from app.episode.deepseek import DeepSeekClient
from app.episode.overlap import analyze_episode_overlaps, find_overlaps
from app.episode.records import assess_affinity, load_episode_records
from app.episode.service import get_care_episode
from app.reconciliation.duplicates import find_exact_duplicates
from app.reconciliation.semantic import near_pairs, saved_suggestions
from app.states import FlagStatus, FlagType
from tests.test_duplicates import line
from tests.test_episode_intelligence import record


def test_missing_quantity_or_unit_price_does_not_establish_exact_duplicate():
    from dataclasses import replace

    for field in ("quantity", "unit_price"):
        lines = [replace(line(n, "CBC", "1000"), **{field: None}) for n in (1, 2)]
        assert find_exact_duplicates(lines) == []


@pytest.fixture
def case(db, actor):
    return svc.create_case(db, actor, patient_alias="Patient (synthetic)", currency="INR")


def pair():
    a, b = record(), record()
    a["lines"][0].update(description="CBC Test", code=None)
    b["lines"][0].update(description="Haemogram", code=None)
    return a, b


def test_aliases_are_review_questions_with_both_sources_and_unchanged_totals():
    a, b = pair()
    original = deepcopy([a, b])
    [finding] = find_overlaps([a, b], "INR")
    assert finding.overlap_type == "NEAR_DUPLICATE"
    assert "Local service-name alias" in finding.description
    assert "incomplete" in finding.description
    assert len(finding.sources) == 2
    assert [a, b] == original
    result = analyze_episode_overlaps(None, type("Case", (), {"currency": "INR"})(), [a, b])
    assert result.gross_billed == result.net_billed == Decimal("2000.00")
    assert result.overlap_amount == Decimal("1000.00")


@pytest.mark.parametrize(
    "field,value",
    [
        ("service_date", None),
        ("service_date", "2026-10-27"),
        ("quantity", None),
        ("quantity", "2"),
        ("quantity", "0"),
        ("code", "OTHER"),
    ],
)
def test_model_cannot_override_service_conflicts(field, value):
    a, b = pair()
    a["lines"][0]["code"] = "C1"
    b["lines"][0]["code"] = "C1"
    b["lines"][0][field] = value
    proposal = [dict(left_line_id=a["lines"][0]["id"], right_line_id=b["lines"][0]["id"])]
    assert list(near_pairs([a, b], "INR", proposal)) == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("provider", "Other lab"),
        ("currency", "USD"),
        ("affinity_status", "conflict"),
        ("review_state", "needs_review"),
        ("document_type", "ESTIMATE"),
        ("document_type", "RECEIPT"),
    ],
)
def test_incompatible_context_is_excluded(field, value):
    a, b = pair()
    b[field] = value
    assert find_overlaps([a, b], "INR") == []


def test_package_overlap_across_hospital_and_lab_keeps_inclusion_unverified():
    hospital, lab = pair()
    hospital["lines"][0]["description"] = "Surgical package"
    lab["provider"] = "Separate laboratory"
    [finding] = find_overlaps([hospital, lab], "INR")
    assert finding.overlap_type == "PACKAGE_SCOPE"
    assert "Inclusion is unverified" in finding.description
    assert len(finding.sources) == 2
    lab["date"] = "2026-12-30"
    assert find_overlaps([hospital, lab], "INR") == []


def test_near_prices_may_differ_and_input_order_does_not_change_question():
    a, b = pair()
    b["lines"][0]["line_total"] = "1200.00"
    forward = find_overlaps([a, b], "INR")
    assert len(forward) == 1
    assert forward == find_overlaps([b, a], "INR")


def bill(db, actor, case, descriptions):
    return svc.add_bill(
        db,
        actor,
        case.id,
        svc.BillInput(
            provider_name="Hospital",
            currency="INR",
            bill_date=date(2026, 10, 26),
            printed_total=Decimal(1000 * len(descriptions)),
            lines=[
                svc.LineInput(
                    line_number=i,
                    description_raw=text,
                    service_date=date(2026, 10, 26),
                    quantity=Decimal("1"),
                    unit_price=Decimal("1000"),
                    line_total=Decimal("1000"),
                )
                for i, text in enumerate(descriptions, 1)
            ],
        ),
    )


def test_same_bill_near_flags_idempotent_block_until_human_review(db, actor, case):
    bill(db, actor, case, ["CBC Test", "Complete Blood Count", "Haemogram"])
    before = svc.get_buckets(db, case)
    ledger_count = len(svc.case_ledger(db, case.id))
    flags = svc.run_checks(db, actor, case.id)
    assert flags and all(f.flag_type == FlagType.POSSIBLE_NEAR_DUPLICATE for f in flags)
    assert svc.run_checks(db, actor, case.id) == []
    for li in svc.case_lines(db, case.id):
        svc.accept_line(db, actor, li.id)
    assert any("overlap" in b for b in svc.approval_blockers(db, case))
    for flag in flags:
        svc.change_flag_status(
            db,
            actor,
            flag.id,
            FlagStatus.DISMISSED,
            "Reviewed source: separate specimens confirmed.",
        )
    assert not any("overlap" in b for b in svc.approval_blockers(db, case))
    assert svc.get_buckets(db, case).net_bill_total == before.net_bill_total
    assert len(svc.case_ledger(db, case.id)) == ledger_count


def test_ai_pairs_saved_cached_backend_checked_and_stale_evidence_rejected(db, actor, case):
    bill(db, actor, case, ["FBC investigation", "Full blood count analysis"])
    records = assess_affinity(load_episode_records(db, case), case.currency)
    ids = [li["id"] for d in records for li in d["lines"]]
    output = dict(
        provider="deepseek",
        analysis_status="model_advice",
        episode_title="Review",
        clinical_summary="Needs review",
        belongs_together=None,
        affinity_explanation="Incomplete",
        key_findings=[],
        payer_recommendations=[],
        service_matches=[dict(left_line_id=ids[0], right_line_id=ids[1])],
    )
    with patch.object(DeepSeekClient, "analyze_episode", return_value=output) as call:
        analyzed = get_care_episode(db, case.id, analyze=True, actor=actor)
        assert len(analyzed.overlaps) == 1
        episode = get_care_episode(db, case.id)
        assert len(episode.overlaps) == 1
        assert "AI-proposed" in episode.overlaps[0].description
        get_care_episode(db, case.id, analyze=True, actor=actor)
        assert call.call_count == 1
    [flag] = svc.run_checks(db, actor, case.id)
    assert flag.flag_type == FlagType.POSSIBLE_NEAR_DUPLICATE
    assert saved_suggestions(db, case, records)
    records[0]["lines"][0]["service_date"] = "2026-10-27"
    assert saved_suggestions(db, case, records) == []


@pytest.mark.parametrize("pair_ids", [("a", "foreign"), ("a", "a")])
def test_model_foreign_or_self_pairs_fail_closed(pair_ids):
    client = DeepSeekClient(api_key="fake")
    output = dict(
        episode_title="Review",
        clinical_summary="Review",
        belongs_together=None,
        affinity_explanation="Unknown",
        key_findings=[],
        payer_recommendations=[],
        document_assessments=[dict(document_id="doc", status="needs_review", reason="Review")],
        service_matches=[dict(zip(("left_line_id", "right_line_id"), pair_ids, strict=True))],
    )
    response = MagicMock()
    response.json.return_value = {
        "choices": [dict(finish_reason="stop", message=dict(content=json.dumps(output)))]
    }
    with patch("httpx.Client.post", return_value=response):
        result = client.analyze_episode({}, [dict(id="doc", lines=[dict(id="a")])], [], [])
    assert result["analysis_status"] == "provider_unavailable"
