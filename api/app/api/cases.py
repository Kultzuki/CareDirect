"""Case API. No endpoint here creates, sends or executes a payment."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import services as svc
from app.db import get_db
from app.episode import get_care_episode
from app.errors import Forbidden
from app.models import CareCase, User
from app.schemas import (
    AcceptLine,
    ApprovalReadinessOut,
    AuditEventOut,
    BillCreate,
    BillOut,
    BucketsOut,
    CareEpisodeOut,
    CaseCreate,
    CaseDetailOut,
    CaseSummaryOut,
    CaseTransition,
    EpisodeAnalyze,
    EpisodeDetails,
    ExternalPaymentCreate,
    ExternalPaymentOut,
    FlagOut,
    FlagStatusChange,
    LedgerEntryOut,
    LineItemOut,
    NoteBody,
    QueryLine,
    RunChecksOut,
    UserOut,
)

router = APIRouter(prefix="/api")

DB = Annotated[Session, Depends(get_db)]


def current_actor(
    db: DB, x_demo_user_id: Annotated[uuid.UUID | None, Header()] = None
) -> svc.Actor:
    """DEMO ONLY: identifies the acting user from a header. Not authentication.
    Real auth replaces this before any non-local deployment."""
    if x_demo_user_id is None:
        raise Forbidden("X-Demo-User-Id header required (demo identity, not authentication)")
    user = db.get(User, x_demo_user_id)
    if user is None:
        raise Forbidden("unknown demo user")
    return svc.Actor(user=user, label=f"{user.role}:{user.display_name}")


ActorDep = Annotated[svc.Actor, Depends(current_actor)]


def _buckets(db: Session, case: CareCase) -> BucketsOut:
    from app.insurance import has_insurance

    b = svc.get_buckets(db, case)
    return BucketsOut(
        insurance_present=has_insurance(db, case.id),
        currency=b.currency,
        bill_total=b.bill_total,
        payable_now=b.payable_now,
        queried=b.queried,
        already_paid=b.already_paid,
        pending_review=b.pending_review,
        invariant_holds=b.invariant_holds,
        consistent=b.consistent,
        issues=list(b.issues),
        original_bill_total=b.original_bill_total,
        adjustments=b.adjustments,
        net_bill_total=b.net_bill_total,
    )


def _summary(db: Session, case: CareCase) -> CaseSummaryOut:
    return CaseSummaryOut(
        id=case.id,
        case_reference=case.case_reference,
        patient_alias=case.patient_alias,
        currency=case.currency,
        status=case.status,
        is_demo=case.is_demo,
        created_at=case.created_at,
        buckets=_buckets(db, case),
        episode_title=case.episode_title,
        clinical_context=case.clinical_context,
    )


def _detail(db: Session, case: CareCase, actor: svc.Actor) -> CaseDetailOut:
    from app.family import access

    blockers = svc.approval_blockers(db, case)
    return CaseDetailOut(
        family_permissions=access(case, actor),
        **_summary(db, case).model_dump(),
        payer=UserOut.model_validate(case.payer),
        bills=[BillOut.model_validate(b) for b in case.bills],
        external_payments=[
            ExternalPaymentOut.model_validate(p) for p in svc.case_payments(db, case.id)
        ],
        flags=[FlagOut.model_validate(f) for f in svc.case_flags(db, case.id)],
        approval_readiness=ApprovalReadinessOut(ready=not blockers, blockers=blockers),
    )


def _visible_case(db: Session, actor: svc.Actor, case_id: uuid.UUID) -> CareCase:
    case = svc.get_case(db, case_id)
    svc._require_case_member(case, actor)
    return case


@router.get("/users", response_model=list[UserOut])
def list_demo_users(db: DB):
    """DEMO ONLY: lists seeded demo identities so the local dashboard can pick one."""
    return db.scalars(select(User).where(User.is_demo.is_(True)).order_by(User.created_at)).all()


@router.get("/cases", response_model=list[CaseSummaryOut])
def list_cases(db: DB, actor: ActorDep):
    q = select(CareCase).order_by(CareCase.created_at.desc())
    if actor.user.role.value != "ADMIN":
        from app.family import visible_case_ids

        q = q.where(visible_case_ids(actor))
    return [_summary(db, c) for c in db.scalars(q).all()]


@router.post("/cases", response_model=CaseDetailOut, status_code=status.HTTP_201_CREATED)
def create_case(body: CaseCreate, db: DB, actor: ActorDep):
    case = svc.create_case(
        db,
        actor,
        patient_alias=body.patient_alias,
        currency=body.currency,
        case_reference=body.case_reference,
        episode_title=body.episode_title,
        clinical_context=body.clinical_context,
    )
    db.commit()
    return _detail(db, case, actor)


@router.post("/demo/cases", response_model=CaseDetailOut, status_code=status.HTTP_201_CREATED)
def create_synthetic_case(body: CaseCreate, db: DB, actor: ActorDep):
    """Explicit synthetic-only fresh run; existing evidence/history is never reset."""
    from app.config import get_settings

    if not actor.user.is_demo or get_settings().app_env not in ("development", "test", "demo"):
        raise Forbidden("Synthetic cases require a configured demo payer.")
    case = svc.create_case(
        db,
        actor,
        patient_alias=body.patient_alias,
        currency=body.currency,
        case_reference=body.case_reference,
        episode_title=body.episode_title,
        clinical_context=body.clinical_context,
        is_demo=True,
    )
    db.commit()
    return _detail(db, case, actor)


@router.get("/cases/{case_id}", response_model=CaseDetailOut)
def get_case(case_id: uuid.UUID, db: DB, actor: ActorDep):
    return _detail(db, _visible_case(db, actor, case_id), actor)


@router.get("/cases/{case_id}/buckets", response_model=BucketsOut)
def get_buckets(case_id: uuid.UUID, db: DB, actor: ActorDep):
    return _buckets(db, _visible_case(db, actor, case_id))


@router.post("/cases/{case_id}/bills", response_model=BillOut, status_code=status.HTTP_201_CREATED)
def add_bill(case_id: uuid.UUID, body: BillCreate, db: DB, actor: ActorDep):
    # Source type is set server-side; clients cannot claim AI or seeded provenance.
    data = svc.BillInput(
        provider_name=body.provider_name,
        currency=body.currency.upper(),
        bill_number=body.bill_number,
        bill_date=body.bill_date,
        printed_total=body.printed_total,
        printed_advance_paid=body.printed_advance_paid,
        printed_balance_due=body.printed_balance_due,
        source_document_ref=body.source_document_ref,
        lines=[svc.LineInput(**ln.model_dump()) for ln in body.lines],
    )
    return svc.add_bill(db, actor, case_id, data)


@router.post("/cases/{case_id}/run-checks", response_model=RunChecksOut)
def run_checks(case_id: uuid.UUID, db: DB, actor: ActorDep):
    created = svc.run_checks(db, actor, case_id)
    return RunChecksOut(flags_created=[FlagOut.model_validate(f) for f in created])


@router.get("/cases/{case_id}/line-items", response_model=list[LineItemOut])
def list_line_items(case_id: uuid.UUID, db: DB, actor: ActorDep):
    _visible_case(db, actor, case_id)
    return svc.case_lines(db, case_id)


@router.get("/cases/{case_id}/flags", response_model=list[FlagOut])
def list_flags(case_id: uuid.UUID, db: DB, actor: ActorDep):
    _visible_case(db, actor, case_id)
    return svc.case_flags(db, case_id)


@router.get("/cases/{case_id}/ledger", response_model=list[LedgerEntryOut])
def list_ledger(case_id: uuid.UUID, db: DB, actor: ActorDep):
    _visible_case(db, actor, case_id)
    return svc.case_ledger(db, case_id)


@router.get("/cases/{case_id}/audit-events", response_model=list[AuditEventOut])
def list_audit(case_id: uuid.UUID, db: DB, actor: ActorDep):
    _visible_case(db, actor, case_id)
    return svc.case_audit(db, case_id)


@router.post(
    "/cases/{case_id}/external-payments",
    response_model=ExternalPaymentOut,
    status_code=status.HTTP_201_CREATED,
)
def record_external_payment(
    case_id: uuid.UUID, body: ExternalPaymentCreate, db: DB, actor: ActorDep
):
    data = svc.PaymentInput(**body.model_dump())
    return svc.record_external_payment(db, actor, case_id, data)


@router.post("/cases/{case_id}/transition", response_model=CaseSummaryOut)
def transition_case(case_id: uuid.UUID, body: CaseTransition, db: DB, actor: ActorDep):
    return _summary(db, svc.transition_case(db, actor, case_id, body.status))


@router.post("/line-items/{line_id}/query", response_model=LineItemOut)
def query_line(line_id: uuid.UUID, body: QueryLine, db: DB, actor: ActorDep):
    return svc.query_line(db, actor, line_id, body.reason, body.flag_id)


@router.post("/line-items/{line_id}/accept", response_model=LineItemOut)
def accept_line(line_id: uuid.UUID, body: AcceptLine, db: DB, actor: ActorDep):
    return svc.accept_line(db, actor, line_id, body.note)


@router.post("/external-payments/{payment_id}/reconcile", response_model=ExternalPaymentOut)
def reconcile_payment(payment_id: uuid.UUID, db: DB, actor: ActorDep):
    return svc.reconcile_external_payment(db, actor, payment_id)


@router.post("/external-payments/{payment_id}/confirm", response_model=ExternalPaymentOut)
def confirm_payment(payment_id: uuid.UUID, body: NoteBody, db: DB, actor: ActorDep):
    return svc.confirm_external_payment(db, actor, payment_id, body.note)


@router.post("/external-payments/{payment_id}/reject", response_model=ExternalPaymentOut)
def reject_payment(payment_id: uuid.UUID, body: NoteBody, db: DB, actor: ActorDep):
    return svc.reject_external_payment(db, actor, payment_id, body.note)


@router.post("/flags/{flag_id}/status", response_model=FlagOut)
def change_flag_status(flag_id: uuid.UUID, body: FlagStatusChange, db: DB, actor: ActorDep):
    return svc.change_flag_status(db, actor, flag_id, body.status, body.note)


@router.get("/cases/{case_id}/episode", response_model=CareEpisodeOut)
def get_case_episode(case_id: uuid.UUID, db: DB, actor: ActorDep):
    _visible_case(db, actor, case_id)
    return get_care_episode(db, case_id)


@router.post("/cases/{case_id}/episode/analyze", response_model=CareEpisodeOut)
def analyze_case_episode(
    case_id: uuid.UUID, db: DB, actor: ActorDep, body: EpisodeAnalyze | None = None
):
    case = svc._lock_case(db, case_id)
    svc._require_reviewer(case, actor)
    episode = get_care_episode(
        db,
        case_id,
        analyze=True,
        actor=actor,
        expected_fingerprint=body.input_fingerprint if body else None,
    )
    db.commit()
    return episode


@router.post("/cases/{case_id}/episode/details", response_model=CareEpisodeOut)
def update_episode_details(case_id: uuid.UUID, body: EpisodeDetails, db: DB, actor: ActorDep):
    from app.errors import ValidationFailed

    case = svc._lock_case(db, case_id)
    svc._require_payer(case, actor)
    title = body.episode_title.strip()
    if not title:
        raise ValidationFailed("An episode title is required.")
    before = dict(episode_title=case.episode_title, clinical_context=case.clinical_context)
    case.episode_title, case.clinical_context = title, (body.clinical_context or "").strip() or None
    svc._audit(
        db,
        actor,
        case_id=case.id,
        event_type="EPISODE_DETAILS_UPDATED",
        entity_type="care_case",
        entity_id=case.id,
        before=before,
        after=dict(episode_title=case.episode_title, clinical_context=case.clinical_context),
    )
    db.commit()
    return get_care_episode(db, case_id)
