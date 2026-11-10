import random
import uuid
from datetime import date
from decimal import Decimal

from app.reconciliation.buckets import compute_buckets
from app.reconciliation.views import LedgerView, LineView, PaymentView
from app.states import DataSource, ExternalPaymentStatus, LedgerEntryType, LineItemStatus

T = LedgerEntryType


def L(entry_type, amount, currency="INR"):
    return LedgerView(entry_type, Decimal(amount), currency)


def line(total, status):
    return LineView(
        id=uuid.uuid4(),
        line_number=1,
        description_raw="x",
        service_date=date(2026, 11, 2),
        quantity=None,
        unit_price=None,
        line_total=Decimal(total),
        currency="INR",
        status=status,
    )


def payment(amount, status=ExternalPaymentStatus.MATCHED):
    return PaymentView(
        id=uuid.uuid4(),
        amount=Decimal(amount),
        currency="INR",
        paid_on=None,
        reference=None,
        payee_name=None,
        source_type=DataSource.MANUAL_ENTRY,
        extraction_confidence=None,
        status=status,
    )


def seed_like():
    lines = [
        line("12000.00", LineItemStatus.ACCEPTED),
        line("3000.00", LineItemStatus.ACCEPTED),
        line("2000.00", LineItemStatus.ACCEPTED),
        line("2000.00", LineItemStatus.QUERIED),
        line("4500.00", LineItemStatus.ACCEPTED),
        line("1500.00", LineItemStatus.ACCEPTED),
    ]
    ledger = [L(T.BILL_CHARGE, li.line_total) for li in lines]
    ledger += [L(T.QUERY_HOLD, "2000.00"), L(T.EXTERNAL_PAYMENT, "4000.00")]
    return ledger, lines, [payment("4000.00")]


def test_seed_case_buckets():
    b = compute_buckets("INR", *seed_like())
    assert (b.bill_total, b.payable_now, b.queried, b.already_paid) == (
        Decimal("25000.00"),
        Decimal("19000.00"),
        Decimal("2000.00"),
        Decimal("4000.00"),
    )
    assert b.bill_total == b.payable_now + b.queried + b.already_paid
    assert b.consistent and b.issues == ()
    assert b.pending_review == Decimal("0.00")


def test_queried_charge_stays_in_bill_total():
    ledger, lines, payments = seed_like()
    b = compute_buckets("INR", ledger, lines, payments)
    assert b.bill_total == Decimal("25000.00")  # not 23000: the query does not remove it


def test_query_release_returns_amount_to_payable():
    ledger, lines, payments = seed_like()
    lines[3] = LineView(**{**lines[3].__dict__, "status": LineItemStatus.ACCEPTED})
    b = compute_buckets("INR", ledger + [L(T.QUERY_RELEASE, "2000.00")], lines, payments)
    assert (b.payable_now, b.queried) == (Decimal("21000.00"), Decimal("0.00"))
    assert b.consistent


def test_unmatched_payment_is_not_already_paid():
    ledger, lines, _ = seed_like()
    ledger = [e for e in ledger if e.entry_type != T.EXTERNAL_PAYMENT]
    b = compute_buckets("INR", ledger, lines, [payment("4000.00", ExternalPaymentStatus.SUBMITTED)])
    assert b.already_paid == Decimal("0.00")
    assert b.payable_now == Decimal("23000.00")
    assert b.consistent


def test_overpayment_is_reported_not_hidden():
    lines = [line("1000.00", LineItemStatus.ACCEPTED)]
    ledger = [L(T.BILL_CHARGE, "1000.00"), L(T.EXTERNAL_PAYMENT, "1500.00")]
    b = compute_buckets("INR", ledger, lines, [payment("1500.00")])
    assert b.payable_now == Decimal("-500.00")
    assert b.invariant_holds  # arithmetic identity still holds
    assert not b.consistent
    assert any("exceeds the bill total" in i for i in b.issues)


def test_ledger_state_disagreement_is_reported():
    ledger, lines, payments = seed_like()
    # Ledger says queried, but no line is in QUERIED state.
    lines[3] = LineView(**{**lines[3].__dict__, "status": LineItemStatus.ACCEPTED})
    b = compute_buckets("INR", ledger, lines, payments)
    assert not b.consistent
    assert any("queried" in i for i in b.issues)


def test_mixed_currency_is_reported():
    ledger, lines, payments = seed_like()
    b = compute_buckets("INR", ledger + [L(T.BILL_CHARGE, "10.00", "USD")], lines, payments)
    assert not b.consistent
    assert any("currencies must not mix" in i for i in b.issues)


def test_empty_case():
    b = compute_buckets("INR", [], [], [])
    assert b.bill_total == b.payable_now == b.queried == b.already_paid == Decimal("0")
    assert b.consistent


def test_invariant_holds_for_random_cases():
    rng = random.Random(20261108)
    for _ in range(500):
        lines, ledger = [], []
        for _ in range(rng.randint(1, 12)):
            total = Decimal(rng.randint(1, 5_000_000)) / 100
            status = rng.choice(list(LineItemStatus))
            lines.append(line(str(total), status))
            ledger.append(L(T.BILL_CHARGE, total))
            if status == LineItemStatus.QUERIED:
                ledger.append(L(T.QUERY_HOLD, total))
        payable_before = sum(
            (li.line_total for li in lines if li.status != LineItemStatus.QUERIED), Decimal(0)
        )
        payments = []
        if payable_before > 0 and rng.random() < 0.7:
            paid = (payable_before * Decimal(rng.randint(0, 100)) / 100).quantize(Decimal("0.01"))
            if paid > 0:
                payments.append(payment(str(paid)))
                ledger.append(L(T.EXTERNAL_PAYMENT, paid))
        b = compute_buckets("INR", ledger, lines, payments)
        assert b.bill_total == b.payable_now + b.queried + b.already_paid
        assert b.bill_total == sum((li.line_total for li in lines), Decimal(0))
        assert b.payable_now >= 0
        assert b.consistent, b.issues
