"""Shared episode membership, internal contributions and notifications. No remote delivery."""

import uuid
from typing import Annotated

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app import family
from app import services as svc
from app.api.cases import DB, ActorDep
from app.config import get_settings
from app.states import UserRole

router = APIRouter(prefix="/api")


@router.get("/cases/{case_id}/family")
def get_family(case_id: uuid.UUID, db: DB, actor: ActorDep):
    return family.workspace(db, actor, case_id)


@router.post("/cases/{case_id}/family/invitations", status_code=201)
def invite(case_id: uuid.UUID, body: family.InviteRequest, db: DB, actor: ActorDep):
    return family.invite(db, actor, case_id, body)


@router.get("/family/invitations/{token}")
def invitation(token: str, db: DB, actor: ActorDep):
    row = family.invitation(db, actor, token)
    return dict(
        role=row.role,
        can_review=row.can_review,
        can_approve=row.can_approve,
        expires_at=row.expires_at,
        accepted=row.accepted_by is not None,
    )


@router.post("/family/invitations/{token}/accept")
def accept(token: str, db: DB, actor: ActorDep):
    return family.accept_invitation(db, actor, token)


@router.post("/cases/{case_id}/family/invitations/{invitation_id}/revoke")
def revoke(case_id: uuid.UUID, invitation_id: uuid.UUID, db: DB, actor: ActorDep):
    family.revoke_invitation(db, actor, case_id, invitation_id)
    return dict(revoked=True)


@router.post("/cases/{case_id}/family/members/{user_id}")
def member(
    case_id: uuid.UUID, user_id: uuid.UUID, body: family.MemberRequest, db: DB, actor: ActorDep
):
    family.change_member(db, actor, case_id, user_id, body)
    return family.workspace(db, actor, case_id)


@router.post("/cases/{case_id}/family/contributions", status_code=201)
def contribute(case_id: uuid.UUID, body: family.ContributionRequest, db: DB, actor: ActorDep):
    row = family.contribute(db, actor, case_id, body)
    return dict(id=str(row.id), amount=family.to_str(row.amount), currency=row.currency)


@router.post("/cases/{case_id}/family/contributions/{entry_id}/reverse", status_code=201)
def reverse(
    case_id: uuid.UUID, entry_id: uuid.UUID, body: family.ReversalRequest, db: DB, actor: ActorDep
):
    row = family.reverse_contribution(db, actor, case_id, entry_id, body)
    return dict(id=str(row.id), amount=family.to_str(row.amount), currency=row.currency)


@router.post("/cases/{case_id}/family/allocations", status_code=201)
def allocate(case_id: uuid.UUID, body: family.AllocationRequest, db: DB, actor: ActorDep):
    row = family.allocate(db, actor, case_id, body)
    return dict(id=str(row.id), version=row.version)


@router.post("/cases/{case_id}/family/notifications/{notification_id}/read")
def read_notification(case_id: uuid.UUID, notification_id: uuid.UUID, db: DB, actor: ActorDep):
    family.mark_read(db, actor, case_id, notification_id)
    return dict(read=True)


class DemoMember(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: Annotated[str, Field(min_length=1, max_length=120)]
    email: Annotated[str, Field(min_length=3, max_length=254)]

    @field_validator("email")
    @classmethod
    def valid_email(cls, value):
        return family.InviteRequest.email(value)


@router.post("/cases/{case_id}/family/demo-identities", status_code=201)
def demo_identity(case_id: uuid.UUID, body: DemoMember, db: DB, actor: ActorDep):
    """Local synthetic role walkthrough only. This never sends an invitation or email."""
    case = family.lock_case(db, case_id)
    family.require(case, actor, "can_manage")
    if get_settings().app_env not in ("development", "test", "demo") or not actor.user.is_demo:
        raise svc.Forbidden("Local synthetic identity setup is unavailable.")
    email = body.email
    if not email.endswith(".invalid"):
        raise svc.ValidationFailed("Use a synthetic .invalid email for the local demo identity.")
    from sqlalchemy import func, select

    from app.models import User

    if db.scalar(select(User.id).where(func.lower(User.email) == email)):
        raise svc.DomainError("A local identity already uses this email.")
    row = svc.create_user(
        db, body.display_name.strip(), UserRole.RELATIVE, email=email, is_demo=True
    )
    db.commit()
    return dict(id=str(row.id), display_name=row.display_name, email=row.email)
