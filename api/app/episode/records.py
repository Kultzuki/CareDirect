"""Complete episode inventory with current human revisions and explicit provenance."""

from pydantic import ValidationError
from sqlalchemy import select

from app import services as svc
from app.extraction.service import _load
from app.models import DocumentExtraction, EvidenceDocument
from app.money import sum_money, to_str
from app.reconciliation.views import normalize_text


def iso_date(value):
    return value.isoformat()[:10] if value is not None else None


def category(descriptions):
    text = " ".join(descriptions).lower()
    for name, words in (
        ("SURGERY", ("surg", "replacement", "theatre", "implant")),
        ("DIAGNOSTICS", ("lab", "blood", "diagnos", "x-ray", "mri", "panel")),
        ("PHARMACY", ("pharm", "tablet", "injection", "drug")),
        ("CONSULTATION", ("consult", "opd", "doctor", "visit")),
    ):
        if any(word in text for word in words):
            return name
    return "BILL"


def _base(record_id, kind, created_at):
    return dict(
        id=str(record_id),
        name=f"{kind.replace('_', ' ').title()} {str(record_id)[:8]}",
        category=kind,
        document_type=kind,
        amount=None,
        date=None,
        date_basis="unknown",
        provider=None,
        currency=None,
        patient_reference=None,
        source_ref=None,
        source_available=False,
        extraction_status="MANUAL",
        review_state="recorded",
        is_recorded=True,
        is_synthetic=False,
        uploaded_at=iso_date(created_at),
        lines=[],
        sources=[],
        is_overlapping=False,
        overlap_note=None,
    )


