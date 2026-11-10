"""Extraction, human revisions and promotion to the ledger.

- The validated AI output is stored once and never changes (`document_extractions`).
- A person's corrections and confirmations are append-only revisions layered over it.
- A value the model was unsure about must be confirmed or corrected by the payer before the
  extraction can be added to the case.
- `promote_extraction` is the only path from an extraction to the ledger, and it goes through
  the same `add_bill` / `record_external_payment` services as manual entry. Promoted charges
  start PENDING_REVIEW, so they are still not payable until the payer reviews them.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import services as svc
from app.documents.storage import PrivateStorage
from app.errors import DomainError, NotFound, ValidationFailed
from app.extraction.adapter import ExtractionAdapter, ExtractionUnavailable
from app.extraction.schema import (
    LOW_CONFIDENCE_THRESHOLD,
    ExtractionRejected,
    ExtractionV1,
    FieldInfo,
    build_source,
    iter_fields,
    parse_extraction,
    parse_field_value,
    value_to_str,
)
from app.models import (
    Bill,
    CareCase,
    DocumentExtraction,
    EvidenceDocument,
    ExternalPayment,
    ExtractionRevision,
)
from app.states import CaseStatus, DataSource, DocumentType, ExtractionStatus, PaymentMethod


def _ref(doc: EvidenceDocument) -> str:
    return f"evidence_document:{doc.id}"


def _pages(doc: EvidenceDocument) -> int:
    return doc.page_count or 1


# ---------------------------------------------------------------- extract


def _raw_hash(raw: object) -> str:
    text = json.dumps(raw, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(text.encode("ascii")).hexdigest()


def _fail(
    db: Session,
    actor: svc.Actor,
    adapter: ExtractionAdapter,
    case: CareCase,
    doc: EvidenceDocument,
    reason: str,
    error_locations: list[str],
) -> ValidationFailed:
    """Record a failed attempt (no values, only locations) and return the error to raise."""
    doc.extraction_status = ExtractionStatus.FAILED
    svc._audit(
        db,
        actor,
        case_id=case.id,
        event_type="EXTRACTION_FAILED",
        entity_type="evidence_document",
        entity_id=doc.id,
        details={"provider": adapter.provider, "reason": reason, "errors": error_locations},
    )
    db.commit()
    return ValidationFailed(reason)


def extract_document(
    db: Session,
    actor: svc.Actor,
    storage: PrivateStorage,
    adapter: ExtractionAdapter,
    document_id: uuid.UUID,
) -> DocumentExtraction:
    first = db.get(EvidenceDocument, document_id)
    if first is None:
        raise NotFound(f"document {document_id} not found")
    case = svc._lock_case(db, first.case_id)
    svc._require_reviewer(case, actor)
    doc = db.get(EvidenceDocument, document_id, populate_existing=True)

    already = db.scalar(
        select(DocumentExtraction.id).where(DocumentExtraction.document_id == doc.id)
    )
    if doc.extraction_status == ExtractionStatus.EXTRACTED or already is not None:
        raise DomainError("already extracted; corrections become revisions")

    try:
        content = storage.get(doc.storage_key)
    except FileNotFoundError:
        raise DomainError("the stored file for this document is missing") from None
    if hashlib.sha256(content).hexdigest() != doc.sha256:
        raise DomainError("the stored file no longer matches its recorded hash")

    try:
        raw = adapter.extract(
            document_id=doc.id,
            document_type=str(doc.document_type),
            mime_type=doc.mime_type,
            content=content,
            page_count=_pages(doc),
        )
        parsed = parse_extraction(raw, document_id=doc.id, page_count=_pages(doc))
    except ExtractionUnavailable as exc:
        raise _fail(db, actor, adapter, case, doc, str(exc), []) from None
    except ExtractionRejected as exc:
        locations = [f"{'.'.join(str(p) for p in e['loc'])}: {e['type']}" for e in exc.errors]
        raise _fail(
            db, actor, adapter, case, doc, "the model output did not match the schema", locations
        ) from None

    row = DocumentExtraction(
        id=uuid.uuid4(),
        document_id=doc.id,
        case_id=case.id,
        schema_version=parsed.schema_version,
        provider=adapter.provider,
        model=adapter.model,
        prompt_version=adapter.prompt_version,
        payload=parsed.model_dump(mode="json"),
        raw_output_sha256=_raw_hash(raw),
        created_by=actor.user_id,
        actor_label=actor.label,
    )
    db.add(row)
    doc.extraction_status = ExtractionStatus.EXTRACTED
    db.flush()
    svc._audit(
        db,
        actor,
        case_id=case.id,
        event_type="EXTRACTION_RECORDED",
        entity_type="document_extraction",
        entity_id=row.id,
        details={
            "document_id": str(doc.id),
            "provider": row.provider,
            "model": row.model,
            "schema_version": row.schema_version,
            "line_count": len(parsed.line_items),
            "review_required_count": sum(
                1
                for f in _resolve(parsed, [], require_review=adapter.provider == "gemini")
                if f.needs_review
            ),
        },
    )
    db.commit()
    return row


# ---------------------------------------------------------------- resolving current values


@dataclass
class _Field:
    info: FieldInfo
    value: str | None
    original_value: str | None
    model_confidence: Decimal | None
    source: dict[str, Any] | None
    state: str
    needs_review: bool


def _source_json(info: FieldInfo) -> dict[str, Any] | None:
    src = info.field.source
    return None if src is None else src.model_dump(mode="json")


def _resolve(
    ex: ExtractionV1, revisions: list[ExtractionRevision], *, require_review=False
) -> list[_Field]:
    """Fold the revisions over the original extraction."""
    corrected: dict[str, dict[str, Any]] = {}
    confirmed: set[str] = set()
    for rev in sorted(revisions, key=lambda r: r.revision_number):
        for item in rev.corrections:
            previous = corrected.get(item["path"])
            source = item["source"] or (previous["source"] if previous else None)
            corrected[item["path"]] = {"value": item["value"], "source": source}
        confirmed.update(rev.confirmed_paths)

    fields = []
    for info in iter_fields(ex):
        original = value_to_str(info.kind, info.field.value)
        confidence = info.field.confidence
        fix = corrected.get(info.path)
        if fix is not None:
            value, source, state = fix["value"], fix["source"] or _source_json(info), "corrected"
        else:
            value, source = original, _source_json(info)
            state = "confirmed" if info.path in confirmed else "extracted"
        reviewed = fix is not None or info.path in confirmed
        needs_review = (
            value is not None
            and confidence is not None
            and (require_review or confidence < LOW_CONFIDENCE_THRESHOLD)
            and not reviewed
        )
        fields.append(_Field(info, value, original, confidence, source, state, needs_review))
    return fields


def _typed(f: _Field) -> Any:
    """The current value as a Python object, ready for the existing services."""
    if f.value is None:
        return None
    kind = f.info.kind
    if kind in ("money", "quantity"):
        return Decimal(f.value)
    if kind == "date":
        return date.fromisoformat(f.value)
    if kind == "payment_method":
        return PaymentMethod(f.value)
    return f.value


def _min_confidence(fields: list[_Field]) -> Decimal | None:
    """Lowest model confidence among values the model itself supplied. Human-entered values
    have none, and none is invented for them."""
    found = [f.model_confidence for f in fields if f.model_confidence is not None]
    return min(found) if found else None


# ---------------------------------------------------------------- the view


def _promoted_to(db: Session, doc: EvidenceDocument) -> dict[str, str | None] | None:
    bill_id = db.scalar(select(Bill.id).where(Bill.source_document_ref == _ref(doc)))
    payment_id = db.scalar(
        select(ExternalPayment.id).where(ExternalPayment.source_document_ref == _ref(doc))
    )
    if bill_id is None and payment_id is None:
        return None
    return {
        "bill_id": None if bill_id is None else str(bill_id),
        "external_payment_id": None if payment_id is None else str(payment_id),
    }


def _blockers(
    doc: EvidenceDocument, case: CareCase, ex: ExtractionV1, fields: list[_Field]
) -> list[str]:
    by_path = {f.info.path: f for f in fields}
    blockers = [
        f"{f.info.label} needs review (model confidence {format(f.model_confidence, 'f')})"
        for f in fields
        if f.needs_review
    ]
    if ex.document_type != doc.document_type:
        blockers.append(
            f"Document type chosen at upload ({doc.document_type}) differs from the type the "
            f"model read ({ex.document_type})"
        )
    if doc.document_type == DocumentType.ESTIMATE:
        blockers.append("Estimates are not added to the ledger in this slice")
        return blockers
    if doc.document_type == DocumentType.BILL:
        blockers += _bill_blockers(case, ex, by_path)
    elif doc.document_type == DocumentType.RECEIPT:
        blockers += _receipt_blockers(case, ex, by_path)
    elif doc.document_type in (
        DocumentType.INSURANCE_PREAUTH,
        DocumentType.INSURANCE_SETTLEMENT,
        DocumentType.INSURER_PAYMENT,
    ):
        blockers.append(
            "Insurance evidence is used in Insurance and TPA reconciliation; "
            "it is not added as a bill or direct payment"
        )
    else:
        blockers.append("Only bills and receipts can be added to the case")
    return blockers


def _bill_blockers(case: CareCase, ex: ExtractionV1, by_path: dict[str, _Field]) -> list[str]:
    out = []
    if case.status not in (CaseStatus.DRAFT, CaseStatus.UNDER_REVIEW):
        out.append(f"Bills cannot be added to a case in {case.status}")
    if by_path["provider_name"].value is None:
        out.append("Provider name is missing")
    currency = by_path["currency"].value
    if currency is None:
        out.append("Currency is missing")
    elif currency != case.currency:
        out.append(f"Currency {currency} differs from the case currency {case.currency}")
    if not ex.line_items:
        out.append("The bill has no line items")
    for index, line in enumerate(ex.line_items):
        label = f"Line {line.line_number}"
        if by_path[f"line_items.{index}.description"].value is None:
            out.append(f"{label} description is missing")
        total = by_path[f"line_items.{index}.line_total"].value
        if total is None:
            out.append(f"{label} line total is missing")
        elif Decimal(total) <= 0:
            out.append(f"{label} line total must be positive (only positive charges are supported)")
    try:
        _tax_charge(by_path)
    except DomainError as exc:
        out.append(str(exc))
    return out


def _receipt_blockers(case: CareCase, ex: ExtractionV1, by_path: dict[str, _Field]) -> list[str]:
    if ex.receipt is None:
        return ["No receipt details were found in the document"]
    out = []
    amount = by_path["receipt.amount"].value
    if amount is None:
        out.append("Receipt amount is missing")
    elif Decimal(amount) <= 0:
        out.append("Receipt amount must be positive")
    if by_path["receipt.payment_method"].value is None:
        out.append("Payment method is missing")
    currency = by_path["currency"].value
    if currency is None:
        out.append("Currency is missing")
    elif currency != case.currency:
        out.append(f"Currency {currency} differs from the case currency {case.currency}")
    return out


@dataclass
class _Loaded:
    doc: EvidenceDocument
    case: CareCase
    ex: ExtractionV1
    revisions: list[ExtractionRevision]
    fields: list[_Field]


def _load(db: Session, extraction: DocumentExtraction) -> _Loaded:
    doc = db.get(EvidenceDocument, extraction.document_id)
    case = db.get(CareCase, extraction.case_id)
    ex = ExtractionV1.model_validate(
        extraction.payload, context={"document_id": doc.id, "page_count": _pages(doc)}
    )
    revisions = list(
        db.scalars(
            select(ExtractionRevision)
            .where(ExtractionRevision.extraction_id == extraction.id)
            .order_by(ExtractionRevision.revision_number)
        )
    )
    return _Loaded(
        doc,
        case,
        ex,
        revisions,
        _resolve(
            ex,
            revisions,
            require_review=extraction.provider == "gemini"
            or doc.document_type
            in (
                DocumentType.INSURANCE_PREAUTH,
                DocumentType.INSURANCE_SETTLEMENT,
                DocumentType.INSURER_PAYMENT,
            ),
        ),
    )


def extraction_view(db: Session, extraction: DocumentExtraction) -> dict[str, Any]:
    """Everything the review screen needs. The API decides what needs review and what blocks
    promotion; clients only render it."""
    loaded = _load(db, extraction)
    promoted = _promoted_to(db, loaded.doc)
    blockers = [] if promoted else _blockers(loaded.doc, loaded.case, loaded.ex, loaded.fields)
    return {
        "id": extraction.id,
        "document_id": extraction.document_id,
        "case_id": extraction.case_id,
        "document_type": loaded.doc.document_type,
        "extracted_document_type": loaded.ex.document_type,
        "schema_version": extraction.schema_version,
        "provider": extraction.provider,
        "model": extraction.model,
        "prompt_version": extraction.prompt_version,
        "is_mock": extraction.provider == "mock",
        "low_confidence_threshold": format(LOW_CONFIDENCE_THRESHOLD, "f"),
        "created_at": extraction.created_at,
        "actor_label": extraction.actor_label,
        "fields": [
            {
                "path": f.info.path,
                "label": f.info.label,
                "group": f.info.group,
                "line_index": f.info.line_index,
                "line_number": f.info.line_number,
                "name": f.info.name,
                "kind": f.info.kind,
                "value": f.value,
                "original_value": f.original_value,
                "model_confidence": (
                    None if f.model_confidence is None else format(f.model_confidence, "f")
                ),
                "source": f.source,
                "state": f.state,
                "needs_review": f.needs_review,
            }
            for f in loaded.fields
        ],
        "review_required": [f.info.path for f in loaded.fields if f.needs_review],
        "promotion_blockers": blockers,
        "can_promote": not blockers and promoted is None,
        "promoted_to": promoted,
        "revisions": [
            {
                "revision_number": r.revision_number,
                "corrections": r.corrections,
                "confirmed_paths": r.confirmed_paths,
                "reason": r.reason,
                "actor_label": r.actor_label,
                "created_at": r.created_at,
            }
            for r in loaded.revisions
        ],
        "original_payload": extraction.payload,
    }


def get_extraction(db: Session, extraction_id: uuid.UUID) -> DocumentExtraction:
    row = db.get(DocumentExtraction, extraction_id)
    if row is None:
        raise NotFound(f"extraction {extraction_id} not found")
    return row


def extraction_for_document(db: Session, document_id: uuid.UUID) -> DocumentExtraction:
    row = db.scalar(select(DocumentExtraction).where(DocumentExtraction.document_id == document_id))
    if row is None:
        raise NotFound("this document has not been extracted yet")
    return row


# ---------------------------------------------------------------- revisions


@dataclass(frozen=True)
class CorrectionInput:
    path: str
    value: str | None
    source: dict[str, Any] | None = None


def add_revision(
    db: Session,
    actor: svc.Actor,
    extraction_id: uuid.UUID,
    corrections: list[CorrectionInput],
    confirmed_paths: list[str],
    reason: str,
) -> ExtractionRevision:
    """Record the payer's corrections and confirmations. The stored extraction is untouched."""
    extraction = get_extraction(db, extraction_id)
    case = svc._lock_case(db, extraction.case_id)
    svc._require_reviewer(case, actor)
    reason = svc._require_note(reason, "a reason for the change")
    if not corrections and not confirmed_paths:
        raise ValidationFailed("nothing to correct or confirm")

    loaded = _load(db, extraction)
    if _promoted_to(db, loaded.doc) is not None:
        raise DomainError(
            "already added to the case; financial corrections require an explicit adjustment"
        )
    current = {f.info.path: f for f in loaded.fields}
    paths = [c.path for c in corrections] + list(confirmed_paths)
    unknown = [p for p in paths if p not in current]
    if unknown:
        raise ValidationFailed("unknown field: " + ", ".join(sorted(set(unknown))))
    if len(set(paths)) != len(paths):
        raise ValidationFailed("a field may appear only once in a revision")

    confirmed = list(confirmed_paths)
    stored: list[dict[str, Any]] = []
    for item in corrections:
        field = current[item.path]
        try:
            value = parse_field_value(field.info.kind, field.info.max_len, item.value)
            if (
                field.info.name == "code"
                and value is not None
                and value.upper() == "CAREDIRECT_TAX"
            ):
                raise ValueError("reserved internal accounting code")
        except ValueError as exc:
            raise ValidationFailed(f"{field.info.label}: {exc}") from None
        source = None
        if item.source is not None:
            try:
                source = build_source(
                    item.source, document_id=loaded.doc.id, page_count=_pages(loaded.doc)
                ).model_dump(mode="json")
            except ValueError as exc:
                raise ValidationFailed(f"{field.info.label}: {exc}") from None
        if source is None and value == field.value:
            # Same value, no new evidence: this is a confirmation, not a correction.
            confirmed.append(item.path)
            continue
        if value is not None and source is None and field.source is None:
            raise ValidationFailed(
                f"{field.info.label}: a corrected value needs the page and snippet where it appears"
            )
        stored.append({"path": item.path, "value": value, "source": source})

    number = (
        db.scalar(
            select(func.max(ExtractionRevision.revision_number)).where(
                ExtractionRevision.extraction_id == extraction.id
            )
        )
        or 0
    ) + 1
    revision = ExtractionRevision(
        id=uuid.uuid4(),
        extraction_id=extraction.id,
        case_id=case.id,
        revision_number=number,
        corrections=stored,
        confirmed_paths=confirmed,
        reason=reason,
        created_by=actor.user_id,
        actor_label=actor.label,
    )
    db.add(revision)
    db.flush()
    svc._audit(
        db,
        actor,
        case_id=case.id,
        event_type="EXTRACTION_REVISED",
        entity_type="extraction_revision",
        entity_id=revision.id,
        details={
            "extraction_id": str(extraction.id),
            "revision_number": number,
            "corrected_paths": [c["path"] for c in stored],
            "confirmed_paths": confirmed,
        },
    )
    db.commit()
    return revision


