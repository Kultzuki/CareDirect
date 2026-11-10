"""Feature B: exact arithmetic, attribution, ambiguity and source preservation."""

from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

from app.extraction.adapter import MockExtractionAdapter
from app.extraction.schema import parse_extraction
from app.extraction.service import _resolve
from app.reconciliation.estimate_comparison import compare, snapshot


def line(description, amount, *, quantity="1.000", price=None, number=1, code=None):
    return {
        "description": description,
        "code": code,
        "quantity": quantity,
        "unit_price": price or amount,
        "line_total": amount,
        "line_number": number,
        "service_date": None,
        "sources": [
            {
                "path": f"line_items.{number - 1}.line_total",
                "source": {
                    "document_id": "source-document",
                    "page": 2,
                    "snippet": f"{description}: {amount}",
                },
                "state": "corrected",
                "needs_review": False,
            }
        ],
    }


def doc(lines, total, **kwargs):
    return {
        "document_id": "document",
        "provider": "Hospital",
        "currency": "INR",
        "needs_review": False,
        "type_matches": True,
        "lines": lines,
        "total": total,
        "tax": None,
        "total_sources": [],
        **kwargs,
    }


def test_requested_example_attributes_exact_5500_difference_and_sources():
    names = ["Consultation", "Laboratory tests", "Medicines", "Room charges"]
    old = ["1000.00", "4000.00", "3000.00", "10000.00"]
    new = ["1000.00", "6000.00", "4500.00", "12000.00"]
    estimate = doc(
        [line(n, a, number=i + 1) for i, (n, a) in enumerate(zip(names, old, strict=True))],
        "18000.00",
    )
    final = doc(
        [line(n, a, number=i + 1) for i, (n, a) in enumerate(zip(names, new, strict=True))],
        "23500.00",
    )
    original = deepcopy((estimate, final))
    result = compare(estimate, final)
    assert result["difference"] == result["itemized_difference"] == "5500.00"
    assert result["status"] == "compared"
    assert "Laboratory tests" in result["summary"] and "Room charges" in result["summary"]
    assert "5500.00 higher" in result["summary"]
    labs = next(r for r in result["rows"] if r["description"] == "Laboratory tests")
    assert labs["difference"] == "2000.00"
    assert labs["final_lines"][0]["sources"] == final["lines"][1]["sources"]
    assert (estimate, final) == original


def test_quantity_price_new_removed_and_repeated_are_independent_signals():
    estimate = doc(
        [line("Room", "100.00", price="100.00"), line("Removed", "50.00", number=2)], "150.00"
    )
    final = doc(
        [
            line("Room", "240.00", quantity="2.000", price="120.00"),
            line("Room", "120.00", price="120.00", number=2),
            line("New", "10.00", number=3),
        ],
        "370.00",
    )
    result = compare(estimate, final)
    rows = {r["description"]: r for r in result["rows"]}
    assert {
        "increased_quantity",
        "increased_unit_price",
        "repeated_service",
        "explanation_needed",
    } <= set(rows["Room"]["changes"])
    assert "new_service" in rows["New"]["changes"]
    assert "removed_service" in rows["Removed"]["changes"]
    assert rows["Removed"]["difference"] == "-50.00"
    assert result["difference"] == "220.00"


def test_offsetting_differences_are_not_sum_of_absolute_deltas():
    result = compare(
        doc([line("A", "100.00"), line("B", "200.00", number=2)], "300.00"),
        doc([line("A", "200.00"), line("B", "100.00", number=2)], "300.00"),
    )
    assert result["difference"] == result["itemized_difference"] == "0.00"
    assert len([r for r in result["rows"] if r["changes"]]) == 2


