"""Invalid state transitions, at the table level and through services (DB-backed)."""

from datetime import date
from decimal import Decimal

import pytest

from app import services as svc
from app.errors import DomainError, InvalidTransition, ValidationFailed
from app.seed import seed
from app.states import (
    CASE_TRANSITIONS,
    EXTERNAL_PAYMENT_TRANSITIONS,
    FLAG_TRANSITIONS,
    LINE_ITEM_TRANSITIONS,
    CaseStatus,
    ExternalPaymentStatus,
    FlagStatus,
    LineItemStatus,
    PaymentMethod,
    ensure_transition,
)


@pytest.mark.parametrize(
    "table,current,target",
    [
        (CASE_TRANSITIONS, CaseStatus.DRAFT, CaseStatus.READY_FOR_APPROVAL),
        (CASE_TRANSITIONS, CaseStatus.DRAFT, CaseStatus.CLOSED),
        (CASE_TRANSITIONS, CaseStatus.CLOSED, CaseStatus.UNDER_REVIEW),
        (CASE_TRANSITIONS, CaseStatus.RECONCILIATION_REQUIRED, CaseStatus.READY_FOR_APPROVAL),
        (LINE_ITEM_TRANSITIONS, LineItemStatus.ACCEPTED, LineItemStatus.PENDING_REVIEW),
        (LINE_ITEM_TRANSITIONS, LineItemStatus.QUERIED, LineItemStatus.QUERIED),
        (LINE_ITEM_TRANSITIONS, LineItemStatus.ACCEPTED, LineItemStatus.ACCEPTED),
        (
            EXTERNAL_PAYMENT_TRANSITIONS,
            ExternalPaymentStatus.MATCHED,
            ExternalPaymentStatus.REJECTED,
        ),
        (
            EXTERNAL_PAYMENT_TRANSITIONS,
            ExternalPaymentStatus.REJECTED,
            ExternalPaymentStatus.MATCHED,
        ),
        (FLAG_TRANSITIONS, FlagStatus.RESOLVED, FlagStatus.PROVIDER_RESPONDED),
        (FLAG_TRANSITIONS, FlagStatus.DISMISSED, FlagStatus.RESOLVED),
        (FLAG_TRANSITIONS, FlagStatus.SUBMITTED_TO_PROVIDER, FlagStatus.DISMISSED),
    ],
)
def test_forbidden_transitions(table, current, target):
    with pytest.raises(InvalidTransition):
        ensure_transition("x", table, current, target)


def test_every_status_has_a_transition_entry():
    for table, enum in [
        (CASE_TRANSITIONS, CaseStatus),
        (LINE_ITEM_TRANSITIONS, LineItemStatus),
        (EXTERNAL_PAYMENT_TRANSITIONS, ExternalPaymentStatus),
        (FLAG_TRANSITIONS, FlagStatus),
    ]:
        assert set(table) == set(enum)


@pytest.fixture
def demo(db):
    case = seed(db)
    lines = {li.line_number: li for li in svc.case_lines(db, case.id)}
    payer = case.payer
    return case, lines, svc.Actor(user=payer, label="PAYER:demo")


def test_cannot_query_a_line_twice(db, demo):
    _, lines, actor = demo
    with pytest.raises(InvalidTransition):
        svc.query_line(db, actor, lines[4].id, "again")


def test_query_requires_reason(db, demo):
    _, lines, actor = demo
    with pytest.raises(ValidationFailed):
        svc.query_line(db, actor, lines[1].id, "   ")


def test_releasing_a_query_requires_note(db, demo):
    _, lines, actor = demo
    with pytest.raises(ValidationFailed):
        svc.accept_line(db, actor, lines[4].id, None)


def test_cannot_accept_accepted_line(db, demo):
    _, lines, actor = demo
    with pytest.raises(InvalidTransition):
        svc.accept_line(db, actor, lines[1].id, "again")


def test_matched_payment_cannot_be_reconciled_or_rejected(db, demo):
    case, _, actor = demo
    [p] = svc.case_payments(db, case.id)
    assert p.status == ExternalPaymentStatus.MATCHED
    with pytest.raises(DomainError):
        svc.reconcile_external_payment(db, actor, p.id)
    with pytest.raises(InvalidTransition):
        svc.reject_external_payment(db, actor, p.id, "changed my mind")


def test_flag_cannot_be_resolved_while_with_provider(db, demo):
    from app import providers

    case, lines, actor = demo
    [flag] = svc.case_flags(db, case.id)
    # Provider state cannot be asserted by a legacy status request.
    with pytest.raises(DomainError):
        svc.change_flag_status(db, actor, flag.id, FlagStatus.SUBMITTED_TO_PROVIDER, "sent")
    providers.create_link(db, actor, flag.id, lines[4].id, "Please clarify this charge.")
    with pytest.raises(DomainError):
        svc.change_flag_status(db, actor, flag.id, FlagStatus.RESOLVED, "skip provider")


