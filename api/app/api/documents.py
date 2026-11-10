"""Document intake API. No endpoint here creates, sends or executes a payment.

Uploads authenticate with the upload token in the URL path, not with the demo identity header.
Everything else uses the same demo identity as the case API.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from starlette.concurrency import run_in_threadpool

from app.api.cases import DB, ActorDep, _visible_case
from app.documents import service as docs
from app.documents.storage import PrivateStorage, get_storage
from app.documents.validation import ALLOWED_MIME, too_large
from app.errors import NotFound
from app.extraction import service as extraction
from app.extraction.adapter import ExtractionAdapter, get_extraction_adapter
from app.schemas import (
    BillOut,
    DocumentOut,
    ExternalPaymentOut,
    ExtractionViewOut,
    PromoteOut,
    RevisionCreate,
    UploadLinkCreate,
    UploadLinkInfoOut,
    UploadLinkOut,
    UploadReceiptOut,
)
from app.states import DocumentType

router = APIRouter(prefix="/api")

Storage = Annotated[PrivateStorage, Depends(get_storage)]
Limits = Annotated[docs.UploadLimits, Depends(docs.get_upload_limits)]
Adapter = Annotated[ExtractionAdapter, Depends(get_extraction_adapter)]

_NO_STORE = "no-store"


def _remaining(row) -> int:
    return row.max_uploads - row.use_count


# ---------------------------------------------------------------- upload links


@router.post(
    "/cases/{case_id}/upload-links",
    response_model=UploadLinkOut,
    status_code=status.HTTP_201_CREATED,
)
def create_upload_link(
    case_id: uuid.UUID, body: UploadLinkCreate, response: Response, db: DB, actor: ActorDep
):
    row, token = docs.create_upload_link(
        db, actor, case_id, body.document_types, body.max_uploads, body.ttl_minutes
    )
    response.headers["Cache-Control"] = _NO_STORE
    return UploadLinkOut(
        id=row.id,
        case_id=row.case_id,
        token=token,
        document_types=row.document_types,
        max_uploads=row.max_uploads,
        expires_at=row.expires_at,
    )


@router.get("/uploads/{token}", response_model=UploadLinkInfoOut)
def upload_link_info(token: str, response: Response, db: DB, limits: Limits):
    row = docs.upload_link_info(db, token)
    response.headers["Cache-Control"] = _NO_STORE
    return UploadLinkInfoOut(
        document_types=row.document_types,
        uploads_remaining=_remaining(row),
        expires_at=row.expires_at,
        max_upload_bytes=limits.max_bytes,
        max_pages=limits.max_pages,
        allowed_mime_types=list(ALLOWED_MIME),
    )


@router.post(
    "/uploads/{token}",
    response_model=UploadReceiptOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    token: str,
    document_type: DocumentType,
    request: Request,
    response: Response,
    db: DB,
    storage: Storage,
    limits: Limits,
):
    """The request body is the raw file; `Content-Type` is its declared type. No file name is
    received or stored."""
    # Refuse a bad link before reading any of the body.
    await run_in_threadpool(docs.check_upload_allowed, db, token, document_type)

    declared_length = request.headers.get("content-length", "")
    if declared_length.isdigit() and int(declared_length) > limits.max_bytes:
        raise too_large(limits.max_bytes)
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > limits.max_bytes:
            raise too_large(limits.max_bytes)

    doc, row = await run_in_threadpool(
        docs.receive_upload,
        db,
        storage,
        limits,
        token,
        document_type,
        request.headers.get("content-type"),
        bytes(body),
    )
    response.headers["Cache-Control"] = _NO_STORE
    return UploadReceiptOut(
        document_id=doc.id,
        document_type=doc.document_type,
        mime_type=doc.mime_type,
        file_size=doc.file_size,
        page_count=doc.page_count,
        sha256=doc.sha256,
        uploads_remaining=_remaining(row),
    )


# ---------------------------------------------------------------- documents


@router.get("/cases/{case_id}/documents", response_model=list[DocumentOut])
def list_documents(case_id: uuid.UUID, db: DB, actor: ActorDep):
    _visible_case(db, actor, case_id)
    return docs.case_documents(db, case_id)


@router.get("/documents/{document_id}", response_model=DocumentOut)
def get_document(document_id: uuid.UUID, db: DB, actor: ActorDep):
    doc = docs.get_document(db, document_id)
    _visible_case(db, actor, doc.case_id)
    return doc


@router.get("/documents/{document_id}/content")
def private_document_content(document_id: uuid.UUID, db: DB, actor: ActorDep, storage: Storage):
    """Private payer-authorized original. Providers receive only selected line excerpts."""
    doc = docs.get_document(db, document_id)
    _visible_case(db, actor, doc.case_id)
    try:
        content = storage.get(doc.storage_key)
    except FileNotFoundError as exc:
        raise NotFound("The source file is unavailable. Ask for a new synthetic copy.") from exc
    return Response(
        content=content,
        media_type=doc.mime_type,
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "Content-Disposition": "inline; filename=source-document",
            "Content-Security-Policy": "sandbox; default-src 'none'; frame-ancestors 'self'",
        },
    )


# ---------------------------------------------------------------- extraction


@router.post(
    "/documents/{document_id}/extract",
    response_model=ExtractionViewOut,
    status_code=status.HTTP_201_CREATED,
)
def extract_document(
    document_id: uuid.UUID, db: DB, actor: ActorDep, storage: Storage, adapter: Adapter
):
    row = extraction.extract_document(db, actor, storage, adapter, document_id)
    return extraction.extraction_view(db, row)


@router.get("/documents/{document_id}/extraction", response_model=ExtractionViewOut)
def get_extraction(document_id: uuid.UUID, db: DB, actor: ActorDep):
    doc = docs.get_document(db, document_id)
    _visible_case(db, actor, doc.case_id)
    return extraction.extraction_view(db, extraction.extraction_for_document(db, doc.id))


@router.post(
    "/extractions/{extraction_id}/revisions",
    response_model=ExtractionViewOut,
    status_code=status.HTTP_201_CREATED,
)
def add_revision(extraction_id: uuid.UUID, body: RevisionCreate, db: DB, actor: ActorDep):
    corrections = [
        extraction.CorrectionInput(
            path=c.path,
            value=c.value,
            source=None if c.source is None else c.source.model_dump(),
        )
        for c in body.corrections
    ]
    extraction.add_revision(
        db, actor, extraction_id, corrections, body.confirmed_paths, body.reason
    )
    return extraction.extraction_view(db, extraction.get_extraction(db, extraction_id))


@router.post(
    "/extractions/{extraction_id}/promote",
    response_model=PromoteOut,
    status_code=status.HTTP_201_CREATED,
)
def promote_extraction(extraction_id: uuid.UUID, db: DB, actor: ActorDep):
    bill, payment = extraction.promote_extraction(db, actor, extraction_id)
    return PromoteOut(
        bill=None if bill is None else BillOut.model_validate(bill),
        external_payment=None if payment is None else ExternalPaymentOut.model_validate(payment),
    )
