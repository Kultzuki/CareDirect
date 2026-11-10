"""Scoped provider proposals and explicit, immutable payer decisions.

ACCEPT acknowledges the question and proposes a full credit. CORRECT proposes a new
recognized amount. EXPLAIN retains the charge. None changes the ledger without the payer.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import uuid
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import services as svc
from app.errors import DomainError, Forbidden, NotFound, ValidationFailed
from app.models import (
    AuditEvent,
    Bill,
    BillingFlag,
    BillLineItem,
    CareCase,
    LedgerEntry,
    ProviderDecision,
    ProviderLink,
    ProviderResponse,
)
from app.money import ZERO, money, to_str
from app.states import (
    CaseStatus,
    FlagStatus,
    FlagType,
    LedgerEntryType,
    LineItemStatus,
    ProviderDecisionType,
    ProviderResponseType,
)

_TOKEN = re.compile(r"^[A-Za-z0-9_-]{43}$")
_LINK_UNAVAILABLE = "This response link is unavailable. Ask the payer for a new link."
_ACTIVE_FLAGS = (FlagStatus.OPEN, FlagStatus.SUBMITTED_TO_PROVIDER, FlagStatus.PROVIDER_RESPONDED)


def _lock(db: Session, case_id: uuid.UUID) -> CareCase:
    case = svc._lock_case(db, case_id)
    # Refresh dependent identities after acquiring the case lock. A session may have
    # loaded them before it waited for a concurrent transaction to finish.
    db.expire_all()
    return db.get(CareCase, case.id, populate_existing=True)


def recognized_amount(db: Session, line: BillLineItem) -> Decimal:
    delta = ZERO
    for entry in db.scalars(select(LedgerEntry).where(LedgerEntry.line_item_id == line.id)):
        if entry.entry_type == LedgerEntryType.ADJUSTMENT_CREDIT:
            delta -= entry.amount
        elif entry.entry_type == LedgerEntryType.ADJUSTMENT_DEBIT:
            delta += entry.amount
    return line.line_total + delta


def _current_hold_seq(db: Session, line_id: uuid.UUID) -> int:
    return (
        db.scalar(
            select(func.max(LedgerEntry.seq)).where(
                LedgerEntry.line_item_id == line_id,
                LedgerEntry.entry_type == LedgerEntryType.QUERY_HOLD,
            )
        )
        or 0
    )


def has_pending_workflow(
    db: Session, line_id: uuid.UUID | None = None, flag_id: uuid.UUID | None = None
) -> bool:
    link_scope = (
        ProviderLink.line_item_id == line_id if line_id else ProviderLink.flag_id == flag_id
    )
    response_scope = (
        ProviderResponse.line_item_id == line_id if line_id else ProviderResponse.flag_id == flag_id
    )
    active = db.scalar(
        select(ProviderLink.id)
        .where(
            link_scope,
            ProviderLink.revoked_at.is_(None),
            ProviderLink.consumed_at.is_(None),
            ProviderLink.expires_at > svc._now(),
        )
        .limit(1)
    )
    unanswered_decision = db.scalar(
        select(ProviderResponse.id)
        .outerjoin(ProviderDecision, ProviderDecision.response_id == ProviderResponse.id)
        .where(
            response_scope,
            ProviderResponse.provider_link_id.is_not(None),
            ProviderDecision.id.is_(None),
        )
        .limit(1)
    )
    return active is not None or unanswered_decision is not None


def _refresh_flag_state(db: Session, actor: svc.Actor, flag: BillingFlag, note: str):
    """One flag may cover several independently held lines and scoped links."""
    db.flush()
    held = any(
        str(li.id) in flag.line_item_ids and li.status == LineItemStatus.QUERIED
        for li in svc.case_lines(db, flag.case_id)
    )
    unanswered = db.scalar(
        select(ProviderResponse.id)
        .outerjoin(ProviderDecision, ProviderDecision.response_id == ProviderResponse.id)
        .where(
            ProviderResponse.flag_id == flag.id,
            ProviderDecision.id.is_(None),
            ProviderResponse.provider_link_id.is_not(None),
        )
        .limit(1)
    )
    active = db.scalar(
        select(ProviderLink.id)
        .where(
            ProviderLink.flag_id == flag.id,
            ProviderLink.revoked_at.is_(None),
            ProviderLink.consumed_at.is_(None),
            ProviderLink.expires_at > svc._now(),
        )
        .limit(1)
    )
    required = (
        flag.line_item_ids[1:]
        if flag.flag_type == FlagType.POSSIBLE_EXACT_DUPLICATE
        else flag.line_item_ids
    )
    accepted = set()
    for line_id, release_seq in db.execute(
        select(ProviderDecision.line_item_id, LedgerEntry.seq)
        .select_from(ProviderDecision)
        .join(ProviderResponse, ProviderDecision.response_id == ProviderResponse.id)
        .join(LedgerEntry, LedgerEntry.provider_decision_id == ProviderDecision.id)
        .where(
            ProviderResponse.flag_id == flag.id,
            ProviderDecision.decision == ProviderDecisionType.ACCEPT,
            LedgerEntry.entry_type == LedgerEntryType.QUERY_RELEASE,
        )
    ):
        # A prior round's answer cannot silently clear a later reopened hold.
        if release_seq > _current_hold_seq(db, line_id):
            accepted.add(line_id)
    all_answered = bool(required) and all(uuid.UUID(line_id) in accepted for line_id in required)
    target = (
        FlagStatus.RESOLVED
        if not held and all_answered
        else FlagStatus.PROVIDER_RESPONDED
        if unanswered
        else FlagStatus.SUBMITTED_TO_PROVIDER
        if active
        else FlagStatus.OPEN
    )
    if flag.status != target:
        svc._set_flag_status(db, actor, flag, target, note)


def create_link(
    db: Session,
    actor: svc.Actor,
    flag_id: uuid.UUID,
    line_id: uuid.UUID,
    question: str,
    ttl_minutes: int = 1440,
):
    question = svc._require_note(question, "a specific question")
    if len(question) > 2000 or not 1 <= ttl_minutes <= 1440:
        raise ValidationFailed("question or link lifetime is outside the allowed limit")
    flag = db.get(BillingFlag, flag_id)
    if flag is None:
        raise NotFound("billing question not found")
    case = _lock(db, flag.case_id)
    svc._require_reviewer(case, actor)
    flag = db.get(BillingFlag, flag_id, populate_existing=True)
    line = db.get(BillLineItem, line_id, populate_existing=True)
    if (
        line is None
        or line.case_id != case.id
        or str(line.id) not in flag.line_item_ids
        or line.bill_id != flag.bill_id
    ):
        raise ValidationFailed("the selected line does not belong to this billing question")
    if flag.flag_type == FlagType.ADVANCE_PAYMENT_MISMATCH:
        raise DomainError("payment evidence is resolved through payment review")
    if line.status != LineItemStatus.QUERIED or flag.status not in _ACTIVE_FLAGS:
        raise DomainError("hold the charge and open the billing question before creating a link")
    if has_pending_workflow(db, line.id):
        raise DomainError("this line already has an active link or a response awaiting review")
    if case.status in (CaseStatus.CLOSED, CaseStatus.RECONCILIATION_REQUIRED):
        raise DomainError("this case cannot open a provider question in its current state")
    amount = recognized_amount(db, line)
    if amount <= ZERO:
        raise DomainError("a fully credited charge has no amount to query")
    # Earlier expired/rejected links cannot become valid for the new question.
    for previous in db.scalars(
        select(ProviderLink).where(
            ProviderLink.line_item_id == line.id, ProviderLink.revoked_at.is_(None)
        )
    ):
        previous.revoked_at = svc._now()
    token = secrets.token_urlsafe(32)
    row = ProviderLink(
        id=uuid.uuid4(),
        case_id=case.id,
        flag_id=flag.id,
        line_item_id=line.id,
        token_sha256=hashlib.sha256(token.encode()).hexdigest(),
        question=question,
        issued_amount=amount,
        expires_at=svc._now() + timedelta(minutes=ttl_minutes),
        created_by=actor.user_id,
    )
    db.add(row)
    db.flush()
    _refresh_flag_state(db, actor, flag, "Scoped response link created; delivery is manual.")
    if case.status == CaseStatus.READY_FOR_APPROVAL:
        svc._set_case_status(
            db, actor, case, CaseStatus.UNDER_REVIEW, "A provider question changed approval state."
        )
    if case.status == CaseStatus.UNDER_REVIEW:
        svc._set_case_status(
            db, actor, case, CaseStatus.AWAITING_PROVIDER, "Scoped response link created."
        )
    svc._audit(
        db,
        actor,
        case_id=case.id,
        event_type="PROVIDER_LINK_CREATED",
        entity_type="provider_link",
        entity_id=row.id,
        details={
            "flag_id": str(flag.id),
            "line_item_id": str(line.id),
            "expires_at": row.expires_at.isoformat(),
            "query_ledger_seq": _current_hold_seq(db, line.id),
        },
    )
    db.commit()
    return row, token


def revoke_link(db: Session, actor: svc.Actor, link_id: uuid.UUID, note: str):
    note = svc._require_note(note, "a reason for revocation")
    link = db.get(ProviderLink, link_id)
    if link is None:
        raise NotFound("response link not found")
    case = _lock(db, link.case_id)
    svc._require_reviewer(case, actor)
    link = db.get(ProviderLink, link_id, populate_existing=True)
    if link.revoked_at is None:
        link.revoked_at = svc._now()
        flag = db.get(BillingFlag, link.flag_id, populate_existing=True)
        _refresh_flag_state(db, actor, flag, note)
        svc._audit(
            db,
            actor,
            case_id=case.id,
            event_type="PROVIDER_LINK_REVOKED",
            entity_type="provider_link",
            entity_id=link.id,
            details={"note": note},
        )
        db.commit()
    return link


def _find_link(db: Session, token: str) -> ProviderLink:
    if not _TOKEN.fullmatch(token):
        raise Forbidden(_LINK_UNAVAILABLE)
    row = db.scalar(
        select(ProviderLink)
        .where(ProviderLink.token_sha256 == hashlib.sha256(token.encode()).hexdigest())
        .execution_options(populate_existing=True)
    )
    if row is None or row.revoked_at is not None or row.expires_at <= svc._now():
        raise Forbidden(_LINK_UNAVAILABLE)
    return row


def portal(db: Session, token: str) -> dict:
    row = _find_link(db, token)
    line = db.get(BillLineItem, row.line_item_id, populate_existing=True)
    flag = db.get(BillingFlag, row.flag_id, populate_existing=True)
    issued = db.scalar(
        select(AuditEvent).where(
            AuditEvent.entity_id == row.id, AuditEvent.event_type == "PROVIDER_LINK_CREATED"
        )
    )
    if row.consumed_at is None and (
        line.status != LineItemStatus.QUERIED
        or flag.status not in _ACTIVE_FLAGS
        or recognized_amount(db, line) != row.issued_amount
        or issued is None
        or issued.details.get("query_ledger_seq") != _current_hold_seq(db, line.id)
    ):
        raise Forbidden(_LINK_UNAVAILABLE)
    response = db.scalar(
        select(ProviderResponse).where(ProviderResponse.provider_link_id == row.id)
    )
    return {
        "provider_name": db.get(Bill, line.bill_id).provider_name,
        "currency": line.currency,
        "question": row.question,
        "line": {
            "id": line.id,
            "description_raw": line.description_raw,
            "line_total": line.line_total,
            "recognized_amount": row.issued_amount,
            "source_page": line.source_page,
            "source_text": line.source_text,
        },
        # Only the selected line's source is disclosed. Broad flag evidence may contain
        # unrelated lines or document metadata and is deliberately not returned.
        "flag": {"id": flag.id, "explanation": flag.explanation},
        "expires_at": row.expires_at,
        "state": "RESPONDED" if row.consumed_at else "AWAITING_RESPONSE",
        "response": response,
    }


def respond(
    db: Session,
    token: str,
    response_type: ProviderResponseType,
    response_text: str,
    responder_label: str,
    corrected_amount: Decimal | None = None,
) -> ProviderResponse:
    row = _find_link(db, token)
    case = _lock(db, row.case_id)
    row = _find_link(db, token)
    if row.consumed_at is not None:
        raise DomainError("A response has already been recorded for this link.")
    portal(db, token)  # Repeat the current line/flag/issued amount checks under the lock.
    text = svc._require_note(response_text, "a reason")
    label = svc._require_note(responder_label, "a billing representative name")
    if len(text) > 2000 or len(label) > 120:
        raise ValidationFailed("response is too long")
    if (response_type == ProviderResponseType.CORRECT) != (corrected_amount is not None):
        raise ValidationFailed("only Correct requires a proposed corrected amount")
    if corrected_amount is not None:
        corrected_amount = money(corrected_amount)
        if corrected_amount < ZERO:
            raise ValidationFailed("the proposed amount must not be negative")
    response = ProviderResponse(
        id=uuid.uuid4(),
        case_id=case.id,
        flag_id=row.flag_id,
        line_item_id=row.line_item_id,
        provider_link_id=row.id,
        response_type=response_type,
        response_text=text,
        corrected_amount=corrected_amount,
        currency=case.currency,
        responder_label=label,
        actor_verification_method="SCOPED_BEARER_LINK_NOT_IDENTITY_VERIFIED",
    )
    db.add(response)
    db.flush()
    row.consumed_at = svc._now()
    flag = db.get(BillingFlag, row.flag_id)
    provider = svc.Actor(user=None, label="PROVIDER:scoped link")
    _refresh_flag_state(db, provider, flag, "Provider proposal awaits payer review.")
    svc._audit(
        db,
        provider,
        case_id=case.id,
        event_type="PROVIDER_RESPONSE_RECORDED",
        entity_type="provider_response",
        entity_id=response.id,
        details={
            "response_type": str(response_type),
            "flag_id": str(flag.id),
            "line_item_id": str(row.line_item_id),
            "ledger_effect": "none",
        },
    )
    db.commit()
    return response


def workflow(db: Session, actor: svc.Actor, case_id: uuid.UUID) -> dict:
    case = svc.get_case(db, case_id)
    svc._require_case_member(case, actor)

    def rows(model):
        return list(
            db.scalars(
                select(model)
                .where(model.case_id == case_id)
                .order_by(model.created_at if model != ProviderResponse else model.responded_at)
                .execution_options(populate_existing=True)
            )
        )

    return {
        "links": rows(ProviderLink),
        "responses": rows(ProviderResponse),
        "decisions": rows(ProviderDecision),
    }


def _response_context(db: Session, actor: svc.Actor, response_id: uuid.UUID):
    response = db.get(ProviderResponse, response_id)
    if response is None:
        raise NotFound("provider response not found")
    case = _lock(db, response.case_id)
    svc._require_reviewer(case, actor)
    response = db.get(ProviderResponse, response_id, populate_existing=True)
    if response.provider_link_id is None or response.line_item_id is None:
        raise DomainError(
            "this historical response has no scoped question and cannot be resolved here"
        )
    line = db.get(BillLineItem, response.line_item_id, populate_existing=True)
    flag = db.get(BillingFlag, response.flag_id, populate_existing=True)
    return case, response, line, flag


def state_fingerprint(db: Session, case: CareCase) -> str:
    # Includes non-ledger changes (flag/response/decision) via immutable audit sequence,
    # and independent mutable state so a stale approval cannot rely on ledger_seq alone.
    state = {
        "case": str(case.id),
        "status": str(case.status),
        "audit_seq": db.scalar(
            select(func.max(AuditEvent.seq)).where(AuditEvent.case_id == case.id)
        )
        or 0,
        "ledger_seq": db.scalar(
            select(func.max(LedgerEntry.seq)).where(LedgerEntry.case_id == case.id)
        )
        or 0,
        "lines": [
            [str(li.id), str(li.status), to_str(recognized_amount(db, li))]
            for li in svc.case_lines(db, case.id)
        ],
        "flags": [[str(f.id), str(f.status)] for f in svc.case_flags(db, case.id)],
    }
    return hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest()


def _proposed(response: ProviderResponse, current: Decimal) -> Decimal:
    if response.response_type == ProviderResponseType.ACCEPT:
        return ZERO
    if response.response_type == ProviderResponseType.CORRECT:
        return response.corrected_amount
    return current


def preview(db: Session, actor: svc.Actor, response_id: uuid.UUID) -> dict:
    case, response, line, flag = _response_context(db, actor, response_id)
    before = svc.get_buckets(db, case)
    current = recognized_amount(db, line)
    proposed = _proposed(response, current)
    adjustment = proposed - current
    blockers = []
    if db.scalar(select(ProviderDecision.id).where(ProviderDecision.response_id == response.id)):
        blockers.append("This response already has a payer decision.")
    if line.status != LineItemStatus.QUERIED or flag.status not in _ACTIVE_FLAGS:
        blockers.append("This question is no longer awaiting a payer decision.")
    if not before.consistent:
        blockers.extend(before.issues)
    if case.status in (CaseStatus.CLOSED, CaseStatus.RECONCILIATION_REQUIRED):
        blockers.append("The case needs reconciliation before accepting a resolution.")
    for other in svc.case_flags(db, case.id):
        if (
            other.id != flag.id
            and other.status in _ACTIVE_FLAGS
            and str(line.id) in other.line_item_ids
        ):
            blockers.append("Another open question covers this line; resolve that question first.")
    after = replace(
        before,
        bill_total=before.bill_total + adjustment,
        adjustments=before.adjustments + adjustment,
        payable_now=before.payable_now + proposed,
        queried=before.queried - current,
    )
    if after.payable_now < ZERO or after.queried < ZERO or after.bill_total < ZERO:
        blockers.append("The proposed resolution would make a financial bucket negative.")
    if not after.invariant_holds:
        blockers.append("The proposed resolution does not reconcile.")
    return {
        "response_id": response.id,
        "case_id": case.id,
        "line_item_id": line.id,
        "currency": case.currency,
        "original_amount": line.line_total,
        "current_amount": current,
        "proposed_amount": proposed,
        "adjustment": adjustment,
        "before": before,
        "after": after,
        "state_fingerprint": state_fingerprint(db, case),
        "can_accept": not blockers,
        "blockers": blockers,
    }


def decide(
    db: Session,
    actor: svc.Actor,
    response_id: uuid.UUID,
    decision: ProviderDecisionType,
    note: str,
    fingerprint: str,
) -> ProviderDecision:
    note = svc._require_note(note, "a note explaining the payer decision")
    case, response, line, flag = _response_context(db, actor, response_id)
    p = preview(db, actor, response_id)
    if fingerprint != p["state_fingerprint"]:
        raise DomainError("The case changed. Review the updated amounts before deciding.")
    if db.scalar(select(ProviderDecision.id).where(ProviderDecision.response_id == response.id)):
        raise DomainError("This response already has a payer decision.")
    if line.status != LineItemStatus.QUERIED or flag.status not in _ACTIVE_FLAGS:
        raise DomainError("This question is no longer awaiting a payer decision.")
    if decision == ProviderDecisionType.ACCEPT and not p["can_accept"]:
        raise DomainError(" ".join(p["blockers"]))
    target = (
        p["proposed_amount"] if decision == ProviderDecisionType.ACCEPT else p["current_amount"]
    )
    adjustment = target - p["current_amount"]
    record = ProviderDecision(
        id=uuid.uuid4(),
        case_id=case.id,
        response_id=response.id,
        line_item_id=line.id,
        decision=decision,
        note=note,
        original_amount=line.line_total,
        previous_amount=p["current_amount"],
        recognized_amount=target,
        adjustment=adjustment,
        currency=case.currency,
        state_fingerprint=fingerprint,
        decided_by=actor.user_id,
        actor_label=actor.label,
    )
    db.add(record)
    db.flush()
    if decision == ProviderDecisionType.ACCEPT:
        svc._ledger(
            db,
            actor,
            case,
            LedgerEntryType.QUERY_RELEASE,
            p["current_amount"],
            "Payer accepted provider resolution: " + note,
            bill_id=line.bill_id,
            line_item_id=line.id,
            flag_id=flag.id,
            provider_decision_id=record.id,
        )
        if adjustment:
            kind = (
                LedgerEntryType.ADJUSTMENT_CREDIT
                if adjustment < ZERO
                else LedgerEntryType.ADJUSTMENT_DEBIT
            )
            svc._ledger(
                db,
                actor,
                case,
                kind,
                abs(adjustment),
                "Reviewed provider adjustment: " + note,
                bill_id=line.bill_id,
                line_item_id=line.id,
                flag_id=flag.id,
                provider_decision_id=record.id,
            )
        line.status = LineItemStatus.ACCEPTED
        line.status_note = note
    # A consumed capability must not expose or answer the next round of the question.
    link = db.get(ProviderLink, response.provider_link_id, populate_existing=True)
    link.revoked_at = svc._now()
    _refresh_flag_state(db, actor, flag, note)
    if case.status == CaseStatus.AWAITING_PROVIDER:
        svc._set_case_status(
            db, actor, case, CaseStatus.UNDER_REVIEW, "Payer reviewed a provider response."
        )
    svc._audit(
        db,
        actor,
        case_id=case.id,
        event_type="PROVIDER_RESOLUTION_" + str(decision),
        entity_type="provider_decision",
        entity_id=record.id,
        before={
            "recognized_amount": to_str(p["current_amount"]),
            "queried": to_str(p["before"].queried),
        },
        after={"recognized_amount": to_str(target), "adjustment": to_str(adjustment)},
        details={"response_id": str(response.id), "line_item_id": str(line.id), "note": note},
    )
    b = svc._check_invariants(db, actor, case)
    if not b.consistent:
        raise DomainError("Resolution failed financial consistency checks: " + " ".join(b.issues))
    db.commit()
    return record
