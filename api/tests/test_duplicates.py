import uuid
from dataclasses import replace
from datetime import date
from decimal import Decimal

from app.reconciliation.duplicates import find_exact_duplicates
from app.reconciliation.views import LineView

DAY = date(2026, 11, 2)


def line(n, desc, total, *, day=DAY, qty="1", unit=None):
    return LineView(
        id=uuid.uuid4(),
        line_number=n,
        description_raw=desc,
        service_date=day,
        quantity=None if qty is None else Decimal(qty),
        unit_price=Decimal(unit if unit is not None else total),
        line_total=Decimal(total),
        currency="INR",
    )


def test_exact_duplicate_detected_with_case_and_punctuation_differences():
    lines = [
        line(1, "Room charges", "12000.00", qty="2", unit="6000.00"),
        line(3, "Complete blood count (CBC)", "2000.00"),
        line(4, "Complete Blood Count  CBC", "2000.00"),
    ]
    [cand] = find_exact_duplicates(lines)
    assert cand.line_numbers == (3, 4)
    assert cand.first_line_id == lines[1].id
    assert cand.repeat_line_ids == (lines[2].id,)
    # Only the repeat is "involved"; the first occurrence is presumed legitimate.
    assert cand.amount_involved == Decimal("2000.00")
    assert "Possible duplicate" in cand.explanation
    assert "fraud" not in cand.explanation.lower()


def test_triplicate_counts_two_repeats():
    lines = [line(n, "X-ray chest", "800.00") for n in (5, 2, 9)]
    [cand] = find_exact_duplicates(lines)
    assert cand.line_numbers == (2, 5, 9)
    assert cand.amount_involved == Decimal("1600.00")


def test_different_date_is_not_a_duplicate():
    lines = [line(1, "CBC", "2000.00"), line(2, "CBC", "2000.00", day=date(2026, 11, 3))]
    assert find_exact_duplicates(lines) == []


def test_different_amount_or_quantity_is_not_a_duplicate():
    assert find_exact_duplicates([line(1, "CBC", "2000.00"), line(2, "CBC", "2000.01")]) == []
    assert (
        find_exact_duplicates(
            [
                line(1, "Saline", "200.00", qty="2", unit="100.00"),
                line(2, "Saline", "200.00", qty="4", unit="50.00"),
            ]
        )
        == []
    )


def test_missing_service_date_is_never_flagged():
    lines = [line(1, "CBC", "2000.00", day=None), line(2, "CBC", "2000.00", day=None)]
    assert find_exact_duplicates(lines) == []


def test_similar_but_not_identical_descriptions_not_flagged():
    # Near-duplicate matching is deliberately out of scope for the exact rule.
    lines = [line(1, "CBC", "2000.00"), line(2, "Complete blood count", "2000.00")]
    assert find_exact_duplicates(lines) == []


def test_detection_does_not_mutate_input():
    lines = [line(1, "CBC", "2000.00"), line(2, "CBC", "2000.00")]
    snapshot = list(lines)
    find_exact_duplicates(lines)
    assert lines == snapshot


def test_dedupe_key_is_order_independent():
    a, b = line(1, "CBC", "2000.00"), line(2, "CBC", "2000.00")
    forward = find_exact_duplicates([a, b])[0].dedupe_key
    assert forward == find_exact_duplicates([b, a])[0].dedupe_key


def test_distinct_item_identifiers_are_not_exact_duplicates():
    a, b = line(1, "Lab panel", "100.00"), line(2, "Lab panel", "100.00")
    assert find_exact_duplicates([replace(a, code="A1"), replace(b, code="B2")]) == []
    assert len(find_exact_duplicates([replace(a, code="A1"), replace(b, code="a1")])) == 1


def test_mixed_currency_lines_are_not_exact_duplicates():
    a, b = line(1, "Lab panel", "100.00"), line(2, "Lab panel", "100.00")
    assert find_exact_duplicates([a, replace(b, currency="USD")]) == []
