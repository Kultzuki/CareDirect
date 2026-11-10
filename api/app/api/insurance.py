"""Authorized, case-scoped insurance evidence comparison and explicit explanation."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.cases import DB, ActorDep, _visible_case
from app.insurance import ExplainRequest, ReviewRequest, Selection, confirm_review, reconcile
from app.insurance_explanation import explain

router = APIRouter(prefix="/api/cases", tags=["insurance"])


@router.get("/{case_id}/insurance")
def get_insurance(
    case_id: uuid.UUID,
    db: DB,
    actor: ActorDep,
    bill_id: uuid.UUID | None = None,
    preauth_id: uuid.UUID | None = None,
    settlement_id: uuid.UUID | None = None,
    insurer_payment_ids: Annotated[list[uuid.UUID] | None, Query()] = None,
    select_documents: bool = False,
):
    case = _visible_case(db, actor, case_id)
    selection = (
        Selection(
            bill_id=bill_id,
            preauth_id=preauth_id,
            settlement_id=settlement_id,
            insurer_payment_ids=insurer_payment_ids or [],
        )
        if select_documents
        else None
    )
    from app.family import access

    result = reconcile(db, case, selection)
    result["can_review"] = access(case, actor)["can_review"]
    return result


@router.post("/{case_id}/insurance/review")
def review_insurance(case_id: uuid.UUID, body: ReviewRequest, db: DB, actor: ActorDep):
    return confirm_review(db, actor, case_id, body)


@router.post("/{case_id}/insurance/explain")
def explain_insurance(case_id: uuid.UUID, body: ExplainRequest, db: DB, actor: ActorDep):
    return explain(db, actor, case_id, body)
