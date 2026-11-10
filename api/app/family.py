"""Case-scoped collaboration and a separate, append-only internal family ledger."""

import hashlib
import json
import re
import secrets
import uuid
from datetime import date, timedelta
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import object_session

from app import services as svc
from app.models import (
    BillLineItem,
    CareCase,
    FamilyAllocationPlan,
    FamilyInvitation,
    FamilyLedgerEntry,
    FamilyMembership,
    FamilyNotification,
    User,
)
from app.money import ZERO, to_str
from app.schemas import MoneyIn
from app.states import LineItemStatus, UserRole

Role = Literal["PAYER", "VIEWER", "PATIENT"]
RequestId = Annotated[str, Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")]


class Permissions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Role = "VIEWER"
    can_review: bool = False
    can_approve: bool = False

    @model_validator(mode="after")
    def role_permissions(self):
        if self.role != "PAYER" and (self.can_review or self.can_approve):
            raise ValueError("Only a payer can have review or payment approval permissions")
        return self


class InviteRequest(Permissions):
    recipient_email: Annotated[str, Field(min_length=3, max_length=254)]
    ttl_hours: Annotated[int, Field(ge=1, le=168)] = 48

    @field_validator("recipient_email")
    @classmethod
    def email(cls, value):
        value = value.strip().casefold()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Enter a valid recipient email")
        return value


class MemberRequest(Permissions):
    active: bool = True
    note: Annotated[str, Field(min_length=1, max_length=2000)]


class ContributionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: uuid.UUID
    amount: MoneyIn
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
    contributed_on: date
    reference: Annotated[str | None, Field(max_length=120)] = None
    note: Annotated[str, Field(min_length=1, max_length=2000)]
    request_id: RequestId


class ReversalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: Annotated[str, Field(min_length=1, max_length=2000)]
    request_id: RequestId


class Share(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: uuid.UUID
    amount: MoneyIn


class AllocationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    line_item_id: uuid.UUID
    source_fingerprint: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    shares: list[Share] = Field(max_length=100)
    note: Annotated[str, Field(min_length=1, max_length=2000)]
    request_id: RequestId


def membership(db, case_id, user_id):
    return db.scalar(
        select(FamilyMembership)
        .where(FamilyMembership.case_id == case_id, FamilyMembership.user_id == user_id)
        .execution_options(populate_existing=True)
    )


def access(case, actor):
    result = dict(
        can_view=False,
        can_review=False,
        can_approve=False,
        can_manage=False,
        can_contribute=False,
        role=None,
    )
    if not actor.user:
        return result
    owner = actor.user_id == case.payer_user_id
    admin = actor.user.role == UserRole.ADMIN
    db = object_session(case)
    member = membership(db, case.id, actor.user_id) if db else None
    if admin:
        return dict(
            can_view=True,
            can_review=True,
            can_approve=True,
            can_manage=True,
            can_contribute=True,
            role="PAYER",
        )
    if owner and member is None:
        return dict(
            can_view=True,
            can_review=True,
            can_approve=True,
            can_manage=True,
            can_contribute=True,
            role="PAYER",
        )
    if member and member.active:
        result.update(
            can_view=True,
            can_review=member.can_review,
            can_approve=member.can_approve,
            can_manage=owner,
            can_contribute=member.role == "PAYER",
            role=member.role,
        )
    return result


def require(case, actor, permission):
    if not access(case, actor).get(permission):
        raise svc.Forbidden("Your episode role does not permit this action (" + permission + ").")


def visible_case_ids(actor):
    return or_(
        CareCase.payer_user_id == actor.user_id,
        CareCase.id.in_(
            select(FamilyMembership.case_id).where(
                FamilyMembership.user_id == actor.user_id, FamilyMembership.active.is_(True)
            )
        ),
    )


def lock_case(db, case_id):
    case = db.scalar(
        select(CareCase)
        .where(CareCase.id == case_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not case:
        raise svc.NotFound("Episode unavailable.")
    return case


def notify(db, event, case, actor):
    """Durable in-app notifications, never email or external delivery."""
    users = set(
        db.scalars(
            select(FamilyMembership.user_id).where(
                FamilyMembership.case_id == case.id, FamilyMembership.active.is_(True)
            )
        )
    ) | {case.payer_user_id}
    for user_id in users - {actor.user_id}:
        db.add(
            FamilyNotification(
                case_id=case.id,
                user_id=user_id,
                audit_event_id=event.id,
                event_type=event.event_type,
                actor_label=actor.label,
            )
        )


def invite(db, actor, case_id, body):
    case = lock_case(db, case_id)
    require(case, actor, "can_manage")
    if case.status == "CLOSED":
        raise svc.DomainError("A closed episode does not accept invitations.")
    if actor.user.email and body.recipient_email == actor.user.email.casefold():
        raise svc.ValidationFailed("The episode owner already has access.")
    raw = secrets.token_urlsafe(32)
    row = FamilyInvitation(
        case_id=case.id,
        recipient_email=body.recipient_email,
        token_sha256=hashlib.sha256(raw.encode()).hexdigest(),
        role=body.role,
        can_review=body.can_review,
        can_approve=body.can_approve,
        expires_at=svc._now() + timedelta(hours=body.ttl_hours),
        created_by=actor.user_id,
    )
    db.add(row)
    db.flush()
    svc._audit(
        db,
        actor,
        case_id=case.id,
        event_type="FAMILY_INVITED",
        entity_type="family_invitation",
        entity_id=row.id,
        details=dict(role=row.role, can_review=row.can_review, can_approve=row.can_approve),
    )
    db.commit()
    return dict(
        id=str(row.id), token=raw, expires_at=row.expires_at, recipient_email=row.recipient_email
    )


def invitation(db, actor, token):
    invalid = "Invitation unavailable for this identity."
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        raise svc.Forbidden(invalid)
    row = db.scalar(
        select(FamilyInvitation)
        .where(FamilyInvitation.token_sha256 == hashlib.sha256(token.encode()).hexdigest())
        .execution_options(populate_existing=True)
    )
    if (
        not row
        or row.revoked_at
        or row.expires_at <= svc._now()
        or not actor.user
        or not actor.user.email
    ):
        raise svc.Forbidden(invalid)
    if actor.user.email.casefold() != row.recipient_email:
        raise svc.Forbidden(invalid)
    return row


def accept_invitation(db, actor, token):
    first = invitation(db, actor, token)
    case = lock_case(db, first.case_id)
    row = invitation(db, actor, token)
    if row.accepted_by:
        if row.accepted_by == actor.user_id:
            require(case, actor, "can_view")  # A consumed invitation cannot undo later revocation.
            return dict(case_id=str(case.id), accepted=True)
        raise svc.Forbidden("Invitation unavailable for this identity.")
    if case.status == "CLOSED":
        raise svc.DomainError("The episode is closed.")
    if actor.user_id == case.payer_user_id or membership(db, case.id, actor.user_id) is not None:
        raise svc.DomainError("Membership already exists. Ask the owner to review its permissions.")
    db.add(
        FamilyMembership(
            case_id=case.id,
            user_id=actor.user_id,
            role=row.role,
            can_review=row.can_review,
            can_approve=row.can_approve,
            active=True,
        )
    )
    row.accepted_by, row.accepted_at = actor.user_id, svc._now()
    db.flush()
    svc._audit(
        db,
        actor,
        case_id=case.id,
        event_type="FAMILY_JOINED",
        entity_type="family_membership",
        entity_id=actor.user_id,
        details=dict(role=row.role),
    )
    db.commit()
    return dict(case_id=str(case.id), accepted=True)


def revoke_invitation(db, actor, case_id, invitation_id):
    case = lock_case(db, case_id)
    require(case, actor, "can_manage")
    row = db.get(FamilyInvitation, invitation_id)
    if not row or row.case_id != case.id:
        raise svc.NotFound("Invitation unavailable.")
    if row.accepted_by:
        raise svc.DomainError("This invitation was accepted. Change the member's access instead.")
    if row.revoked_at is None:
        row.revoked_at = svc._now()
        svc._audit(
            db,
            actor,
            case_id=case.id,
            event_type="FAMILY_INVITATION_REVOKED",
            entity_type="family_invitation",
            entity_id=row.id,
        )
        db.commit()


def change_member(db, actor, case_id, user_id, body):
    case = lock_case(db, case_id)
    require(case, actor, "can_manage")
    row = membership(db, case.id, user_id)
    if user_id == case.payer_user_id:
        if not body.active or body.role != "PAYER":
            raise svc.ValidationFailed(
                "The owner retains active payer membership and access management."
            )
        if not row:
            row = FamilyMembership(case_id=case.id, user_id=user_id, role="PAYER")
            db.add(row)
    elif not row:
        raise svc.NotFound("Membership unavailable. Invite the person first.")
    row.role, row.can_review, row.can_approve, row.active = (
        body.role,
        body.can_review,
        body.can_approve,
        body.active,
    )
    svc._audit(
        db,
        actor,
        case_id=case.id,
        event_type="FAMILY_PERMISSIONS_CHANGED",
        entity_type="family_membership",
        entity_id=user_id,
        details=dict(
            role=body.role,
            can_review=body.can_review,
            can_approve=body.can_approve,
            active=body.active,
            note=svc._require_note(body.note, "Permission change reason"),
        ),
    )
    db.commit()


def _member_can_receive(db, case, user_id):
    if user_id == case.payer_user_id:
        return
    member = membership(db, case.id, user_id)
    if not member or not member.active or member.role != "PAYER":
        raise svc.ValidationFailed("Choose an active family payer in this episode.")


def contribute(db, actor, case_id, body):
    case = lock_case(db, case_id)
    require(case, actor, "can_contribute")
    if actor.user_id != body.user_id and not access(case, actor)["can_manage"]:
        raise svc.Forbidden("Only the owner can record a contribution for another person.")
    _member_can_receive(db, case, body.user_id)
    if body.amount <= ZERO or body.currency != case.currency:
        raise svc.ValidationFailed(
            "Use a positive contribution in the episode currency; no conversion is inferred."
        )
    if body.contributed_on > svc._now().date():
        raise svc.ValidationFailed("A recorded contribution cannot have a future date.")
    note = svc._require_note(body.note, "Contribution note")
    previous = db.scalar(
        select(FamilyLedgerEntry).where(
            FamilyLedgerEntry.case_id == case.id, FamilyLedgerEntry.request_id == body.request_id
        )
    )
    if previous:
        if (
            previous.entry_type,
            previous.user_id,
            previous.amount,
            previous.currency,
            previous.contributed_on,
            previous.reference,
            previous.note,
            previous.created_by,
        ) != (
            "CONTRIBUTION",
            body.user_id,
            body.amount,
            body.currency,
            body.contributed_on,
            body.reference,
            note,
            actor.user_id,
        ):
            raise svc.DomainError(
                "Request identifier already belongs to different contribution evidence."
            )
        return previous
    row = FamilyLedgerEntry(
        case_id=case.id,
        user_id=body.user_id,
        entry_type="CONTRIBUTION",
        amount=body.amount,
        currency=case.currency,
        contributed_on=body.contributed_on,
        reference=body.reference,
        note=note,
        request_id=body.request_id,
        created_by=actor.user_id,
    )
    db.add(row)
    db.flush()
    svc._audit(
        db,
        actor,
        case_id=case.id,
        event_type="FAMILY_CONTRIBUTION_RECORDED",
        entity_type="family_ledger_entry",
        entity_id=row.id,
        details=dict(user_id=str(row.user_id), amount=to_str(row.amount), currency=row.currency),
    )
    db.commit()
    return row


def reverse_contribution(db, actor, case_id, entry_id, body):
    case = lock_case(db, case_id)
    require(case, actor, "can_manage")
    source = db.get(FamilyLedgerEntry, entry_id)
    if not source or source.case_id != case.id or source.entry_type != "CONTRIBUTION":
        raise svc.NotFound("Original contribution unavailable.")
    existing = db.scalar(
        select(FamilyLedgerEntry).where(FamilyLedgerEntry.reverses_id == source.id)
    )
    if existing:
        if existing.request_id == body.request_id and existing.note == body.note.strip():
            return existing
        raise svc.DomainError("This contribution already has a reversal.")
    if db.scalar(
        select(FamilyLedgerEntry.id).where(
            FamilyLedgerEntry.case_id == case.id, FamilyLedgerEntry.request_id == body.request_id
        )
    ):
        raise svc.DomainError("Request identifier already used.")
    row = FamilyLedgerEntry(
        case_id=case.id,
        user_id=source.user_id,
        entry_type="REVERSAL",
        amount=source.amount,
        currency=source.currency,
        contributed_on=svc._now().date(),
        reference=source.reference,
        reverses_id=source.id,
        note=svc._require_note(body.note, "Reversal reason"),
        request_id=body.request_id,
        created_by=actor.user_id,
    )
    db.add(row)
    db.flush()
    svc._audit(
        db,
        actor,
        case_id=case.id,
        event_type="FAMILY_CONTRIBUTION_REVERSED",
        entity_type="family_ledger_entry",
        entity_id=row.id,
        details=dict(original_entry_id=str(source.id), amount=to_str(row.amount)),
    )
    db.commit()
    return row


def line_basis(db, line):
    from app.providers import recognized_amount

    amount = recognized_amount(db, line)
    packet = dict(
        id=str(line.id), amount=to_str(amount), status=str(line.status), currency=line.currency
    )
    return amount, hashlib.sha256(json.dumps(packet, sort_keys=True).encode()).hexdigest()


def allocate(db, actor, case_id, body):
    case = lock_case(db, case_id)
    require(case, actor, "can_review")
    line = db.get(BillLineItem, body.line_item_id, populate_existing=True)
    if not line or line.case_id != case.id:
        raise svc.NotFound("Expense unavailable in this episode.")
    amount, fingerprint = line_basis(db, line)
    shares = sorted(
        [dict(user_id=str(s.user_id), amount=to_str(s.amount)) for s in body.shares],
        key=lambda s: s["user_id"],
    )
    note = svc._require_note(body.note, "Allocation note")
    previous = db.scalar(
        select(FamilyAllocationPlan).where(
            FamilyAllocationPlan.case_id == case.id,
            FamilyAllocationPlan.request_id == body.request_id,
        )
    )
    if previous:
        if (
            previous.line_item_id,
            previous.source_fingerprint,
            previous.shares,
            previous.note,
            previous.created_by,
        ) != (line.id, body.source_fingerprint, shares, note, actor.user_id):
            raise svc.DomainError("Request identifier already belongs to a different allocation.")
        return previous
    if fingerprint != body.source_fingerprint:
        raise svc.DomainError("Expense changed. Refresh its current amount before allocating.")
    if line.status != LineItemStatus.ACCEPTED:
        raise svc.DomainError("Review and accept the charge before allocating it.")
    if len({s.user_id for s in body.shares}) != len(body.shares):
        raise svc.ValidationFailed("Allocate one share per person.")
    for share in body.shares:
        _member_can_receive(db, case, share.user_id)
        if share.amount <= ZERO:
            raise svc.ValidationFailed(
                "Allocation shares must be positive; omit a person for zero."
            )
    if sum((s.amount for s in body.shares), ZERO) > amount:
        raise svc.ValidationFailed("Allocated shares cannot exceed the recognized expense amount.")
    version = (
        db.scalar(
            select(func.max(FamilyAllocationPlan.version)).where(
                FamilyAllocationPlan.line_item_id == line.id
            )
        )
        or 0
    )
    row = FamilyAllocationPlan(
        case_id=case.id,
        line_item_id=line.id,
        version=version + 1,
        currency=case.currency,
        source_amount=amount,
        source_fingerprint=fingerprint,
        shares=shares,
        request_id=body.request_id,
        note=note,
        created_by=actor.user_id,
    )
    db.add(row)
    db.flush()
    svc._audit(
        db,
        actor,
        case_id=case.id,
        event_type="FAMILY_EXPENSE_ALLOCATED",
        entity_type="family_allocation_plan",
        entity_id=row.id,
        details=dict(line_item_id=str(line.id), version=row.version, shares=shares),
    )
    db.commit()
    return row


def workspace(db, actor, case_id):
    case = svc.get_case(db, case_id)
    require(case, actor, "can_view")
    own_access = access(case, actor)
    members = list(
        db.scalars(
            select(FamilyMembership)
            .where(FamilyMembership.case_id == case.id)
            .order_by(FamilyMembership.created_at, FamilyMembership.id)
        )
    )
    user_ids = {m.user_id for m in members} | {case.payer_user_id}
    users = {u.id: u for u in db.scalars(select(User).where(User.id.in_(user_ids)))}
    permissions = {
        m.user_id: dict(
            role=m.role, can_review=m.can_review, can_approve=m.can_approve, active=m.active
        )
        for m in members
    }
    permissions.setdefault(
        case.payer_user_id, dict(role="PAYER", can_review=True, can_approve=True, active=True)
    )
    ledger = list(
        db.scalars(
            select(FamilyLedgerEntry)
            .where(FamilyLedgerEntry.case_id == case.id)
            .order_by(FamilyLedgerEntry.created_at, FamilyLedgerEntry.id)
        )
    )
    contributions = {user_id: ZERO for user_id in user_ids}
    for entry in ledger:
        contributions[entry.user_id] += entry.amount * (-1 if entry.entry_type == "REVERSAL" else 1)
    plans = list(
        db.scalars(
            select(FamilyAllocationPlan)
            .where(FamilyAllocationPlan.case_id == case.id)
            .order_by(FamilyAllocationPlan.version, FamilyAllocationPlan.id)
        )
    )
    latest = {plan.line_item_id: plan for plan in plans}
    expenses, assigned = [], {user_id: ZERO for user_id in user_ids}
    from decimal import Decimal

    for line in svc.case_lines(db, case.id):
        amount, fingerprint = line_basis(db, line)
        plan = latest.get(line.id)
        stale = bool(plan and plan.source_fingerprint != fingerprint)
        current = plan.shares if plan and not stale else []
        for share in current:
            assigned[uuid.UUID(share["user_id"])] += Decimal(share["amount"])
        expenses.append(
            dict(
                id=str(line.id),
                description=line.description_raw,
                status=str(line.status),
                amount=to_str(amount),
                source_fingerprint=fingerprint,
                shares=current,
                allocation_stale=stale,
                allocation_version=plan.version if plan else None,
                unallocated=to_str(amount - sum((Decimal(s["amount"]) for s in current), ZERO)),
            )
        )
    notifications = list(
        db.scalars(
            select(FamilyNotification)
            .where(
                FamilyNotification.case_id == case.id, FamilyNotification.user_id == actor.user_id
            )
            .order_by(FamilyNotification.created_at.desc(), FamilyNotification.id)
            .limit(100)
        )
    )
    invitations = (
        list(
            db.scalars(
                select(FamilyInvitation)
                .where(FamilyInvitation.case_id == case.id)
                .order_by(FamilyInvitation.created_at.desc())
            )
        )
        if own_access["can_manage"]
        else []
    )

    def project(row, names):
        return {name: getattr(row, name) for name in names.split()}

    return dict(
        case_id=str(case.id),
        currency=case.currency,
        actor_id=str(actor.user_id),
        access=own_access,
        total_contributions=to_str(sum(contributions.values(), ZERO)),
        members=[
            dict(
                user_id=str(user_id),
                display_name=users[user_id].display_name,
                is_owner=user_id == case.payer_user_id,
                **permissions[user_id],
                contributions=to_str(contributions[user_id]),
                allocated_expenses=to_str(assigned[user_id]),
                contribution_minus_allocation=to_str(contributions[user_id] - assigned[user_id]),
            )
            for user_id in sorted(user_ids, key=str)
        ],
        invitations=[
            dict(
                **project(
                    row,
                    "id recipient_email role can_review can_approve "
                    "expires_at accepted_at revoked_at",
                ),
                expired=row.expires_at <= svc._now(),
            )
            for row in invitations
        ],
        ledger=[
            {
                **project(
                    row,
                    "id user_id entry_type currency contributed_on reference "
                    "reverses_id note created_by created_at",
                ),
                "amount": to_str(row.amount),
            }
            for row in ledger
        ],
        expenses=expenses,
        allocation_history=[
            {
                **project(p, "id line_item_id version shares note created_by created_at"),
                "source_amount": to_str(p.source_amount),
            }
            for p in plans
        ],
        notifications=[
            project(n, "id event_type actor_label created_at read_at") for n in notifications
        ],
        history=[
            project(e, "id event_type actor_label created_at entity_type")
            for e in svc.case_audit(db, case.id)
        ],
    )


def mark_read(db, actor, case_id, notification_id):
    case = svc.get_case(db, case_id)
    require(case, actor, "can_view")
    row = db.get(FamilyNotification, notification_id)
    if not row or row.case_id != case.id or row.user_id != actor.user_id:
        raise svc.NotFound("Notification unavailable.")
    if row.read_at is None:
        row.read_at = svc._now()
        db.commit()
