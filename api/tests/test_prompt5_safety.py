"""Financial and case-isolation regressions; synthetic evidence only."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import services as svc
from app.errors import DomainError
from app.states import CaseStatus, LedgerEntryType, PaymentMethod, UserRole


def make_bill(db, actor, *, duplicate=False):
    case = svc.create_case(db, actor, patient_alias="Synthetic safety case", currency="INR")
    amounts = ["1000.00", "1000.00"] if duplicate else ["10000.00"]
    bill = svc.add_bill(
        db,
        actor,
        case.id,
        svc.BillInput(
            provider_name="Synthetic Safety Clinic",
            currency="INR",
            bill_date=date(2026, 11, 9),
            printed_total=sum(map(Decimal, amounts)),
            printed_advance_paid=Decimal("4000.00"),
            lines=[
                svc.LineInput(
                    i,
                    "Consultation",
                    Decimal(amount),
                    date(2026, 11, 8),
                    quantity=Decimal("1"),
                    unit_price=Decimal(amount),
                )
                for i, amount in enumerate(amounts, 1)
            ],
        ),
    )
    return case, bill


def receipt(db, actor, case, bill, reference="SYNTHETIC-REF"):
    return svc.record_external_payment(
        db,
        actor,
        case.id,
        svc.PaymentInput(
            method=PaymentMethod.UPI,
            amount=Decimal("1000.00"),
            currency="INR",
            paid_on=date(2026, 11, 8),
            reference=reference,
            payee_name="Synthetic Safety Clinic",
            bill_id=bill.id,
        ),
    )


def test_duplicate_transaction_reference_needs_clarification_and_cannot_be_overridden(db, actor):
    case, bill = make_bill(db, actor)
    first = receipt(db, actor, case, bill)
    svc.reconcile_external_payment(db, actor, first.id)
    second = receipt(db, actor, case, bill, " synthetic-ref ")
    svc.reconcile_external_payment(db, actor, second.id)
    assert second.status == "NEEDS_CLARIFICATION"
    assert svc.get_buckets(db, case).already_paid == Decimal("1000.00")
    with pytest.raises(DomainError, match="already matched"):
        svc.confirm_external_payment(db, actor, second.id, "Same reference on another image")
    assert svc.get_buckets(db, case).consistent


def test_reconciliation_refreshes_state_changed_since_initial_read(db, actor):
    case, bill = make_bill(db, actor)
    stale_payment = receipt(db, actor, case, bill)
    # A different identity map commits while the first caller still retains SUBMITTED.
    with Session(
        bind=db.connection(), join_transaction_mode="create_savepoint", expire_on_commit=False
    ) as other:
        other_actor = svc.Actor(other.get(type(actor.user), actor.user_id), "synthetic-other-call")
        svc.reconcile_external_payment(other, other_actor, stale_payment.id)
    assert stale_payment.status == "SUBMITTED"
    with pytest.raises(DomainError, match="only SUBMITTED"):
        svc.reconcile_external_payment(db, actor, stale_payment.id)
    entries = [
        e for e in svc.case_ledger(db, case.id) if e.entry_type == LedgerEntryType.EXTERNAL_PAYMENT
    ]
    assert len(entries) == 1
    assert svc.get_buckets(db, case).consistent


def test_database_refuses_second_credit_for_same_receipt(db, actor):
    case, bill = make_bill(db, actor)
    payment = receipt(db, actor, case, bill)
    svc.reconcile_external_payment(db, actor, payment.id)
    with pytest.raises(IntegrityError), db.begin_nested():
        svc._ledger(
            db,
            actor,
            case,
            LedgerEntryType.EXTERNAL_PAYMENT,
            payment.amount,
            "Synthetic duplicate credit",
            external_payment_id=payment.id,
        )


def test_unrelated_relative_cannot_list_or_read_case(client, db, actor):
    case, _ = make_bill(db, actor)
    relative = svc.create_user(db, "Unrelated relative", UserRole.RELATIVE)
    headers = {"X-Demo-User-Id": str(relative.id)}
    assert client.get("/api/cases", headers=headers).json() == []
    assert client.get(f"/api/cases/{case.id}", headers=headers).status_code == 403
    assert client.post(f"/api/cases/{case.id}/run-checks", headers=headers).status_code == 403


def test_approval_cannot_skip_current_deterministic_checks(db, actor):
    case, bill = make_bill(db, actor, duplicate=True)
    for line in bill.line_items:
        svc.accept_line(db, actor, line.id)
    with pytest.raises(DomainError, match="run checks"):
        svc.transition_case(db, actor, case.id, CaseStatus.READY_FOR_APPROVAL)
    flags = svc.run_checks(db, actor, case.id)
    assert flags
    svc.query_line(db, actor, bill.line_items[1].id, "Clarify repeated consultation")
    svc.transition_case(db, actor, case.id, CaseStatus.READY_FOR_APPROVAL)
    approval = svc.record_approval(db, actor, case.id, Decimal("1000.00"), "Synthetic clinic")
    assert approval.approved_amount == Decimal("1000.00")