def test_tax_is_counted_once_when_additive_and_not_when_inclusive():
    estimate = doc([line("A", "100.00")], "110.00", tax="10.00")
    final = doc([line("A", "200.00")], "220.00", tax="20.00")
    result = compare(estimate, final)
    assert result["itemized_difference"] == result["difference"] == "110.00"
    assert len(result["rows"]) == 2
    inclusive = compare(
        doc([line("A", "110.00")], "110.00", tax="10.00"),
        doc([line("A", "220.00")], "220.00", tax="20.00"),
    )
    assert inclusive["itemized_difference"] == "110.00"
    assert len(inclusive["rows"]) == 1


def test_unreconciled_totals_and_missing_values_remain_visible():
    estimate = doc([line("A", "100.00")], "100.00")
    final = doc([line("A", "120.00")], "150.00")
    result = compare(estimate, final)
    assert result["difference"] == "50.00"
    assert result["itemized_difference"] == "20.00"
    assert result["status"] == "needs_review"
    assert any("do not fully explain" in warning for warning in result["warnings"])
    final["lines"][0]["line_total"] = None
    missing = compare(estimate, final)
    assert missing["itemized_difference"] is None
    assert missing["rows"][0]["final"] is None


def test_missing_quantities_or_mixed_prices_do_not_invent_attribution():
    result = compare(
        doc([line("Room", "100.00", quantity=None)], "100.00"),
        doc([line("Room", "150.00", quantity=None), line("Room", "120.00", number=2)], "270.00"),
    )
    assert "increased_quantity" not in result["rows"][0]["changes"]
    assert "increased_unit_price" not in result["rows"][0]["changes"]


def test_provider_currency_type_and_low_confidence_guards():
    estimate = doc([line("A", "100.00")], "100.00")
    for overrides in (
        {"provider": "Other hospital"},
        {"currency": "USD"},
        {"type_matches": False},
        {"provider": None},
    ):
        result = compare(estimate, doc([line("A", "120.00")], "120.00", **overrides))
        assert result["status"] == "blocked"
        assert result["rows"] == []
    result = compare(estimate, doc([line("A", "120.00")], "120.00", needs_review=True))
    assert result["status"] == "needs_review"
    assert "provisional" in result["warnings"][0]


def test_normalization_and_changed_codes_do_not_hide_unmatched_lines():
    estimate = doc([line("  ROOM  Charge ", "100.00", code="R1")], "100.00")
    result = compare(estimate, doc([line("room charge", "100.00", code="R1")], "100.00"))
    assert len(result["rows"]) == 1
    assert result["rows"][0]["changes"] == []
    changed_code = compare(estimate, doc([line("room charge", "100.00", code="R2")], "100.00"))
    assert len(changed_code["rows"]) == 2


def test_snapshot_uses_human_revisions_with_field_source_and_state():
    document_id = uuid4()
    raw = MockExtractionAdapter().extract(
        document_id=document_id,
        document_type="BILL",
        mime_type="application/pdf",
        content=b"CAREDIRECT-SYNTHETIC-FIXTURE:clean_bill",
        page_count=2,
    )
    parsed = parse_extraction(raw, document_id=document_id, page_count=2)
    source = {"document_id": str(document_id), "page": 1, "snippet": "Corrected total 1600"}
    revision = SimpleNamespace(
        revision_number=1,
        confirmed_paths=[],
        corrections=[
            {
                "path": "line_items.0.line_total",
                "value": "1600.00",
                "source": source,
            }
        ],
    )
    loaded = SimpleNamespace(
        doc=SimpleNamespace(id=document_id, document_type="BILL"),
        ex=parsed,
        fields=_resolve(parsed, [revision]),
    )
    result = snapshot(loaded)
    assert result["lines"][0]["line_total"] == "1600.00"
    field = next(f for f in result["lines"][0]["sources"] if f["path"] == "line_items.0.line_total")
    assert field["source"] == source
    assert field["state"] == "corrected"
    assert field["needs_review"] is False


def test_no_lines_and_no_totals_does_not_report_a_zero_difference():
    result = compare(doc([], None), doc([], None))
    assert result["difference"] is None
    assert result["itemized_difference"] is None
    assert result["status"] == "needs_review"
