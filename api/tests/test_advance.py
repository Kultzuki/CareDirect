import uuid
from datetime import date
from decimal import Decimal

from app.reconciliation.advance import match_advance_payment
from app.reconciliation.views import BillView, PaymentView
from app.states import DataSource

BILL = BillView(
    id=uuid.uuid4(),
    provider_name="Synthetic City Hospital (Demo)",
    bill_date=date(2026, 11, 4),
    currency="INR",
    printed_total=Decimal("25000.00"),
    printed_advance_paid=Decimal("4000.00"),
    printed_balance_due=Decimal("21000.00"),
)


def pay(**kw):
    base = dict(
        id=uuid.uuid4(),
        amount=Decimal("4000.00"),
        currency="INR",
        paid_on=date(2026, 11, 1),
        reference="UPI-REF-1",
        payee_name="Synthetic City Hospital",
        source_type=DataSource.MANUAL_ENTRY,
        extraction_confidence=None,
    )
    base.update(kw)
    return PaymentView(**base)


def test_matching_receipt():
    r = match_advance_payment(pay(), BILL)
    assert r.matched, r.problems
    assert r.as_json()["label"].endswith("(not bank-verified)")


def test_amount_exceeding_printed_advance():
    r = match_advance_payment(pay(amount=Decimal("5000.00")), BILL)
    assert not r.matched
    assert any("exceeds" in p for p in r.problems)


def test_second_receipt_cannot_double_count_advance():
    r = match_advance_payment(pay(), BILL, already_matched_on_bill=Decimal("4000.00"))
    assert not r.matched


def test_partial_advance_split_across_two_receipts():
    first = match_advance_payment(pay(amount=Decimal("1500.00")), BILL)
    second = match_advance_payment(
        pay(amount=Decimal("2500.00")), BILL, already_matched_on_bill=Decimal("1500.00")
    )
    assert first.matched and second.matched


def test_currency_mismatch():
    assert not match_advance_payment(pay(currency="USD"), BILL).matched


def test_payment_after_bill_date():
    assert not match_advance_payment(pay(paid_on=date(2026, 11, 5)), BILL).matched


def test_missing_fields_are_problems_not_guesses():
    r = match_advance_payment(pay(paid_on=None, reference=None, payee_name=None), BILL)
    assert not r.matched
    assert len(r.problems) == 3
    assert all("not present in supplied evidence" in p for p in r.problems)


def test_payee_mismatch():
    assert not match_advance_payment(pay(payee_name="Some Other Clinic"), BILL).matched


def test_bill_without_printed_advance():
    b = BillView(**{**BILL.__dict__, "printed_advance_paid": None})
    assert not match_advance_payment(pay(), b).matched


def test_low_confidence_ai_extraction_needs_human_review():
    r = match_advance_payment(
        pay(source_type=DataSource.AI_EXTRACTED, extraction_confidence=Decimal("0.700")), BILL
    )
    assert not r.matched
    assert any("low confidence" in p for p in r.problems)
    ok = match_advance_payment(
        pay(source_type=DataSource.AI_EXTRACTED, extraction_confidence=Decimal("0.950")), BILL
    )
    assert ok.matched
