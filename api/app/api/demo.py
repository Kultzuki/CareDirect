"""Bounded synthetic demo entry. Fresh cases preserve every previous case and audit."""

import hashlib
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, text

from app import services as svc
from app.api.cases import DB, ActorDep
from app.config import get_settings
from app.demo_samples import SAMPLE_NAMES, sample_bytes
from app.documents.service import UploadLimits, create_upload_link, receive_upload
from app.documents.storage import PrivateStorage, get_storage
from app.errors import Forbidden, NotFound
from app.extraction.adapter import MockExtractionAdapter
from app.extraction.service import extract_document
from app.models import CareCase, DocumentExtraction, EvidenceDocument, User
from app.schemas import UserOut
from app.states import DocumentType, UserRole

router = APIRouter(prefix="/api/demo")
PRIVATE = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}


def allowed():
    if get_settings().app_env not in ("development", "test", "demo"):
        raise Forbidden("Synthetic demo is disabled.")


@router.get("/identity", response_model=UserOut)
def identity(db: DB):
    allowed()
    payer = db.scalar(
        select(User).where(
            User.email == "payer@demo.invalid", User.role == UserRole.PAYER, User.is_demo.is_(True)
        )
    )
    if payer is None:
        raise NotFound("The designated synthetic payer has not been seeded.")
    return payer


@router.get("/samples/{filename}")
def sample(filename: str, actor: ActorDep):
    allowed()
    if not actor.user.is_demo or actor.user.role != UserRole.PAYER:
        raise Forbidden("Synthetic samples require a demo payer.")
    if filename not in SAMPLE_NAMES:
        raise NotFound("Unknown synthetic sample.")
    content, mime = sample_bytes(filename)
    return Response(
        content,
        media_type=mime,
        headers={**PRIVATE, "Content-Disposition": f'attachment; filename="{filename}"'},
    )


class RunBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["EMPTY", "PREPARED"]
    request_id: uuid.UUID


@router.post("/runs", status_code=201)
def fresh_run(
    body: RunBody, db: DB, actor: ActorDep, storage: Annotated[PrivateStorage, Depends(get_storage)]
):
    allowed()
    if not actor.user.is_demo or actor.user.role != UserRole.PAYER:
        raise Forbidden("Fresh runs require a synthetic demo payer.")
    lock_key = int.from_bytes(
        hashlib.sha256(f"{actor.user_id}:{body.request_id}".encode()).digest()[:8],
        "big",
        signed=True,
    )
    # Dedicated connection retains the session-level lock across service commits.
    # Only the lead runs DB work; deployed demo is bounded to one synthetic workspace.
    with db.get_bind().engine.connect() as guard:
        guard.execute(text("SELECT pg_advisory_lock(:key)"), {"key": lock_key})
        try:
            return _prepare_run(body, db, actor, storage)
        finally:
            guard.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": lock_key})


def _prepare_run(body, db, actor, storage):
    # Serialize case creation for this payer, with a deterministic unique reference.
    # Replaying the same request cannot create another case. No existing case is reset.
    db.scalar(select(User).where(User.id == actor.user.id).with_for_update())
    reference = f"DEMO-{body.mode[0]}-{body.request_id.hex}"
    case = db.scalar(select(CareCase).where(CareCase.case_reference == reference))
    if case is not None:
        svc._require_payer(case, actor)
    else:
        case = svc.create_case(
            db,
            actor,
            patient_alias="Synthetic Harbor family",
            currency="USD",
            case_reference=reference,
            is_demo=True,
        )
    db.commit()
    if body.mode == "PREPARED":
        settings = get_settings()
        for filename, kind in [
            ("usd_bill.pdf", DocumentType.BILL),
            ("usd_estimate.pdf", DocumentType.ESTIMATE),
            ("usd_receipt.pdf", DocumentType.RECEIPT),
        ]:
            content, mime = sample_bytes(filename)
            digest = hashlib.sha256(content).hexdigest()
            doc = db.scalar(
                select(EvidenceDocument).where(
                    EvidenceDocument.case_id == case.id, EvidenceDocument.sha256 == digest
                )
            )
            if doc is None:
                _, token = create_upload_link(db, actor, case.id, [kind], max_uploads=1)
                doc, _ = receive_upload(
                    db,
                    storage,
                    UploadLimits(settings.max_upload_bytes, settings.max_upload_pages),
                    token,
                    kind,
                    mime,
                    content,
                )
            extraction = db.scalar(
                select(DocumentExtraction).where(DocumentExtraction.document_id == doc.id)
            )
            if extraction is None:
                extract_document(db, actor, storage, MockExtractionAdapter(), doc.id)
        # No promote, line acceptance, receipt matching or provider/payment approval here.
    return {
        "case_id": str(case.id),
        "case_reference": case.case_reference,
        "mode": body.mode,
        "synthetic": True,
    }
