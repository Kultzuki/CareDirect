"""Synthetic regression cases for tax accounting and immutable promoted reviews."""

from decimal import Decimal

import pytest

from app import services as svc
from app.extraction.adapter import MockExtractionAdapter, get_extraction_adapter
from app.main import app
from tests.test_extraction_flow import extract, ingest, promote, revise


@pytest.fixture
def case(db, actor):
    case = svc.create_case(db, actor, patient_alias="Synthetic tax review", currency="INR")
    db.commit()
    return case


def tax_adapter(total, subtotal, tax="18.00"):
    class Adapter(MockExtractionAdapter):
        def extract(self, **kwargs):
            raw = super().extract(**kwargs)
            raw["line_items"] = raw["line_items"][:1]
            line = raw["line_items"][0]
            for key, value in (
                ("quantity", "1"),
                ("unit_price", "100.00"),
                ("line_total", "100.00"),
            ):
                line[key]["value"] = value
            line["code"]["value"] = "SYNTHETIC-TAX-ITEM"
            for key, value in (
                ("total", total),
                ("subtotal", subtotal),
                ("tax_total", tax),
                ("advance_paid", "0.00"),
            ):
                raw[key]["value"] = value
            return raw

    return Adapter


@pytest.mark.parametrize(
    "total,subtotal,expected,count",
    [("118.00", "100.00", "118.00", 2), ("100.00", "82.00", "100.00", 1)],
)
def test_tax_exclusive_and_inclusive_totals_are_accounted_once(
    client, headers, db, actor, case, total, subtotal, expected, count
):
    app.dependency_overrides[get_extraction_adapter] = tax_adapter(total, subtotal)
    view = extract(client, headers, ingest(client, headers, case, "clean_bill"))
    assert view["can_promote"] is True
    result = promote(client, headers, view["id"])
    assert result.status_code == 201, result.text
    bill = result.json()["bill"]
    assert len(bill["line_items"]) == count
    actual = svc.get_buckets(db, case)
    assert actual.bill_total == Decimal(expected)
    assert actual.invariant_holds and actual.consistent
    assert not svc.run_checks(db, actor, case.id)
    lines = svc.case_lines(db, case.id)
    assert lines[0].code == "SYNTHETIC-TAX-ITEM"
    if count == 2:
        assert lines[-1].description_raw == "Stated invoice tax"
        assert lines[-1].source_page is not None
        assert lines[-1].source_text
        assert lines[-1].status == "PENDING_REVIEW"


@pytest.mark.parametrize("total,subtotal", [("120.00", "100.00"), ("100.00", "90.00")])
def test_ambiguous_tax_is_blocked_without_ledger_effect(client, headers, db, case, total, subtotal):
    app.dependency_overrides[get_extraction_adapter] = tax_adapter(total, subtotal)
    view = extract(client, headers, ingest(client, headers, case, "clean_bill"))
    assert any("tax cannot be reconciled" in text for text in view["promotion_blockers"])
    assert promote(client, headers, view["id"]).status_code == 409
    assert svc.case_ledger(db, case.id) == []


def test_promoted_extraction_cannot_diverge_from_immutable_financial_record(
    client, headers, db, case
):
    view = extract(client, headers, ingest(client, headers, case, "clean_bill"))
    assert promote(client, headers, view["id"]).status_code == 201
    before = svc.get_buckets(db, case)
    result = revise(
        client,
        headers,
        view["id"],
        corrections=[{"path": "line_items.0.line_total", "value": "999.00"}],
    )
    assert result.status_code == 409
    assert "explicit adjustment" in result.json()["message"]
    assert svc.get_buckets(db, case) == before


def test_ai_extraction_and_human_revision_do_not_write_ledger_until_promotion(
    client, headers, db, case
):
    app.dependency_overrides[get_extraction_adapter] = tax_adapter("118.00", "100.00")
    view = extract(client, headers, ingest(client, headers, case, "clean_bill"))
    assert svc.case_ledger(db, case.id) == []
    result = revise(
        client,
        headers,
        view["id"],
        corrections=[
            {"path": "line_items.0.line_total", "value": "120.00"},
            {"path": "line_items.0.unit_price", "value": "120.00"},
            {"path": "subtotal", "value": "120.00"},
            {"path": "total", "value": "138.00"},
        ],
    )
    assert result.status_code == 201, result.text
    assert svc.case_ledger(db, case.id) == []
    assert promote(client, headers, view["id"]).status_code == 201
    buckets = svc.get_buckets(db, case)
    assert buckets.bill_total == buckets.payable_now == Decimal("138.00")
    assert buckets.pending_review == Decimal("138.00")
    assert buckets.queried == buckets.already_paid == Decimal("0.00")
    assert buckets.consistent
