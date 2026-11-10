import uuid
from datetime import date
from decimal import Decimal

from app.reconciliation.arithmetic import check_bill_arithmetic
from app.reconciliation.views import BillView, LineView


def line(n, total, qty=None, unit=None):
    return LineView(
        id=uuid.uuid4(),
        line_number=n,
        description_raw=f"item {n}",
        service_date=date(2026, 11, 2),
        quantity=None if qty is None else Decimal(qty),
        unit_price=None if unit is None else Decimal(unit),
        line_total=Decimal(total),
        currency="INR",
    )


def bill(total=None, advance=None, due=None):
    return BillView(
        id=uuid.uuid4(),
        provider_name="Hospital",
        bill_date=date(2026, 11, 4),
        currency="INR",
        printed_total=None if total is None else Decimal(total),
        printed_advance_paid=None if advance is None else Decimal(advance),
        printed_balance_due=None if due is None else Decimal(due),
    )


def test_consistent_bill_has_no_issues():
    lines = [line(1, "12000.00", "2", "6000.00"), line(2, "13000.00")]
    assert check_bill_arithmetic(bill("25000.00", "4000.00", "21000.00"), lines) == []


def test_line_total_mismatch():
    [issue] = check_bill_arithmetic(bill(), [line(1, "1250.00", "3", "400.00")])
    assert issue.kind == "LINE_TOTAL"
    assert issue.expected == Decimal("1200.00")
    assert issue.difference == Decimal("50.00")
    assert "Arithmetic mismatch" in issue.explanation


def test_line_total_uses_explicit_rounding_only():
    # 3 x 33.335 = 100.005 -> 100.01 half-up; printed 100.01 is consistent.
    assert check_bill_arithmetic(bill(), [line(1, "100.01", "3", "33.335")]) == []


def test_bill_total_mismatch():
    issues = check_bill_arithmetic(bill("25000.00"), [line(1, "12000.00"), line(2, "12500.00")])
    [issue] = issues
    assert issue.kind == "BILL_TOTAL"
    assert issue.expected == Decimal("24500.00")
    assert issue.printed == Decimal("25000.00")


def test_balance_due_mismatch():
    [issue] = check_bill_arithmetic(bill("25000.00", "4000.00", "20000.00"), [line(1, "25000.00")])
    assert issue.kind == "BALANCE_DUE"
    assert issue.expected == Decimal("21000.00")


def test_missing_printed_values_are_not_guessed():
    # No printed total or quantity/unit: nothing to compare, so no issue is invented.
    assert check_bill_arithmetic(bill(), [line(1, "500.00")]) == []
