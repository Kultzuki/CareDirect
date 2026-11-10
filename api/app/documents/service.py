"""Upload links and token-scoped document intake.

A relative or provider uploads through a link the payer created. The link is a random token;
only its SHA-256 is stored. A token is scoped to one case, a set of document types, a number
of uploads and an expiry. Every token failure returns the same message, so a caller cannot
tell a wrong token from an expired or used-up one.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import services as svc
from app.config import get_settings
from app.documents.storage import PrivateStorage
from app.documents.validation import validate_upload
from app.errors import DomainError, Forbidden, NotFound, ValidationFailed
from app.models import EvidenceDocument, UploadToken
from app.states import CaseStatus, DataSource, DocumentType, UserRole

INVALID_LINK = "upload link is invalid or expired"
UPLOADABLE_TYPES = (
    DocumentType.BILL,
    DocumentType.ESTIMATE,
    DocumentType.RECEIPT,
    DocumentType.INSURANCE_PREAUTH,
    DocumentType.INSURANCE_SETTLEMENT,
    DocumentType.INSURER_PAYMENT,
)
MAX_LINK_UPLOADS = 50

_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")


@dataclass(frozen=True)
class UploadLimits:
    max_bytes: int
    max_pages: int


def get_upload_limits() -> UploadLimits:
    """FastAPI dependency. Tests override it to exercise the size limit with small files."""
    settings = get_settings()
    return UploadLimits(max_bytes=settings.max_upload_bytes, max_pages=settings.max_upload_pages)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


# ---------------------------------------------------------------- upload links


def create_upload_link(
    db: Session,
    actor: svc.Actor,
    case_id: uuid.UUID,
    document_types: list[DocumentType] | list[str],
    max_uploads: int = 5,
    ttl_minutes: int | None = None,
) -> tuple[UploadToken, str]:
    """Create a scoped upload link. The raw token is returned once and never stored."""
    case = svc._lock_case(db, case_id)
    svc._require_reviewer(case, actor)
    if case.status == CaseStatus.CLOSED:
        raise DomainError("a closed case does not accept uploads")

    try:
        types = [DocumentType(t) for t in document_types]
    except ValueError:
        raise ValidationFailed("unknown document type") from None
    if not types:
        raise ValidationFailed("choose at least one document type")
    if len(set(types)) != len(types):
        raise ValidationFailed("document types must not repeat")
    if any(t not in UPLOADABLE_TYPES for t in types):
        raise ValidationFailed("an upload link may allow only BILL, ESTIMATE and RECEIPT")
    if not 1 <= max_uploads <= MAX_LINK_UPLOADS:
        raise ValidationFailed(f"max uploads must be between 1 and {MAX_LINK_UPLOADS}")

    settings = get_settings()
    ttl = settings.upload_token_ttl_minutes if ttl_minutes is None else ttl_minutes
    if not 1 <= ttl <= settings.upload_token_max_ttl_minutes:
        raise ValidationFailed(
            f"link lifetime must be between 1 and {settings.upload_token_max_ttl_minutes} minutes"
        )

    token = secrets.token_urlsafe(32)
    row = UploadToken(
        id=uuid.uuid4(),
        case_id=case.id,
        token_sha256=hash_token(token),
        document_types=[str(t) for t in types],
        max_uploads=max_uploads,
        expires_at=svc._now() + timedelta(minutes=ttl),
        created_by=actor.user_id,
    )
    db.add(row)
    db.flush()
    svc._audit(
        db,
        actor,
        case_id=case.id,
        event_type="UPLOAD_LINK_CREATED",
        entity_type="upload_token",
        entity_id=row.id,
        after={
            "document_types": row.document_types,
            "max_uploads": max_uploads,
            "expires_at": row.expires_at.isoformat(),
        },
    )
    db.commit()
    return row, token


def _load_token(db: Session, token: str, *, now: datetime, lock: bool) -> UploadToken:
    if not _TOKEN_RE.fullmatch(token):
        raise Forbidden(INVALID_LINK)
    stmt = select(UploadToken).where(UploadToken.token_sha256 == hash_token(token))
    if lock:
        # Re-read the row after the lock is granted, even if an earlier unlocked check loaded
        # it in this session: a concurrent upload may have used the last slot meanwhile.
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    row = db.execute(stmt).scalar_one_or_none()
    if row is None or row.expires_at <= now or row.use_count >= row.max_uploads:
        raise Forbidden(INVALID_LINK)
    return row


def upload_link_info(db: Session, token: str, *, now: datetime | None = None) -> UploadToken:
    """Check a link without using up an upload and without writing anything."""
    return _load_token(db, token, now=now or svc._now(), lock=False)


def check_upload_allowed(
    db: Session, token: str, document_type: DocumentType, *, now: datetime | None = None
) -> None:
    """Cheap pre-check so a bad link is refused before the file body is read."""
    row = upload_link_info(db, token, now=now)
    if str(document_type) not in row.document_types:
        raise Forbidden(INVALID_LINK)


# ---------------------------------------------------------------- intake


def receive_upload(
    db: Session,
    storage: PrivateStorage,
    limits: UploadLimits,
    token: str,
    document_type: DocumentType,
    declared_mime: str | None,
    content: bytes,
    *,
    now: datetime | None = None,
) -> tuple[EvidenceDocument, UploadToken]:
    """Validate and store one uploaded file under the token's case."""
    now = now or svc._now()
    row = _load_token(db, token, now=now, lock=True)
    if str(document_type) not in row.document_types:
        raise Forbidden(INVALID_LINK)
    case = svc._lock_case(db, row.case_id)
    if case.status == CaseStatus.CLOSED:
        raise DomainError("a closed case does not accept uploads")

    checked = validate_upload(
        content, declared_mime, max_bytes=limits.max_bytes, max_pages=limits.max_pages
    )
    already = db.scalar(
        select(EvidenceDocument.id).where(
            EvidenceDocument.case_id == case.id, EvidenceDocument.sha256 == checked.sha256
        )
    )
    if already is not None:
        raise DomainError("this file was already uploaded to this case")

    key = storage.new_key(case.id)
    storage.put(key, content)
    try:
        # The savepoint keeps a failed insert from leaving half-written rows in the session.
        with db.begin_nested():
            doc = EvidenceDocument(
                id=uuid.uuid4(),
                case_id=case.id,
                document_type=document_type,
                storage_key=key,
                sha256=checked.sha256,
                mime_type=checked.mime_type,
                file_size=checked.file_size,
                page_count=checked.page_count,
                source_type=DataSource.MANUAL_ENTRY,
                uploaded_by=None,
                uploaded_by_role=UserRole.RELATIVE,
            )
            db.add(doc)
            db.flush()
            row.use_count += 1
            row.last_used_at = now
            svc._audit(
                db,
                svc.Actor(user=None, label=f"upload-link:{row.id}"),
                case_id=case.id,
                event_type="DOCUMENT_UPLOADED",
                entity_type="evidence_document",
                entity_id=doc.id,
                after={
                    "document_type": str(document_type),
                    "mime_type": checked.mime_type,
                    "file_size": checked.file_size,
                    "page_count": checked.page_count,
                    "sha256_prefix": checked.sha256[:12],
                    "upload_token_id": str(row.id),
                },
            )
        db.commit()
    except Exception:
        # The file is removed if the record could not be written; it was never referenced.
        storage.discard(key)
        raise
    return doc, row


# ---------------------------------------------------------------- reads


def case_documents(db: Session, case_id: uuid.UUID) -> list[EvidenceDocument]:
    return list(
        db.scalars(
            select(EvidenceDocument)
            .where(EvidenceDocument.case_id == case_id)
            .order_by(EvidenceDocument.created_at, EvidenceDocument.id)
        )
    )


def get_document(db: Session, document_id: uuid.UUID) -> EvidenceDocument:
    doc = db.get(EvidenceDocument, document_id)
    if doc is None:
        raise NotFound(f"document {document_id} not found")
    return doc