def test_resolved_flag_requires_reason_to_reopen_and_retains_charge(db, demo):
    case, _, actor = demo
    [flag] = svc.case_flags(db, case.id)
    svc.change_flag_status(db, actor, flag.id, FlagStatus.RESOLVED, "provider confirmed")
    with pytest.raises(ValidationFailed):
        svc.change_flag_status(db, actor, flag.id, FlagStatus.OPEN, " ")
    svc.change_flag_status(
        db, actor, flag.id, FlagStatus.OPEN, "New supplied evidence needs review."
    )
    assert flag.status == FlagStatus.OPEN
    assert svc.get_buckets(db, case).queried == Decimal("2000.00")


def test_resolving_flag_does_not_change_charge(db, demo):
    case, lines, actor = demo
    [flag] = svc.case_flags(db, case.id)
    svc.change_flag_status(db, actor, flag.id, FlagStatus.RESOLVED, "provider confirmed duplicate")
    b = svc.get_buckets(db, case)
    # Still queried: resolving a question never silently removes or releases a charge.
    assert b.queried == Decimal("2000.00")
    assert b.bill_total == Decimal("25000.00")


def test_case_cannot_close_with_payable_amount(db, demo):
    case, _, actor = demo
    svc.transition_case(db, actor, case.id, CaseStatus.READY_FOR_APPROVAL)
    with pytest.raises(DomainError):
        svc.transition_case(db, actor, case.id, CaseStatus.CLOSED)


def test_case_cannot_jump_from_draft_to_ready(db, actor):
    case = svc.create_case(db, actor, patient_alias="P", currency="INR")
    db.commit()
    with pytest.raises(InvalidTransition):
        svc.transition_case(db, actor, case.id, CaseStatus.READY_FOR_APPROVAL)


def test_ready_for_approval_blocked_by_unreviewed_line(db, actor):
    case = svc.create_case(db, actor, patient_alias="P", currency="INR")
    svc.add_bill(
        db,
        actor,
        case.id,
        svc.BillInput(
            provider_name="H",
            currency="INR",
            lines=[svc.LineInput(1, "Consultation", Decimal("500.00"))],
        ),
    )
    with pytest.raises(DomainError, match="not yet reviewed"):
        svc.transition_case(db, actor, case.id, CaseStatus.READY_FOR_APPROVAL)


def test_ready_for_approval_blocked_by_unqueried_duplicate(db, actor):
    case = svc.create_case(db, actor, patient_alias="P", currency="INR")
    bill = svc.add_bill(
        db,
        actor,
        case.id,
        svc.BillInput(
            provider_name="H",
            currency="INR",
            lines=[
                svc.LineInput(
                    n,
                    "CBC",
                    Decimal("2000.00"),
                    date(2026, 11, 2),
                    quantity=Decimal("1"),
                    unit_price=Decimal("2000.00"),
                )
                for n in (1, 2)
            ],
        ),
    )
    svc.run_checks(db, actor, case.id)
    for li in bill.line_items:
        svc.accept_line(db, actor, li.id)
    with pytest.raises(DomainError, match="duplicate"):
        svc.transition_case(db, actor, case.id, CaseStatus.READY_FOR_APPROVAL)


def test_overpayment_moves_case_to_reconciliation_required(db, actor):
    case = svc.create_case(db, actor, patient_alias="P", currency="INR")
    bill = svc.add_bill(
        db,
        actor,
        case.id,
        svc.BillInput(
            provider_name="Hospital",
            currency="INR",
            bill_date=date(2026, 11, 4),
            printed_total=Decimal("1000.00"),
            printed_advance_paid=Decimal("1500.00"),
            lines=[svc.LineInput(1, "Consultation", Decimal("1000.00"))],
        ),
    )
    p = svc.record_external_payment(
        db,
        actor,
        case.id,
        svc.PaymentInput(
            method=PaymentMethod.UPI,
            amount=Decimal("1500.00"),
            currency="INR",
            paid_on=date(2026, 11, 1),
            reference="R",
            payee_name="Hospital",
            bill_id=bill.id,
        ),
    )
    svc.reconcile_external_payment(db, actor, p.id)
    db.refresh(case)
    assert case.status == CaseStatus.RECONCILIATION_REQUIRED
    assert not svc.get_buckets(db, case).consistent
    # Cannot return to review while the inconsistency remains.
    with pytest.raises(DomainError):
        svc.transition_case(db, actor, case.id, CaseStatus.UNDER_REVIEW)
