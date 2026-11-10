"""Business operations. Every state change is audited; every financial change
writes an append-only ledger entry plus an audit event in the same transaction.

No function here creates, sends or executes a payment. There is no PayPal code
in this slice.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import DomainError, Forbidden, NotFound, ValidationFailed
from app.models import (
    ApprovalRecord,
    AuditEvent,
    Bill,
    BillingFlag,
    BillLineItem,
    CareCase,
    ExternalPayment,
    LedgerEntry,
    PaymentOperation,
    PayPalPaymentRef,
    User,
)
from app.money import ZERO, money, quantity, to_str
from app.reconciliation import advance
from app.reconciliation.buckets import Buckets, compute_buckets
from app.reconciliation.checks import collect_flags
from app.reconciliation.views import BillView, LedgerView, LineView, PaymentView
from app.states import (
    CASE_TRANSITIONS,
    EXTERNAL_PAYMENT_TRANSITIONS,
    FLAG_TRANSITIONS,
    LINE_ITEM_TRANSITIONS,
    CaseStatus,
    DataSource,
    ExternalPaymentStatus,
    FlagStatus,
    FlagType,
    LedgerEntryType,
    LineItemStatus,
    PaymentMethod,
    UserRole,
    ensure_transition,
)


@dataclass(frozen=True)
class Actor:
    user: User | None
    label: str

    @property
    def user_id(self) -> uuid.UUID | None:
        return self.user.id if self.user else None


SYSTEM = Actor(user=None, label="system")


# ---------------------------------------------------------------- input DTOs


@dataclass(frozen=True)
class LineInput:
    line_number: int
    description_raw: str
    line_total: Decimal
    service_date: date | None = None
    quantity: Decimal | None = None
    unit_price: Decimal | None = None
    extraction_confidence: Decimal | None = None
    source_page: int | None = None
    source_text: str | None = None
    code: str | None = None


@dataclass(frozen=True)
class BillInput:
    provider_name: str
    currency: str
    lines: Sequence[LineInput]
    bill_number: str | None = None
    bill_date: date | None = None
    printed_total: Decimal | None = None
    printed_advance_paid: Decimal | None = None
    printed_balance_due: Decimal | None = None
    source_document_ref: str | None = None


@dataclass(frozen=True)
class PaymentInput:
    method: PaymentMethod
    amount: Decimal
    currency: str
    paid_on: date | None = None
    reference: str | None = None
    payee_name: str | None = None
    bill_id: uuid.UUID | None = None
    extraction_confidence: Decimal | None = None
    source_document_ref: str | None = None


# ---------------------------------------------------------------- helpers


def _now() -> datetime:
    return datetime.now(UTC)


def _audit(
    db: Session,
    actor: Actor,
    *,
    case_id: uuid.UUID | None,
    event_type: str,
    entity_type: str,
    entity_id: uuid.UUID | None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    details: dict[str, Any] | None = None,
    ledger_entry: LedgerEntry | None = None,
) -> AuditEvent:
    ev = AuditEvent(
        id=uuid.uuid4(),
        case_id=case_id,
        actor_user_id=actor.user_id,
        actor_label=actor.label,
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        ledger_entry_id=ledger_entry.id if ledger_entry else None,
        before=before,
        after=after,
        details=details or {},
    )
    db.add(ev)
    if case_id is not None:
        from app.family import notify

        case = db.get(CareCase, case_id)
        if case is not None:
            notify(db, ev, case, actor)
    return ev


def _ledger(
    db: Session,
    actor: Actor,
    case: CareCase,
    entry_type: LedgerEntryType,
    amount: Decimal,
    reason: str,
    *,
    bill_id: uuid.UUID | None = None,
    line_item_id: uuid.UUID | None = None,
    external_payment_id: uuid.UUID | None = None,
    flag_id: uuid.UUID | None = None,
    provider_decision_id: uuid.UUID | None = None,
) -> LedgerEntry:
    """Append one ledger entry and its audit event. The only way ledger rows are written."""
    amount = money(amount)
    if amount <= 0:
        raise DomainError("ledger amounts must be positive; direction comes from entry type")
    entry = LedgerEntry(
        id=uuid.uuid4(),
        case_id=case.id,
        entry_type=entry_type,
        amount=amount,
        currency=case.currency,
        bill_id=bill_id,
        line_item_id=line_item_id,
        external_payment_id=external_payment_id,
        flag_id=flag_id,
        provider_decision_id=provider_decision_id,
        reason=reason,
        created_by=actor.user_id,
        actor_label=actor.label,
    )
    db.add(entry)
    db.flush()
    _audit(
        db,
        actor,
        case_id=case.id,
        event_type="LEDGER_ENTRY_APPENDED",
        entity_type="ledger_entry",
        entity_id=entry.id,
        ledger_entry=entry,
        details={
            "entry_type": str(entry_type),
            "amount": to_str(amount),
            "currency": case.currency,
            "reason": reason,
        },
    )
    return entry


def _lock_case(db: Session, case_id: uuid.UUID) -> CareCase:
    case = db.execute(
        select(CareCase)
        .where(CareCase.id == case_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if case is None:
        raise NotFound(f"case {case_id} not found")
    if db.scalar(select(PaymentOperation.id).where(PaymentOperation.case_id == case_id)):
        raise DomainError(
            "This case is frozen while a Sandbox invoice attempt exists. "
            "Verify the payment or start a fresh demo case."
        )
    return case


def _require_payer(case: CareCase, actor: Actor) -> None:
    if actor.user is None:
        raise Forbidden("this action requires an authenticated user")
    if actor.user.role == UserRole.ADMIN:
        return
    if actor.user.id != case.payer_user_id:
        raise Forbidden("only the case payer may perform this action")


def _require_case_member(case: CareCase, actor: Actor) -> None:
    from app.family import require

    require(case, actor, "can_view")


def _require_reviewer(case: CareCase, actor: Actor) -> None:
    from app.family import require

    require(case, actor, "can_review")


def _require_payment_approver(case: CareCase, actor: Actor) -> None:
    from app.family import require

    require(case, actor, "can_approve")


def _require_note(note: str | None, what: str) -> str:
    if note is None or not note.strip():
        raise ValidationFailed(f"{what} is required")
    return note.strip()


def _line_view(li: BillLineItem) -> LineView:
    return LineView(
        id=li.id,
        line_number=li.line_number,
        description_raw=li.description_raw,
        service_date=li.service_date,
        quantity=li.quantity,
        unit_price=li.unit_price,
        line_total=li.line_total,
        currency=li.currency,
        status=li.status,
        code=li.code,
    )


def _bill_view(b: Bill) -> BillView:
    return BillView(
        id=b.id,
        provider_name=b.provider_name,
        bill_date=b.bill_date,
        currency=b.currency,
        printed_total=b.printed_total,
        printed_advance_paid=b.printed_advance_paid,
        printed_balance_due=b.printed_balance_due,
    )


def _payment_view(p: ExternalPayment) -> PaymentView:
    return PaymentView(
        id=p.id,
        amount=p.amount,
        currency=p.currency,
        paid_on=p.paid_on,
        reference=p.reference,
        payee_name=p.payee_name,
        source_type=p.source_type,
        extraction_confidence=p.extraction_confidence,
        status=p.status,
    )


# ---------------------------------------------------------------- users & cases


def create_user(
    db: Session, display_name: str, role: UserRole, email: str | None = None, is_demo: bool = False
) -> User:
    user = User(display_name=display_name, role=role, email=email, is_demo=is_demo)
    db.add(user)
    db.flush()
    _audit(
        db,
        SYSTEM,
        case_id=None,
        event_type="USER_CREATED",
        entity_type="user",
        entity_id=user.id,
        after={"role": str(role), "is_demo": is_demo},
    )
    return user


def create_case(
    db: Session,
    actor: Actor,
    *,
    patient_alias: str,
    currency: str,
    case_reference: str | None = None,
    episode_title: str | None = None,
    clinical_context: str | None = None,
    is_demo: bool = False,
) -> CareCase:
    if actor.user is None or actor.user.role not in (UserRole.PAYER, UserRole.ADMIN):
        raise Forbidden("only a payer may create a case")
    currency = currency.upper()
    if len(currency) != 3 or not currency.isalpha():
        raise ValidationFailed("currency must be an ISO 4217 code")
    case = CareCase(
        case_reference=case_reference or f"CD-{uuid.uuid4().hex[:8].upper()}",
        patient_alias=patient_alias,
        episode_title=episode_title,
        clinical_context=clinical_context,
        payer_user_id=actor.user.id,
        currency=currency,
        status=CaseStatus.DRAFT,
        is_demo=is_demo,
    )
    db.add(case)
    db.flush()
    _audit(
        db,
        actor,
        case_id=case.id,
        event_type="CASE_CREATED",
        entity_type="care_case",
        entity_id=case.id,
        after={"status": str(case.status), "currency": currency, "is_demo": is_demo},
    )
    return case


def _set_case_status(db: Session, actor: Actor, case: CareCase, target: CaseStatus, why: str):
    ensure_transition("case", CASE_TRANSITIONS, case.status, target)
    before = str(case.status)
    case.status = target
    _audit(
        db,
        actor,
        case_id=case.id,
        event_type="CASE_STATUS_CHANGED",
        entity_type="care_case",
        entity_id=case.id,
        before={"status": before},
        after={"status": str(target)},
        details={"reason": why},
    )


def transition_case(db: Session, actor: Actor, case_id: uuid.UUID, target: CaseStatus) -> CareCase:
    case = _lock_case(db, case_id)
    _require_reviewer(case, actor)
    ensure_transition("case", CASE_TRANSITIONS, case.status, target)
    blockers = approval_blockers(db, case) if target == CaseStatus.READY_FOR_APPROVAL else []
    if target == CaseStatus.CLOSED:
        b = get_buckets(db, case)
        if b.payable_now != ZERO or b.queried != ZERO:
            blockers.append("Case still has payable or queried amounts.")
    if target == CaseStatus.UNDER_REVIEW and case.status == CaseStatus.RECONCILIATION_REQUIRED:
        b = get_buckets(db, case)
        if not b.consistent:
            blockers.extend(b.issues)
    if blockers:
        raise DomainError("cannot move case to " + str(target) + ": " + " ".join(blockers))
    _set_case_status(db, actor, case, target, "requested by payer")
    db.commit()
    return case


def approval_blockers(db: Session, case: CareCase) -> list[str]:
    """Reasons the payable amount cannot yet be put up for human approval."""
    blockers: list[str] = []
    from app.insurance import has_insurance

    if has_insurance(db, case.id):
        blockers.append(
            "This episode includes insurer funding. Review Insurance and TPA reconciliation; "
            "gross-bill collection is blocked because it includes insurer or unresolved amounts."
        )
    b = get_buckets(db, case)
    if not b.consistent:
        blockers.extend(b.issues)
    if b.pending_review > ZERO:
        blockers.append(f"{to_str(b.pending_review)} of charges not yet reviewed by the payer.")
    if b.payable_now <= ZERO:
        blockers.append("Nothing is payable.")
    open_payments = db.scalar(
        select(func.count())
        .select_from(ExternalPayment)
        .where(
            ExternalPayment.case_id == case.id,
            ExternalPayment.status.in_(
                [ExternalPaymentStatus.SUBMITTED, ExternalPaymentStatus.NEEDS_CLARIFICATION]
            ),
        )
    )
    if open_payments:
        blockers.append("External payment evidence awaits reconciliation.")
    # An open flag is fine only if every line it covers is held in the queried bucket.
    lines = {li.id: li for li in _case_lines(db, case.id)}
    current_candidates = collect_flags(db, case)
    current_keys = {f.dedupe_key for f in current_candidates}
    stored_flags = _case_flags(db, case.id)
    known_keys = {f.dedupe_key for f in stored_flags}
    if any(f.dedupe_key not in known_keys for f in current_candidates):
        blockers.append("Billing checks found questions not yet reviewed; run checks first.")
    for flag in stored_flags:
        if (
            flag.flag_type
            in (
                FlagType.ESTIMATE_DRIFT,
                FlagType.CROSS_DOCUMENT_OVERLAP,
                FlagType.POSSIBLE_NEAR_DUPLICATE,
            )
            and flag.dedupe_key not in current_keys
        ):
            continue
        if flag.status not in (
            FlagStatus.OPEN,
            FlagStatus.SUBMITTED_TO_PROVIDER,
            FlagStatus.PROVIDER_RESPONDED,
        ):
            continue
        if flag.flag_type == FlagType.ADVANCE_PAYMENT_MISMATCH:
            blockers.append("An advance-payment question is unresolved.")
            continue
        flagged = [lines[uuid.UUID(i)] for i in flag.line_item_ids if uuid.UUID(i) in lines]
        if flag.flag_type == FlagType.POSSIBLE_EXACT_DUPLICATE:
            repeats = flagged[1:]  # first occurrence may stay payable
            if any(li.status != LineItemStatus.QUERIED for li in repeats):
                blockers.append("A possible duplicate is neither queried nor resolved.")
        elif not flagged or any(li.status != LineItemStatus.QUERIED for li in flagged):
            blockers.append(
                "An episode overlap question is unresolved."
                if flag.flag_type
                in (FlagType.CROSS_DOCUMENT_OVERLAP, FlagType.POSSIBLE_NEAR_DUPLICATE)
                else "An arithmetic question is unresolved."
            )
    return blockers


def record_approval(
    db: Session,
    actor: Actor,
    case_id: uuid.UUID,
    amount: Decimal,
    payee_label: str,
    provider_merchant_ref: str | None = None,
    note: str | None = None,
) -> ApprovalRecord:
    """Record the payer's approval of exactly the payable_now amount, with the bucket
    snapshot shown at approval time. This creates no invoice and moves no money."""
    case = _lock_case(db, case_id)
    _require_payment_approver(case, actor)
    if case.status != CaseStatus.READY_FOR_APPROVAL:
        raise DomainError(f"a case in {case.status} cannot be approved")
    payee_label = _require_note(payee_label, "the payee shown at approval")
    amount = money(amount)
    blockers = approval_blockers(db, case)
    if blockers:
        raise DomainError("cannot approve: " + " ".join(blockers))
    b = get_buckets(db, case)
    if amount != b.payable_now:
        raise ValidationFailed(
            f"approved amount {to_str(amount)} must equal payable now {to_str(b.payable_now)}"
        )
    ledger_seq = db.scalar(select(func.max(LedgerEntry.seq)).where(LedgerEntry.case_id == case.id))
    already = db.scalar(
        select(func.count())
        .select_from(ApprovalRecord)
        .where(ApprovalRecord.case_id == case.id, ApprovalRecord.ledger_seq == ledger_seq)
    )
    if already:
        raise DomainError("these figures are already approved; nothing changed since then")
    approval = ApprovalRecord(
        id=uuid.uuid4(),
        case_id=case.id,
        approved_by=actor.user_id,
        actor_label=actor.label,
        currency=case.currency,
        approved_amount=amount,
        bill_total=b.bill_total,
        payable_now=b.payable_now,
        queried=b.queried,
        already_paid=b.already_paid,
        payee_label=payee_label,
        provider_merchant_ref=provider_merchant_ref,
        ledger_seq=ledger_seq,
        note=note,
    )
    db.add(approval)
    db.flush()
    _audit(
        db,
        actor,
        case_id=case.id,
        event_type="PAYMENT_APPROVED",
        entity_type="approval_record",
        entity_id=approval.id,
        after={
            "approved_amount": to_str(amount),
            "currency": case.currency,
            "bill_total": to_str(b.bill_total),
            "payable_now": to_str(b.payable_now),
            "queried": to_str(b.queried),
            "already_paid": to_str(b.already_paid),
            "payee_label": payee_label,
            "ledger_seq": ledger_seq,
        },
    )
    db.commit()
    return approval


def case_approvals(db: Session, case_id: uuid.UUID) -> list[ApprovalRecord]:
    return list(
        db.scalars(
            select(ApprovalRecord)
            .where(ApprovalRecord.case_id == case_id)
            .order_by(ApprovalRecord.created_at)
        )
    )


# ---------------------------------------------------------------- bills


def add_bill(
    db: Session,
    actor: Actor,
    case_id: uuid.UUID,
    data: BillInput,
    source_type: DataSource = DataSource.MANUAL_ENTRY,
) -> Bill:
    case = _lock_case(db, case_id)
    _require_reviewer(case, actor)
    if case.status not in (CaseStatus.DRAFT, CaseStatus.UNDER_REVIEW):
        raise DomainError(f"bills cannot be added to a case in {case.status}")
    if data.currency.upper() != case.currency:
        raise ValidationFailed(f"bill currency {data.currency} differs from case {case.currency}")
    if not data.lines:
        raise ValidationFailed("a bill needs at least one line item")
    numbers = [ln.line_number for ln in data.lines]
    if len(set(numbers)) != len(numbers):
        raise ValidationFailed("line numbers must be unique within a bill")

    bill = Bill(
        id=uuid.uuid4(),
        case_id=case.id,
        provider_name=data.provider_name,
        bill_number=data.bill_number,
        bill_date=data.bill_date,
        currency=case.currency,
        printed_total=None if data.printed_total is None else money(data.printed_total),
        printed_advance_paid=(
            None if data.printed_advance_paid is None else money(data.printed_advance_paid)
        ),
        printed_balance_due=(
            None if data.printed_balance_due is None else money(data.printed_balance_due)
        ),
        source_type=source_type,
        source_document_ref=data.source_document_ref,
        created_by=actor.user_id,
    )
    db.add(bill)
    db.flush()
    _audit(
        db,
        actor,
        case_id=case.id,
        event_type="BILL_RECORDED",
        entity_type="bill",
        entity_id=bill.id,
        after={
            "provider_name": bill.provider_name,
            "printed_total": None if bill.printed_total is None else to_str(bill.printed_total),
            "line_count": len(data.lines),
            "source_type": str(source_type),
        },
    )
    for ln in data.lines:
        total = money(ln.line_total)
        if total <= ZERO:
            raise ValidationFailed(
                f"line {ln.line_number}: only positive charges are supported in this slice"
            )
        item = BillLineItem(
            id=uuid.uuid4(),
            bill_id=bill.id,
            case_id=case.id,
            line_number=ln.line_number,
            description_raw=ln.description_raw,
            code=ln.code,
            service_date=ln.service_date,
            quantity=None if ln.quantity is None else quantity(ln.quantity),
            unit_price=None if ln.unit_price is None else money(ln.unit_price),
            line_total=total,
            currency=case.currency,
            source_type=source_type,
            extraction_confidence=ln.extraction_confidence,
            source_page=ln.source_page,
            source_text=ln.source_text,
            status=LineItemStatus.PENDING_REVIEW,
        )
        db.add(item)
        db.flush()
        _ledger(
            db,
            actor,
            case,
            LedgerEntryType.BILL_CHARGE,
            total,
            f"Bill line {ln.line_number} as supplied",
            bill_id=bill.id,
            line_item_id=item.id,
        )
    if case.status == CaseStatus.DRAFT:
        _set_case_status(db, actor, case, CaseStatus.UNDER_REVIEW, "first bill recorded")
    _check_invariants(db, actor, case)
    db.commit()
    db.refresh(bill)
    return bill


# ---------------------------------------------------------------- deterministic checks


def run_checks(db: Session, actor: Actor, case_id: uuid.UUID) -> list[BillingFlag]:
    """Run duplicate and arithmetic checks. Idempotent: existing flags are not recreated.
    Flags never alter line items or the ledger."""
    case = _lock_case(db, case_id)
    _require_reviewer(case, actor)
    existing = {f.dedupe_key for f in _case_flags(db, case.id)}
    created: list[BillingFlag] = []

    created = [flag for flag in collect_flags(db, case) if flag.dedupe_key not in existing]

    for flag in created:
        db.add(flag)
        db.flush()
        _audit(
            db,
            actor,
            case_id=case.id,
            event_type="FLAG_CREATED",
            entity_type="billing_flag",
            entity_id=flag.id,
            after={"flag_type": str(flag.flag_type), "status": str(flag.status)},
            details={"rule_id": flag.rule_id, "rule_version": flag.rule_version},
        )
    _audit(
        db,
        actor,
        case_id=case.id,
        event_type="CHECKS_RUN",
        entity_type="care_case",
        entity_id=case.id,
        details={"flags_created": len(created)},
    )
    db.commit()
    return created


# ---------------------------------------------------------------- line items


def _get_line(db: Session, line_id: uuid.UUID) -> BillLineItem:
    li = db.get(BillLineItem, line_id)
    if li is None:
        raise NotFound(f"line item {line_id} not found")
    return li


def query_line(
    db: Session, actor: Actor, line_id: uuid.UUID, reason: str, flag_id: uuid.UUID | None = None
) -> BillLineItem:
    """Hold a charge for clarification. The charge stays on the bill and in the ledger;
    it moves from Payable to Queried."""
    reason = _require_note(reason, "a reason for the query")
    case_id = _get_line(db, line_id).case_id
    case = _lock_case(db, case_id)
    _require_reviewer(case, actor)
    li = db.get(BillLineItem, line_id, with_for_update=True, populate_existing=True)
    from app.providers import has_pending_workflow, recognized_amount

    if has_pending_workflow(db, li.id):
        raise DomainError(
            "review or revoke the existing provider workflow before changing this line"
        )
    amount = recognized_amount(db, li)
    if amount <= ZERO:
        raise DomainError("a fully credited line has no amount to hold")
    ensure_transition("line item", LINE_ITEM_TRANSITIONS, li.status, LineItemStatus.QUERIED)
    if flag_id is not None:
        flag = db.get(BillingFlag, flag_id, populate_existing=True)
        if flag is None or flag.case_id != case.id or str(li.id) not in flag.line_item_ids:
            raise ValidationFailed("flag does not belong to this line item")
        if flag.status in (FlagStatus.RESOLVED, FlagStatus.DISMISSED):
            _set_flag_status(db, actor, flag, FlagStatus.OPEN, "Payer reopened question: " + reason)
    before = str(li.status)
    li.status = LineItemStatus.QUERIED
    li.status_note = reason
    _audit(
        db,
        actor,
        case_id=case.id,
        event_type="LINE_ITEM_QUERIED",
        entity_type="bill_line_item",
        entity_id=li.id,
        before={"status": before},
        after={"status": str(li.status)},
        details={"reason": reason, "flag_id": str(flag_id) if flag_id else None},
    )
    _ledger(
        db,
        actor,
        case,
        LedgerEntryType.QUERY_HOLD,
        amount,
        f"Line {li.line_number} held for clarification: {reason}",
        bill_id=li.bill_id,
        line_item_id=li.id,
        flag_id=flag_id,
    )
    _check_invariants(db, actor, case)
    db.commit()
    return li


def accept_line(db: Session, actor: Actor, line_id: uuid.UUID, note: str | None = None):
    """Payer accepts a charge as payable. Releasing a query needs a written note."""
    case_id = _get_line(db, line_id).case_id
    case = _lock_case(db, case_id)
    _require_reviewer(case, actor)
    li = db.get(BillLineItem, line_id, with_for_update=True, populate_existing=True)
    from app.providers import has_pending_workflow, recognized_amount

    if has_pending_workflow(db, li.id):
        raise DomainError("review the provider response through its explicit payer decision")
    ensure_transition("line item", LINE_ITEM_TRANSITIONS, li.status, LineItemStatus.ACCEPTED)
    was_queried = li.status == LineItemStatus.QUERIED
    if was_queried:
        note = _require_note(note, "a note explaining why the query is released")
    before = str(li.status)
    li.status = LineItemStatus.ACCEPTED
    li.status_note = note
    _audit(
        db,
        actor,
        case_id=case.id,
        event_type="LINE_ITEM_ACCEPTED",
        entity_type="bill_line_item",
        entity_id=li.id,
        before={"status": before},
        after={"status": str(li.status)},
        details={"note": note},
    )
    if was_queried:
        _ledger(
            db,
            actor,
            case,
            LedgerEntryType.QUERY_RELEASE,
            recognized_amount(db, li),
            f"Line {li.line_number} query released: {note}",
            bill_id=li.bill_id,
            line_item_id=li.id,
        )
    _check_invariants(db, actor, case)
    db.commit()
    return li


# ---------------------------------------------------------------- external payments


def record_external_payment(
    db: Session,
    actor: Actor,
    case_id: uuid.UUID,
    data: PaymentInput,
    source_type: DataSource = DataSource.MANUAL_ENTRY,
) -> ExternalPayment:
    """Record payment evidence. It does not count as paid until reconciled."""
    case = _lock_case(db, case_id)
    _require_reviewer(case, actor)
    amount = money(data.amount)
    if amount <= ZERO:
        raise ValidationFailed("payment amount must be positive")
    if data.bill_id is not None:
        bill = db.get(Bill, data.bill_id)
        if bill is None or bill.case_id != case.id:
            raise ValidationFailed("bill does not belong to this case")
    p = ExternalPayment(
        id=uuid.uuid4(),
        case_id=case.id,
        bill_id=data.bill_id,
        method=data.method,
        amount=amount,
        currency=data.currency.upper(),
        paid_on=data.paid_on,
        reference=data.reference,
        payee_name=data.payee_name,
        source_type=source_type,
        extraction_confidence=data.extraction_confidence,
        source_document_ref=data.source_document_ref,
        status=ExternalPaymentStatus.SUBMITTED,
        created_by=actor.user_id,
    )
    db.add(p)
    db.flush()
    _audit(
        db,
        actor,
        case_id=case.id,
        event_type="EXTERNAL_PAYMENT_RECORDED",
        entity_type="external_payment",
        entity_id=p.id,
        after={
            "status": str(p.status),
            "amount": to_str(amount),
            "currency": p.currency,
            "method": str(p.method),
            "source_type": str(source_type),
        },
    )
    db.commit()
    return p


def _payment_bill(db: Session, case: CareCase, p: ExternalPayment) -> Bill | None:
    if p.bill_id is not None:
        return db.get(Bill, p.bill_id)
    bills = db.scalars(select(Bill).where(Bill.case_id == case.id)).all()
    return bills[0] if len(bills) == 1 else None


def _matched_bill_id(p: ExternalPayment) -> uuid.UUID | None:
    if p.bill_id is not None:
        return p.bill_id
    inferred = (p.match_basis or {}).get("bill_id")
    return uuid.UUID(inferred) if inferred else None


def _matched_on_bill(db: Session, case: CareCase, bill_id: uuid.UUID, exclude: uuid.UUID):
    return sum(
        (
            p.amount
            for p in case_payments(db, case.id)
            if p.id != exclude
            and p.status == ExternalPaymentStatus.MATCHED
            and _matched_bill_id(p) == bill_id
        ),
        ZERO,
    )


def _duplicate_matched_reference(db: Session, case: CareCase, payment: ExternalPayment) -> bool:
    """Same-case, same-method transaction references identify one payment, not two receipts.

    This conservative check does not establish authenticity or bank verification.
    """
    reference = (payment.reference or "").strip().casefold()
    if not reference:
        return False
    return any(
        p.id != payment.id
        and p.status == ExternalPaymentStatus.MATCHED
        and p.method == payment.method
        and p.currency == payment.currency
        and (p.reference or "").strip().casefold() == reference
        for p in case_payments(db, case.id)
    )


def _mark_matched(db: Session, actor: Actor, case: CareCase, p: ExternalPayment, basis: dict):
    if _duplicate_matched_reference(db, case, p):
        raise DomainError("transaction reference is already matched; reject duplicate evidence")
    before = str(p.status)
    ensure_transition(
        "external payment", EXTERNAL_PAYMENT_TRANSITIONS, p.status, ExternalPaymentStatus.MATCHED
    )
    p.status = ExternalPaymentStatus.MATCHED
    p.match_basis = basis
    _audit(
        db,
        actor,
        case_id=case.id,
        event_type="EXTERNAL_PAYMENT_MATCHED",
        entity_type="external_payment",
        entity_id=p.id,
        before={"status": before},
        after={"status": str(p.status)},
        details=basis,
    )
    _ledger(
        db,
        actor,
        case,
        LedgerEntryType.EXTERNAL_PAYMENT,
        p.amount,
        f"{p.method} payment evidence reconciled to bill",
        bill_id=_matched_bill_id(p),
        external_payment_id=p.id,
    )


def reconcile_external_payment(db: Session, actor: Actor, payment_id: uuid.UUID):
    p0 = db.get(ExternalPayment, payment_id)
    if p0 is None:
        raise NotFound(f"external payment {payment_id} not found")
    case = _lock_case(db, p0.case_id)
    _require_reviewer(case, actor)
    p = db.get(ExternalPayment, payment_id, with_for_update=True, populate_existing=True)
    if p.status != ExternalPaymentStatus.SUBMITTED:
        raise DomainError(f"external payment is {p.status}; only SUBMITTED can be reconciled")

    bill = _payment_bill(db, case, p)
    if bill is None:
        result = advance.MatchResult(
            matched=False, problems=["Payment is not linked to a single bill on this case."]
        )
    else:
        result = advance.match_advance_payment(
            _payment_view(p), _bill_view(bill), _matched_on_bill(db, case, bill.id, p.id)
        )
    if _duplicate_matched_reference(db, case, p):
        result = advance.MatchResult(
            matched=False,
            basis=result.basis,
            problems=[*result.problems, "Transaction reference is already matched on this case."],
        )
    basis = result.as_json()
    basis.update(
        {
            "sources": [
                {"source_document_ref": p.source_document_ref},
                {"source_document_ref": bill.source_document_ref if bill else None},
            ],
            "confidence": (
                None if p.extraction_confidence is None else format(p.extraction_confidence, "f")
            ),
            "limitations": [
                "Matches supplied evidence only; not bank verified.",
                "Missing evidence is not inferred.",
            ],
        }
    )
    if bill is not None:
        # p.bill_id is immutable evidence; an inferred bill link is recorded here instead.
        basis["bill_id"] = str(bill.id)
        basis["bill_link"] = "supplied" if p.bill_id else "inferred (only bill on case)"

    if result.matched:
        _mark_matched(db, actor, case, p, basis)
    else:
        before = str(p.status)
        ensure_transition(
            "external payment",
            EXTERNAL_PAYMENT_TRANSITIONS,
            p.status,
            ExternalPaymentStatus.NEEDS_CLARIFICATION,
        )
        p.status = ExternalPaymentStatus.NEEDS_CLARIFICATION
        p.match_basis = basis
        _audit(
            db,
            actor,
            case_id=case.id,
            event_type="EXTERNAL_PAYMENT_NEEDS_CLARIFICATION",
            entity_type="external_payment",
            entity_id=p.id,
            before={"status": before},
            after={"status": str(p.status)},
            details=basis,
        )
        flag = BillingFlag(
            case_id=case.id,
            bill_id=bill.id if bill else None,
            external_payment_id=p.id,
            flag_type=FlagType.ADVANCE_PAYMENT_MISMATCH,
            line_item_ids=[],
            amount_involved=p.amount,
            explanation="Payment evidence needs clarification: " + " ".join(result.problems),
            evidence=basis,
            rule_id=advance.RULE_ID,
            rule_version=advance.RULE_VERSION,
            dedupe_key=f"adv:{p.id}",
        )
        db.add(flag)
        db.flush()
        _audit(
            db,
            actor,
            case_id=case.id,
            event_type="FLAG_CREATED",
            entity_type="billing_flag",
            entity_id=flag.id,
            after={"flag_type": str(flag.flag_type), "status": str(flag.status)},
        )
    _check_invariants(db, actor, case)
    db.commit()
    return p


def confirm_external_payment(db: Session, actor: Actor, payment_id: uuid.UUID, note: str):
    """Human confirms evidence the automatic match could not. Currency must still match."""
    note = _require_note(note, "a note explaining the confirmation")
    p0 = db.get(ExternalPayment, payment_id)
    if p0 is None:
        raise NotFound(f"external payment {payment_id} not found")
    case = _lock_case(db, p0.case_id)
    _require_reviewer(case, actor)
    p = db.get(ExternalPayment, payment_id, with_for_update=True, populate_existing=True)
    if p.status != ExternalPaymentStatus.NEEDS_CLARIFICATION:
        raise DomainError(
            f"external payment is {p.status}; only NEEDS_CLARIFICATION can be confirmed"
        )
    if p.currency != case.currency:
        raise DomainError("payment currency differs from case currency; it cannot be matched")
    basis = dict(p.match_basis or {})
    basis.update({"label": "Confirmed by payer (not bank-verified)", "payer_note": note})
    _mark_matched(db, actor, case, p, basis)
    for flag in _case_flags(db, case.id):
        if flag.external_payment_id == p.id and flag.status == FlagStatus.OPEN:
            _set_flag_status(db, actor, flag, FlagStatus.RESOLVED, note)
    _check_invariants(db, actor, case)
    db.commit()
    return p


def reject_external_payment(db: Session, actor: Actor, payment_id: uuid.UUID, note: str):
    note = _require_note(note, "a note explaining the rejection")
    p0 = db.get(ExternalPayment, payment_id)
    if p0 is None:
        raise NotFound(f"external payment {payment_id} not found")
    case = _lock_case(db, p0.case_id)
    _require_reviewer(case, actor)
    p = db.get(ExternalPayment, payment_id, with_for_update=True, populate_existing=True)
    ensure_transition(
        "external payment", EXTERNAL_PAYMENT_TRANSITIONS, p.status, ExternalPaymentStatus.REJECTED
    )
    before = str(p.status)
    p.status = ExternalPaymentStatus.REJECTED
    p.status_note = note
    _audit(
        db,
        actor,
        case_id=case.id,
        event_type="EXTERNAL_PAYMENT_REJECTED",
        entity_type="external_payment",
        entity_id=p.id,
        before={"status": before},
        after={"status": str(p.status)},
        details={"note": note},
    )
    for flag in _case_flags(db, case.id):
        if flag.external_payment_id == p.id and flag.status == FlagStatus.OPEN:
            _set_flag_status(db, actor, flag, FlagStatus.RESOLVED, note)
    db.commit()
    return p


# ---------------------------------------------------------------- flags


def _set_flag_status(db: Session, actor: Actor, flag: BillingFlag, target: FlagStatus, note: str):
    ensure_transition("flag", FLAG_TRANSITIONS, flag.status, target)
    before = str(flag.status)
    flag.status = target
    if target in (FlagStatus.RESOLVED, FlagStatus.DISMISSED):
        flag.resolution_note = note
        flag.resolved_by = actor.user_id
        flag.resolved_at = _now()
    _audit(
        db,
        actor,
        case_id=flag.case_id,
        event_type="FLAG_STATUS_CHANGED",
        entity_type="billing_flag",
        entity_id=flag.id,
        before={"status": before},
        after={"status": str(target)},
        details={"note": note},
    )


def change_flag_status(
    db: Session, actor: Actor, flag_id: uuid.UUID, target: FlagStatus, note: str
) -> BillingFlag:
    """Resolve or dismiss a flag. This never changes a line item or the ledger;
    the payer must separately accept or keep querying the affected charge."""
    note = _require_note(note, "a note")
    f0 = db.get(BillingFlag, flag_id)
    if f0 is None:
        raise NotFound(f"flag {flag_id} not found")
    case = _lock_case(db, f0.case_id)
    _require_reviewer(case, actor)
    flag = db.get(BillingFlag, flag_id, with_for_update=True, populate_existing=True)
    from app.providers import has_pending_workflow

    if has_pending_workflow(db, flag_id=flag.id):
        raise DomainError("review or revoke the provider workflow before changing this question")
    if target in (FlagStatus.SUBMITTED_TO_PROVIDER, FlagStatus.PROVIDER_RESPONDED):
        raise DomainError("use the scoped provider workflow for provider states")
    if flag.flag_type == FlagType.ADVANCE_PAYMENT_MISMATCH:
        raise DomainError("advance-payment flags are closed by confirming or rejecting the payment")
    _set_flag_status(db, actor, flag, target, note)
    db.commit()
    return flag


# ---------------------------------------------------------------- reads & invariants


def _case_lines(db: Session, case_id: uuid.UUID) -> list[BillLineItem]:
    return list(
        db.scalars(
            select(BillLineItem)
            .where(BillLineItem.case_id == case_id)
            .execution_options(populate_existing=True)
            .order_by(BillLineItem.bill_id, BillLineItem.line_number)
        )
    )


def _case_flags(db: Session, case_id: uuid.UUID) -> list[BillingFlag]:
    return list(
        db.scalars(
            select(BillingFlag)
            .where(BillingFlag.case_id == case_id)
            .execution_options(populate_existing=True)
            .order_by(BillingFlag.created_at)
        )
    )


def case_payments(db: Session, case_id: uuid.UUID) -> list[ExternalPayment]:
    return list(
        db.scalars(
            select(ExternalPayment)
            .where(ExternalPayment.case_id == case_id)
            .execution_options(populate_existing=True)
            .order_by(ExternalPayment.created_at)
        )
    )


def case_ledger(db: Session, case_id: uuid.UUID) -> list[LedgerEntry]:
    return list(
        db.scalars(
            select(LedgerEntry).where(LedgerEntry.case_id == case_id).order_by(LedgerEntry.seq)
        )
    )


def case_audit(db: Session, case_id: uuid.UUID) -> list[AuditEvent]:
    return list(
        db.scalars(select(AuditEvent).where(AuditEvent.case_id == case_id).order_by(AuditEvent.seq))
    )


def case_flags(db: Session, case_id: uuid.UUID) -> list[BillingFlag]:
    return _case_flags(db, case_id)


def case_lines(db: Session, case_id: uuid.UUID) -> list[BillLineItem]:
    return _case_lines(db, case_id)


def get_buckets(db: Session, case: CareCase) -> Buckets:
    db.flush()
    ledger = [
        LedgerView(e.entry_type, e.amount, e.currency, e.line_item_id)
        for e in case_ledger(db, case.id)
    ]
    lines = [_line_view(li) for li in _case_lines(db, case.id)]
    payments = [_payment_view(p) for p in case_payments(db, case.id)]
    paypal_paid = sum(
        (
            p.amount
            for p in db.scalars(
                select(PayPalPaymentRef).where(
                    PayPalPaymentRef.case_id == case.id, PayPalPaymentRef.payment_source == "PAYPAL"
                )
            )
        ),
        ZERO,
    )
    return compute_buckets(case.currency, ledger, lines, payments, paypal_paid)


def _check_invariants(db: Session, actor: Actor, case: CareCase) -> Buckets:
    b = get_buckets(db, case)
    if not b.consistent and CaseStatus.RECONCILIATION_REQUIRED in CASE_TRANSITIONS[case.status]:
        _set_case_status(db, actor, case, CaseStatus.RECONCILIATION_REQUIRED, " ".join(b.issues))
    return b


def get_case(db: Session, case_id: uuid.UUID) -> CareCase:
    case = db.get(CareCase, case_id)
    if case is None:
        raise NotFound(f"case {case_id} not found")
    return case