# ---------------------------------------------------------------- promotion


def _tax_charge(by_path: dict[str, _Field]) -> Decimal | None:
    """Account for stated tax only when the supplied totals identify its treatment."""
    tax = _typed(by_path["tax_total"])
    if tax is None or tax == 0:
        return None
    if tax < 0:
        raise DomainError("Negative tax needs an explicit credit adjustment")
    total = _typed(by_path["total"])
    amounts = [
        f
        for path, f in by_path.items()
        if path.startswith("line_items.") and path.endswith(".line_total")
    ]
    if total is None or any(f.value is None for f in amounts):
        raise DomainError(
            "Stated tax needs complete line totals and a stated total before promotion"
        )
    line_sum = sum((_typed(f) for f in amounts), Decimal("0.00"))
    subtotal = _typed(by_path["subtotal"])
    if line_sum == total and tax <= total and (subtotal is None or subtotal + tax == total):
        return None  # the supplied line totals already include tax
    if line_sum + tax == total and (subtotal is None or subtotal == line_sum):
        return tax
    raise DomainError(
        "Stated tax cannot be reconciled with the supplied line totals, subtotal and total"
    )


def _bill_input(loaded: _Loaded) -> svc.BillInput:
    by_path = {f.info.path: f for f in loaded.fields}

    def value(path: str) -> Any:
        return _typed(by_path[path])

    lines = []
    for index, line in enumerate(loaded.ex.line_items):
        prefix = f"line_items.{index}."
        own = [f for f in loaded.fields if f.info.path.startswith(prefix)]
        total_source = by_path[prefix + "line_total"].source or {}
        lines.append(
            svc.LineInput(
                line_number=line.line_number,
                description_raw=value(prefix + "description"),
                code=value(prefix + "code"),
                line_total=value(prefix + "line_total"),
                service_date=value(prefix + "service_date"),
                quantity=value(prefix + "quantity"),
                unit_price=value(prefix + "unit_price"),
                extraction_confidence=_min_confidence(own),
                source_page=total_source.get("page"),
                source_text=total_source.get("snippet"),
            )
        )
    tax = _tax_charge(by_path)
    if tax is not None:
        field = by_path["tax_total"]
        source = field.source or {}
        lines.append(
            svc.LineInput(
                line_number=max(line.line_number for line in loaded.ex.line_items) + 1,
                description_raw="Stated invoice tax",
                # Internal accounting identifier, not an extracted service code.
                code="CAREDIRECT_TAX",
                line_total=tax,
                extraction_confidence=field.model_confidence,
                source_page=source.get("page"),
                source_text=source.get("snippet"),
            )
        )
    return svc.BillInput(
        provider_name=value("provider_name"),
        currency=value("currency"),
        lines=lines,
        bill_number=value("invoice_number"),
        bill_date=value("invoice_date"),
        printed_total=value("total"),
        printed_advance_paid=value("advance_paid"),
        printed_balance_due=None,
        source_document_ref=_ref(loaded.doc),
    )


