"""Prompt 4 records: upload tokens, immutable extractions and append-only revisions.
The triggers in migration 0003 are tested directly with raw SQL as well as through the ORM."""

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app import services as svc
from app.errors import ImmutableRecordError
from app.models import DocumentExtraction, EvidenceDocument, ExtractionRevision, UploadToken
from app.seed import seed
from app.states import DataSource, DocumentType, UserRole

IMMUTABLE = "append-only|immutable"


@pytest.fixture
def demo(db):
    case = seed(db)
    actor = svc.Actor(user=case.payer, label="PAYER:demo")
    return case, actor


def _hex() -> str:
    return hashlib.sha256(uuid.uuid4().bytes).hexdigest()


def _flush_fails(db, obj, exc=IntegrityError):
    nested = db.begin_nested()
    db.add(obj)
    with pytest.raises(exc):
        db.flush()
    nested.rollback()


def _doc(case) -> EvidenceDocument:
    return EvidenceDocument(
        case_id=case.id,
        document_type=DocumentType.BILL,
        storage_key=f"cases/{case.id}/{uuid.uuid4().hex}",
        sha256=_hex(),
        mime_type="application/pdf",
        file_size=1024,
        page_count=1,
        source_type=DataSource.MANUAL_ENTRY,
        uploaded_by_role=UserRole.RELATIVE,
    )


def _extraction(case, doc, **kw) -> DocumentExtraction:
    data = {
        "document_id": doc.id,
        "case_id": case.id,
        "schema_version": "caredirect.extraction.v1",
        "provider": "mock",
        "model": "mock-replay-v1",
        "prompt_version": "none",
        "payload": {"schema_version": "caredirect.extraction.v1"},
        "raw_output_sha256": _hex(),
        "actor_label": "PAYER:demo",
    }
    data.update(kw)
    return DocumentExtraction(**data)


def _revision(case, extraction, actor, **kw) -> ExtractionRevision:
    data = {
        "extraction_id": extraction.id,
        "case_id": case.id,
        "revision_number": 1,
        "corrections": [],
        "confirmed_paths": ["provider_identifier"],
        "reason": "Checked against the paper bill",
        "created_by": actor.user_id,
        "actor_label": actor.label,
    }
    data.update(kw)
    return ExtractionRevision(**data)


def _token(case, actor, **kw) -> UploadToken:
    data = {
        "case_id": case.id,
        "token_sha256": _hex(),
        "document_types": ["BILL"],
        "max_uploads": 3,
        "expires_at": datetime.now(UTC) + timedelta(hours=1),
        "created_by": actor.user_id,
    }
    data.update(kw)
    return UploadToken(**data)


@pytest.fixture
def extraction(db, demo):
    case, _ = demo
    doc = _doc(case)
    db.add(doc)
    db.flush()
    ex = _extraction(case, doc)
    db.add(ex)
    db.flush()
    return ex


def _sql_refused(db, sql, **params):
    nested = db.begin_nested()
    with pytest.raises(DBAPIError, match=IMMUTABLE):
        db.execute(text(sql), params)
    nested.rollback()


# ---------------------------------------------------------------- document_extractions


def test_extraction_row_is_stored(db, demo, extraction):
    assert extraction.id is not None
    assert extraction.payload == {"schema_version": "caredirect.extraction.v1"}
    assert extraction.created_at is not None


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE document_extractions SET provider = 'other'",
        "UPDATE document_extractions SET payload = '{}'::jsonb",
        "DELETE FROM document_extractions",
    ],
)
def test_extraction_update_and_delete_refused_by_trigger(db, extraction, sql):
    _sql_refused(db, sql)


def test_extraction_orm_guard(db, extraction):
    extraction.payload = {"changed": True}
    with pytest.raises(ImmutableRecordError):
        db.flush()
    db.rollback()


def test_extraction_orm_delete_guard(db, extraction):
    db.delete(extraction)
    with pytest.raises(ImmutableRecordError):
        db.flush()
    db.rollback()


def test_second_extraction_for_the_same_document_refused(db, demo, extraction):
    case, _ = demo
    doc = db.get(EvidenceDocument, extraction.document_id)
    _flush_fails(db, _extraction(case, doc))


def test_extraction_hash_must_be_hex(db, demo):
    case, _ = demo
    doc = _doc(case)
    db.add(doc)
    db.flush()
    _flush_fails(db, _extraction(case, doc, raw_output_sha256="not-a-hash"))


# ---------------------------------------------------------------- extraction_revisions


