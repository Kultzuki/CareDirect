"""Provider capabilities are query scoped; payer decisions use the case authorization."""

import uuid

from fastapi import APIRouter, Response, status

from app import providers
from app.api.cases import DB, ActorDep
from app.schemas import (
    NoteBody,
    ProviderDecisionCreate,
    ProviderDecisionOut,
    ProviderLinkCreate,
    ProviderLinkHistoryOut,
    ProviderLinkOut,
    ProviderPortalOut,
    ProviderPortalResponseOut,
    ProviderPreviewOut,
    ProviderResponseCreate,
    ProviderWorkflowOut,
)

router = APIRouter(prefix="/api")


def _private(response: Response):
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"


@router.post(
    "/flags/{flag_id}/provider-links",
    response_model=ProviderLinkOut,
    status_code=status.HTTP_201_CREATED,
)
def create_link(
    flag_id: uuid.UUID, body: ProviderLinkCreate, db: DB, actor: ActorDep, response: Response
):
    row, token = providers.create_link(
        db, actor, flag_id, body.line_item_id, body.question, body.ttl_minutes
    )
    _private(response)
    return ProviderLinkOut(
        id=row.id,
        case_id=row.case_id,
        flag_id=row.flag_id,
        line_item_id=row.line_item_id,
        token=token,
        expires_at=row.expires_at,
    )


@router.post("/provider-links/{link_id}/revoke", response_model=ProviderLinkHistoryOut)
def revoke_link(link_id: uuid.UUID, body: NoteBody, db: DB, actor: ActorDep, response: Response):
    _private(response)
    return providers.revoke_link(db, actor, link_id, body.note)


@router.get("/provider/respond/{token}", response_model=ProviderPortalOut)
def portal(token: str, db: DB, response: Response):
    _private(response)
    return providers.portal(db, token)


@router.post(
    "/provider/respond/{token}",
    response_model=ProviderPortalResponseOut,
    status_code=status.HTTP_201_CREATED,
)
def respond(token: str, body: ProviderResponseCreate, db: DB, response: Response):
    _private(response)
    return providers.respond(
        db,
        token,
        body.response_type,
        body.response_text,
        body.responder_label,
        body.corrected_amount,
    )


@router.get("/cases/{case_id}/provider-workflow", response_model=ProviderWorkflowOut)
def workflow(case_id: uuid.UUID, db: DB, actor: ActorDep, response: Response):
    _private(response)
    return providers.workflow(db, actor, case_id)


@router.get("/provider-responses/{response_id}/preview", response_model=ProviderPreviewOut)
def preview(response_id: uuid.UUID, db: DB, actor: ActorDep, response: Response):
    _private(response)
    return providers.preview(db, actor, response_id)


@router.post(
    "/provider-responses/{response_id}/decision",
    response_model=ProviderDecisionOut,
    status_code=status.HTTP_201_CREATED,
)
def decide(
    response_id: uuid.UUID,
    body: ProviderDecisionCreate,
    db: DB,
    actor: ActorDep,
    response: Response,
):
    _private(response)
    return providers.decide(
        db, actor, response_id, body.decision, body.note, body.state_fingerprint
    )