def _payment_input(loaded: _Loaded) -> svc.PaymentInput:
    by_path = {f.info.path: f for f in loaded.fields}
    receipt_fields = [f for f in loaded.fields if f.info.group == "receipt"]
    return svc.PaymentInput(
        method=_typed(by_path["receipt.payment_method"]),
        amount=_typed(by_path["receipt.amount"]),
        currency=_typed(by_path["currency"]),
        paid_on=_typed(by_path["receipt.paid_on"]),
        reference=_typed(by_path["receipt.transaction_reference"]),
        payee_name=_typed(by_path["receipt.payee_name"]),
        bill_id=None,
        extraction_confidence=_min_confidence(receipt_fields),
        source_document_ref=_ref(loaded.doc),
    )


def promote_extraction(
    db: Session, actor: svc.Actor, extraction_id: uuid.UUID
) -> tuple[Bill | None, ExternalPayment | None]:
    """Add the extraction's current values to the case as a bill or an external payment.
    Refused while any value awaits review or any required value is missing."""
    extraction = get_extraction(db, extraction_id)
    case = svc._lock_case(db, extraction.case_id)
    svc._require_reviewer(case, actor)

    loaded = _load(db, extraction)
    if _promoted_to(db, loaded.doc) is not None:
        raise DomainError("already added to the case")
    blockers = _blockers(loaded.doc, loaded.case, loaded.ex, loaded.fields)
    if blockers:
        raise DomainError("cannot add to case: " + "; ".join(blockers))

    svc._audit(
        db,
        actor,
        case_id=case.id,
        event_type="EXTRACTION_PROMOTED",
        entity_type="document_extraction",
        entity_id=extraction.id,
        details={
            "document_id": str(loaded.doc.id),
            "document_type": str(loaded.doc.document_type),
            "revision_count": len(loaded.revisions),
        },
    )
    # add_bill / record_external_payment commit, which also commits the audit event above.
    if loaded.doc.document_type == DocumentType.BILL:
        bill = svc.add_bill(
            db, actor, case.id, _bill_input(loaded), source_type=DataSource.AI_EXTRACTED
        )
        return bill, None
    payment = svc.record_external_payment(
        db, actor, case.id, _payment_input(loaded), source_type=DataSource.AI_EXTRACTED
    )
    return None, payment
