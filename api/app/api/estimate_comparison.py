"""Authorized read-only comparison of two evidence documents within one case."""

import uuid

from fastapi import APIRouter
from sqlalchemy import select

from app.api.cases import DB, ActorDep, _visible_case
from app.errors import ValidationFailed
from app.extraction.service import _load
from app.models import DocumentExtraction, EvidenceDocument
from app.reconciliation.estimate_comparison import compare, snapshot
from app.states import DocumentType, ExtractionStatus

router = APIRouter(prefix="/api/cases", tags=["estimate-comparison"])


@router.get("/{case_id}/estimate-comparison")
def estimate_comparison(
    case_id: uuid.UUID,
    db: DB,
    actor: ActorDep,
    estimate_document_id: uuid.UUID | None = None,
    final_document_id: uuid.UUID | None = None,
):
    _visible_case(db, actor, case_id)
    docs = list(
        db.scalars(
            select(EvidenceDocument)
            .where(
                EvidenceDocument.case_id == case_id,
                EvidenceDocument.document_type.in_([DocumentType.ESTIMATE, DocumentType.BILL]),
            )
            .order_by(EvidenceDocument.created_at, EvidenceDocument.id)
        )
    )
    choices = [
        {
            "id": str(d.id),
            "document_type": str(d.document_type),
            "extraction_status": str(d.extraction_status),
            "created_at": d.created_at.isoformat(),
        }
        for d in docs
    ]

    selected = []
    extraction_modes = {}
    for kind, requested in (
        (DocumentType.ESTIMATE, estimate_document_id),
        (DocumentType.BILL, final_document_id),
    ):
        eligible = [d for d in docs if d.document_type == kind]
        if requested is not None:
            eligible = [d for d in eligible if d.id == requested]
            if not eligible:
                raise ValidationFailed("Select a document of the required type from this case.")
        if len(eligible) != 1:
            return {
                "status": "select_documents",
                "documents": choices,
                "rows": [],
                "summary": "Upload an estimate and final bill, then select one of each.",
            }
        doc = eligible[0]
        row = db.scalar(select(DocumentExtraction).where(DocumentExtraction.document_id == doc.id))
        if row is None or doc.extraction_status != ExtractionStatus.EXTRACTED:
            return {
                "status": "awaiting_extraction",
                "documents": choices,
                "rows": [],
                "summary": "Extract both selected documents in Review documents first.",
            }
        selected.append(snapshot(_load(db, row)))
        extraction_modes[str(kind)] = row.provider
    return {**compare(*selected), "documents": choices, "extraction_providers": extraction_modes}