def test_revision_is_stored_and_never_touches_the_extraction(db, demo, extraction):
    case, actor = demo
    before = dict(extraction.payload)
    rev = _revision(case, extraction, actor)
    db.add(rev)
    db.flush()
    assert rev.revision_number == 1
    assert extraction.payload == before


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE extraction_revisions SET reason = 'changed'",
        "DELETE FROM extraction_revisions",
    ],
)
def test_revision_update_and_delete_refused_by_trigger(db, demo, extraction, sql):
    case, actor = demo
    db.add(_revision(case, extraction, actor))
    db.flush()
    _sql_refused(db, sql)


def test_revision_orm_guard(db, demo, extraction):
    case, actor = demo
    rev = _revision(case, extraction, actor)
    db.add(rev)
    db.flush()
    rev.reason = "rewritten"
    with pytest.raises(ImmutableRecordError):
        db.flush()
    db.rollback()


def test_duplicate_revision_number_refused(db, demo, extraction):
    case, actor = demo
    db.add(_revision(case, extraction, actor))
    db.flush()
    _flush_fails(db, _revision(case, extraction, actor, confirmed_paths=[]))


def test_revision_numbers_continue_per_extraction(db, demo, extraction):
    case, actor = demo
    db.add(_revision(case, extraction, actor, revision_number=1))
    db.add(_revision(case, extraction, actor, revision_number=2))
    db.flush()


@pytest.mark.parametrize("reason", ["", "   "])
def test_blank_revision_reason_refused(db, demo, extraction, reason):
    case, actor = demo
    _flush_fails(db, _revision(case, extraction, actor, reason=reason))


def test_revision_number_must_be_positive(db, demo, extraction):
    case, actor = demo
    _flush_fails(db, _revision(case, extraction, actor, revision_number=0))


# ---------------------------------------------------------------- upload_tokens


def test_token_use_count_may_change(db, demo):
    case, actor = demo
    tok = _token(case, actor)
    db.add(tok)
    db.flush()
    tok.use_count = 1
    tok.last_used_at = datetime.now(UTC)
    db.flush()
    nested = db.begin_nested()
    db.execute(text("UPDATE upload_tokens SET use_count = 2"))
    nested.commit()


def test_token_scope_cannot_change(db, demo):
    case, actor = demo
    other = svc.create_case(db, actor, patient_alias="Other", currency="INR")
    tok = _token(case, actor)
    db.add(tok)
    db.flush()
    _sql_refused(db, "UPDATE upload_tokens SET expires_at = now() + interval '30 days'")
    _sql_refused(db, "UPDATE upload_tokens SET case_id = :other", other=other.id)
    _sql_refused(db, "UPDATE upload_tokens SET max_uploads = 50")
    _sql_refused(db, "UPDATE upload_tokens SET document_types = '[\"RECEIPT\"]'::jsonb")
    _sql_refused(db, "UPDATE upload_tokens SET token_sha256 = repeat('a', 64)")


def test_token_orm_guard(db, demo):
    case, actor = demo
    tok = _token(case, actor)
    db.add(tok)
    db.flush()
    tok.expires_at = tok.expires_at + timedelta(days=30)
    with pytest.raises(ImmutableRecordError):
        db.flush()
    db.rollback()


def test_token_delete_refused(db, demo):
    case, actor = demo
    db.add(_token(case, actor))
    db.flush()
    _sql_refused(db, "DELETE FROM upload_tokens")


def test_token_orm_delete_guard(db, demo):
    case, actor = demo
    tok = _token(case, actor)
    db.add(tok)
    db.flush()
    db.delete(tok)
    with pytest.raises(ImmutableRecordError):
        db.flush()
    db.rollback()


def test_token_use_count_cannot_exceed_max_uploads(db, demo):
    case, actor = demo
    _flush_fails(db, _token(case, actor, max_uploads=2, use_count=3))


@pytest.mark.parametrize("max_uploads", [0, 51])
def test_token_max_uploads_range(db, demo, max_uploads):
    case, actor = demo
    _flush_fails(db, _token(case, actor, max_uploads=max_uploads))


def test_token_hash_must_be_hex_and_unique(db, demo):
    case, actor = demo
    _flush_fails(db, _token(case, actor, token_sha256="plain-token-value"))
    digest = _hex()
    db.add(_token(case, actor, token_sha256=digest))
    db.flush()
    _flush_fails(db, _token(case, actor, token_sha256=digest))


def test_token_document_types_must_be_an_array(db, demo):
    case, actor = demo
    _flush_fails(db, _token(case, actor, document_types={"BILL": True}))