def load_episode_records(db, case):
    """One record per upload, including bills awaiting promotion and unextracted receipts."""
    docs = list(
        db.scalars(
            select(EvidenceDocument)
            .where(EvidenceDocument.case_id == case.id)
            .order_by(EvidenceDocument.created_at, EvidenceDocument.id)
        )
    )
    extractions = {
        e.document_id: e
        for e in db.scalars(select(DocumentExtraction).where(DocumentExtraction.case_id == case.id))
    }
    bills = {b.source_document_ref: b for b in case.bills}
    payments = svc.case_payments(db, case.id)
    payment_refs = {p.source_document_ref: p for p in payments}
    seen, records = set(), []
    for doc in docs:
        ref = f"evidence_document:{doc.id}"
        bill, payment = bills.get(ref), payment_refs.get(ref)
        seen.add(ref)
        record = _base(doc.id, str(doc.document_type), doc.created_at)
        record.update(
            category=doc.category or str(doc.document_type),
            source_ref=ref,
            source_available=True,
            extraction_status=str(doc.extraction_status),
            review_state="awaiting_extraction",
            is_recorded=bill is not None or payment is not None,
            is_synthetic=str(doc.source_type) == "SEEDED_SYNTHETIC",
        )
        record["payment_status"] = str(payment.status) if payment is not None else None
        extraction = extractions.get(doc.id)
        if extraction is not None:
            try:
                loaded = _load(db, extraction)
            except ValidationError:
                # Preserve the upload in the inventory even if legacy stored output is invalid.
                record.update(
                    review_state="needs_review",
                    extraction_status="INVALID",
                    is_synthetic=record["is_synthetic"] or extraction.provider == "mock",
                )
                records.append(record)
                continue
            fields = {f.info.path: f for f in loaded.fields}

            def value(path, fields=fields):
                return fields[path].value if path in fields else None

            receipt = str(doc.document_type) == "RECEIPT"
            number = value("invoice_number") or str(doc.id)[:8]
            record.update(
                name=f"{str(doc.document_type).title()} {number}",
                amount=value("receipt.amount" if receipt else "total"),
                date=value("receipt.paid_on" if receipt else "invoice_date"),
                provider=value("provider_name") or value("receipt.payee_name"),
                currency=value("currency"),
                patient_reference=value("patient_reference"),
                is_synthetic=record["is_synthetic"] or extraction.provider == "mock",
                review_state="needs_review"
                if any(f.needs_review for f in loaded.fields)
                or loaded.ex.document_type != doc.document_type
                else "extracted",
                sources=[
                    dict(
                        path=f.info.path,
                        source=f.source,
                        state=f.state,
                        needs_review=f.needs_review,
                    )
                    for f in loaded.fields
                    if f.value is not None
                ],
                date_basis="payment_date" if receipt else "document_date",
            )
            for index, line in enumerate(loaded.ex.line_items):
                prefix = f"line_items.{index}."
                ledger_line = (
                    next((li for li in bill.line_items if li.line_number == line.line_number), None)
                    if bill
                    else None
                )
                record["lines"].append(
                    dict(
                        id=f"{doc.id}:{line.line_number}",
                        ledger_line_id=str(ledger_line.id) if ledger_line else None,
                        line_number=line.line_number,
                        **{
                            name: value(prefix + name)
                            for name in (
                                "description",
                                "code",
                                "service_date",
                                "quantity",
                                "unit_price",
                                "line_total",
                            )
                        },
                        sources=[f for f in record["sources"] if f["path"].startswith(prefix)],
                    )
                )
            if record["category"] == "BILL":
                record["category"] = category([li["description"] or "" for li in record["lines"]])
        records.append(record)
    for bill in case.bills:
        if bill.source_document_ref in seen:
            continue
        record = _base(bill.id, "BILL", bill.created_at)
        record.update(
            name=f"Bill {bill.bill_number or str(bill.id)[:8]}",
            category=category([li.description_raw for li in bill.line_items]),
            amount=to_str(bill.printed_total)
            if bill.printed_total is not None
            else to_str(sum_money(li.line_total for li in bill.line_items)),
            date=iso_date(bill.bill_date),
            date_basis="document_date",
            provider=bill.provider_name,
            currency=bill.currency,
            source_ref=bill.source_document_ref,
            is_synthetic=str(bill.source_type) == "SEEDED_SYNTHETIC",
        )
        record["lines"] = [
            dict(
                id=str(li.id),
                ledger_line_id=str(li.id),
                line_number=li.line_number,
                description=li.description_raw,
                code=li.code,
                service_date=iso_date(li.service_date),
                quantity=str(li.quantity) if li.quantity is not None else None,
                unit_price=to_str(li.unit_price) if li.unit_price is not None else None,
                line_total=to_str(li.line_total),
                sources=[
                    dict(
                        path="bill_line",
                        source=dict(page=li.source_page, snippet=li.source_text),
                        state=str(li.source_type),
                    )
                ],
            )
            for li in bill.line_items
        ]
        records.append(record)
    for payment in payments:
        if payment.source_document_ref in seen:
            continue
        record = _base(payment.id, "RECEIPT", payment.created_at)
        record.update(
            name="Payment evidence",
            amount=to_str(payment.amount),
            date=iso_date(payment.paid_on),
            date_basis="payment_date",
            provider=payment.payee_name,
            currency=payment.currency,
            source_ref=payment.source_document_ref,
            review_state=str(payment.status),
            is_synthetic=str(payment.source_type) == "SEEDED_SYNTHETIC",
        )
        record["payment_status"] = str(payment.status)
        records.append(record)
    return sorted(records, key=lambda d: (d["uploaded_at"] or "", d["id"]))


def assess_affinity(records, currency):
    """Report missing/conflicting membership evidence without inferring clinical identity."""
    groups = {}
    for record in records:
        provider, reference = (
            normalize_text(record["provider"]),
            normalize_text(record["patient_reference"]),
        )
        if provider and reference:
            groups.setdefault(provider, set()).add(reference)
    for record in records:
        provider, reference = (
            normalize_text(record["provider"]),
            normalize_text(record["patient_reference"]),
        )
        if record["currency"] and record["currency"] != currency:
            status, reason = "conflict", "Document currency differs from the episode currency."
        elif len(groups.get(provider, set())) > 1:
            status, reason = (
                "conflict",
                "Different patient references appear for the same provider.",
            )
        elif record["review_state"] in ("needs_review", "awaiting_extraction"):
            status, reason = "unknown", "Extract and review fields before assessing membership."
        elif (
            provider
            and reference
            and sum(
                normalize_text(d["provider"]) == provider
                and normalize_text(d["patient_reference"]) == reference
                for d in records
            )
            > 1
        ):
            status, reason = (
                "consistent",
                "Provider and patient reference agree with other episode evidence.",
            )
        else:
            status, reason = (
                "unknown",
                "Assigned by upload; matching patient evidence is incomplete.",
            )
        record["affinity_status"], record["affinity_reason"] = status, reason
    return records
