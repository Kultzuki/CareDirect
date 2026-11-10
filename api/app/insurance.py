"""Source-backed insurance reconciliation. No coverage adjudication or money mutations."""

import hashlib
import json
import uuid
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app import services as svc
from app.extraction.service import _load
from app.models import AuditEvent, DocumentExtraction, EvidenceDocument
from app.money import ZERO, to_str
from app.reconciliation.views import normalize_text
from app.states import DocumentType, ExternalPaymentStatus

INSURANCE_TYPES = (
    DocumentType.INSURANCE_PREAUTH,
    DocumentType.INSURANCE_SETTLEMENT,
    DocumentType.INSURER_PAYMENT,
)
COMPONENTS = {
    "approved_amount": "Insurance approved (not paid)",
    "copay": "Patient co-payment",
    "deductible": "Patient deductible",
    "noncovered": "Stated non-covered expenses",
    "pending": "Pending insurance claim",
    "rejected": "Rejected claim — responsibility unresolved",
}


class Selection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bill_id: uuid.UUID | None = None
    preauth_id: uuid.UUID | None = None
    settlement_id: uuid.UUID | None = None
    insurer_payment_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    selection: Selection
    input_fingerprint: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    note: Annotated[str, Field(min_length=1, max_length=2000)]


class ExplainRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    selection: Selection
    input_fingerprint: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


def has_insurance(db, case_id):
    return (
        db.scalar(
            select(EvidenceDocument.id)
            .where(
                EvidenceDocument.case_id == case_id,
                EvidenceDocument.document_type.in_(INSURANCE_TYPES),
            )
            .limit(1)
        )
        is not None
    )


def latest_review(db, case_id):
    return db.scalar(
        select(AuditEvent)
        .where(AuditEvent.case_id == case_id, AuditEvent.event_type == "INSURANCE_REVIEWED")
        .order_by(AuditEvent.seq.desc())
        .limit(1)
    )


def source_document_id(reference):
    if not reference or not reference.startswith("evidence_document:"):
        return None
    try:
        return str(uuid.UUID(reference.split(":", 1)[1]))
    except ValueError:
        return None


def reconcile(db, case, selection=None):
    docs = list(
        db.scalars(
            select(EvidenceDocument)
            .where(
                EvidenceDocument.case_id == case.id,
                EvidenceDocument.document_type.in_(INSURANCE_TYPES),
            )
            .order_by(EvidenceDocument.created_at, EvidenceDocument.id)
        )
    )
    review = latest_review(db, case.id)
    if selection is None:
        if review:
            selection = Selection.model_validate(review.details["selection"])
        else:

            def single(kind):
                own = [d.id for d in docs if d.document_type == kind]
                return own[0] if len(own) == 1 else None

            selection = Selection(
                bill_id=case.bills[0].id if len(case.bills) == 1 else None,
                preauth_id=single(DocumentType.INSURANCE_PREAUTH),
                settlement_id=single(DocumentType.INSURANCE_SETTLEMENT),
                insurer_payment_ids=[
                    d.id for d in docs if d.document_type == DocumentType.INSURER_PAYMENT
                ],
            )
    issues, warnings, facts = [], [], []
    by_doc = {d.id: d for d in docs}
    bills = {b.id: b for b in case.bills}
    bill = bills.get(selection.bill_id)
    if selection.bill_id and not bill:
        raise svc.ValidationFailed("Select a hospital bill from this episode.")
    if not bill:
        issues.append("Select one recorded hospital bill for this claim.")

    def fact(fact_id, label, value, source=None, document_id=None):
        result = dict(
            id=fact_id,
            label=label,
            value=value,
            source=source,
            document_id=str(document_id) if document_id else None,
        )
        facts.append(result)
        return result

    loaded = {}
    chosen = [
        ("preauth", selection.preauth_id, DocumentType.INSURANCE_PREAUTH),
        ("settlement", selection.settlement_id, DocumentType.INSURANCE_SETTLEMENT),
    ]
    if len(set(selection.insurer_payment_ids)) != len(selection.insurer_payment_ids):
        raise svc.ValidationFailed("Select each insurer payment document once.")
    chosen += [
        (f"payment:{i}", doc_id, DocumentType.INSURER_PAYMENT)
        for i, doc_id in enumerate(sorted(selection.insurer_payment_ids, key=str))
    ]
    for role, doc_id, kind in chosen:
        if doc_id is None:
            continue
        doc = by_doc.get(doc_id)
        if not doc or doc.document_type != kind:
            raise svc.ValidationFailed("Select a document of the required type from this episode.")
        row = db.scalar(select(DocumentExtraction).where(DocumentExtraction.document_id == doc.id))
        if not row or str(doc.extraction_status) != "EXTRACTED":
            issues.append(f"Extract and review the selected {role} document.")
            continue
        item = _load(db, row)
        fields = {f.info.path: f for f in item.fields}
        loaded[role] = fields
        if item.ex.document_type != kind or item.ex.insurance is None:
            issues.append(
                f"The selected {role} extraction has no matching insurance document facts."
            )
        if any(
            f.value is not None and f.state not in ("confirmed", "corrected") for f in item.fields
        ):
            issues.append(f"Confirm all populated fields in the selected {role} extraction.")
        if fields["currency"].value != case.currency:
            issues.append(f"The selected {role} currency is missing or differs from the episode.")
        for path, f in fields.items():
            if f.value is not None:
                fact(f"{doc.id}:{path}", f.info.label, f.value, f.source, doc.id)
        if bill:
            reference = fields.get("insurance.bill_reference")
            if reference and reference.value and bill.bill_number:
                if normalize_text(reference.value) != normalize_text(bill.bill_number):
                    issues.append(f"The selected {role} references a different hospital bill.")
            else:
                warnings.append(
                    f"{role}: hospital bill reference is incomplete; "
                    "verify membership in the selected bill."
                )

    def value(role, name):
        f = loaded.get(role, {}).get("insurance." + name)
        return f.value if f else None

    claims = {
        normalize_text(value(role, "claim_reference"))
        for role in loaded
        if value(role, "claim_reference")
    }
    if len(claims) > 1:
        issues.append("Selected documents have conflicting claim references.")
    if any(not value(role, "claim_reference") for role in loaded):
        warnings.append("Claim reference is missing on some evidence; verify claim membership.")
    if not selection.settlement_id:
        issues.append(
            "Select a final settlement statement; pre-authorisation is not final settlement."
        )
    if value("settlement", "claimed_total") is None:
        warnings.append("Settlement claimed total is unstated; verify the claim's bill scope.")
    amounts = {name: value("settlement", name) for name in COMPONENTS}
    if any(v is not None and Decimal(v) < ZERO for v in amounts.values()):
        issues.append("Settlement components must not be negative.")
    complete = all(v is not None for v in amounts.values())
    if not complete:
        issues.append(
            "Some settlement components are not stated. Missing amounts remain unknown, not zero."
        )
    hospital_total = None
    itemized = None
    if bill:
        itemized = sum((li.line_total for li in bill.line_items), ZERO)
        from app.providers import recognized_amount

        hospital_total = sum((recognized_amount(db, li) for li in bill.line_items), ZERO)
        fact(
            "hospital:total",
            "Hospital itemized bill after agreed adjustments",
            to_str(hospital_total),
        )
        for li in bill.line_items:
            fact(
                f"hospital:line:{li.id}",
                li.description_raw,
                to_str(li.line_total),
                dict(page=li.source_page, snippet=li.source_text),
                source_document_id(bill.source_document_ref),
            )
        if bill.printed_total is not None and bill.printed_total != itemized:
            issues.append(
                "Hospital stated total differs from its itemized total; clarify the bill first."
            )
    claimed = value("settlement", "claimed_total")
    if claimed is not None and hospital_total is not None and Decimal(claimed) != hospital_total:
        issues.append(
            "Settlement claimed total differs from the selected recognized hospital bill."
        )
    allocated = sum((Decimal(v) for v in amounts.values()), ZERO) if complete else None
    unexplained = (
        hospital_total - allocated if hospital_total is not None and allocated is not None else None
    )
    if unexplained is not None and unexplained != ZERO:
        issues.append(
            "Settlement components do not reconcile to the hospital bill; "
            "categories may overlap or amounts are unexplained."
        )
    patient = (
        sum((Decimal(amounts[k]) for k in ("copay", "deductible", "noncovered")), ZERO)
        if all(amounts[k] is not None for k in ("copay", "deductible", "noncovered"))
        else None
    )
    known_patient_subtotal = (
        sum(
            (
                Decimal(amounts[k])
                for k in ("copay", "deductible", "noncovered")
                if amounts[k] is not None
            ),
            ZERO,
        )
        if any(amounts[k] is not None for k in ("copay", "deductible", "noncovered"))
        else None
    )
    paid, references, remittances_valid = ZERO, set(), True
    for role in loaded:
        if not role.startswith("payment:"):
            continue
        recipient = value(role, "payment_recipient")
        if (
            not bill
            or not recipient
            or normalize_text(recipient) != normalize_text(bill.provider_name)
        ):
            issues.append("Insurer remittance must identify the selected hospital as recipient.")
            remittances_valid = False
            continue
        amount, reference, paid_on = (
            value(role, key) for key in ("insurer_paid", "payment_reference", "paid_on")
        )
        if amount is None or Decimal(amount) <= ZERO or not reference or not paid_on:
            remittances_valid = False
            issues.append("Insurer remittance needs a positive amount, reference and payment date.")
            continue
        key = normalize_text(reference).replace(" ", "")
        if key in references:
            remittances_valid = False
            issues.append("Duplicate insurer payment reference; do not count the remittance twice.")
            continue
        references.add(key)
        paid += Decimal(amount)
    insurer_paid = (
        paid
        if selection.insurer_payment_ids
        and remittances_valid
        and all(
            role in loaded for role, doc_id, _ in chosen if doc_id and role.startswith("payment:")
        )
        else None
    )
    approved = (
        Decimal(amounts["approved_amount"]) if amounts["approved_amount"] is not None else None
    )
    if insurer_paid is not None and approved is not None and insurer_paid > approved:
        issues.append(
            "Insurer payment evidence exceeds the approved amount; reconcile the discrepancy."
        )
    family = ZERO
    family_records = []
    direct_payments = svc.case_payments(db, case.id)
    payment_sources = {p.source_document_ref for p in direct_payments if p.source_document_ref}
    pending_receipts = list(
        db.scalars(
            select(EvidenceDocument).where(
                EvidenceDocument.case_id == case.id,
                EvidenceDocument.document_type == DocumentType.RECEIPT,
            )
        )
    )
    if any(f"evidence_document:{doc.id}" not in payment_sources for doc in pending_receipts):
        issues.append(
            "Family receipt evidence awaits extraction, review or payment reconciliation."
        )
    if bill:
        for payment in direct_payments:
            if (
                payment.reference
                and normalize_text(payment.reference).replace(" ", "") in references
            ):
                issues.append(
                    "An insurer remittance also appears as direct payment evidence; "
                    "clarify who paid before counting either toward family responsibility."
                )
            if payment.status != ExternalPaymentStatus.MATCHED:
                if payment.status != ExternalPaymentStatus.REJECTED and payment.bill_id in (
                    None,
                    bill.id,
                ):
                    issues.append("Family payment evidence awaits reconciliation.")
                continue
            if payment.bill_id == bill.id or (payment.bill_id is None and len(case.bills) == 1):
                family += payment.amount
                family_records.append(
                    dict(
                        id=str(payment.id),
                        amount=to_str(payment.amount),
                        paid_on=payment.paid_on.isoformat() if payment.paid_on else None,
                    )
                )
                fact(
                    f"family:{payment.id}",
                    "Matched direct payment evidence",
                    to_str(payment.amount),
                    document_id=source_document_id(payment.source_document_ref),
                )
            elif payment.bill_id is None:
                warnings.append(
                    "Unassigned family payment evidence is excluded; link it to the bill first."
                )
        # Verified PayPal credits are family payments; never count invoice totals or approvals.
        from app.models import LedgerEntry
        from app.states import LedgerEntryType

        credits = list(
            db.scalars(
                select(LedgerEntry).where(
                    LedgerEntry.case_id == case.id,
                    LedgerEntry.entry_type == LedgerEntryType.PAYPAL_PAYMENT,
                )
            )
        )
        if len(case.bills) == 1:
            family += sum((entry.amount for entry in credits), ZERO)
            for entry in credits:
                fact(f"family:{entry.id}", "Verified PayPal credit", to_str(entry.amount))
        elif credits:
            warnings.append(
                "Case-level PayPal credits cannot be assigned automatically among multiple bills."
            )
    due = max(patient - family, ZERO) if patient is not None else None
    overpaid = max(family - patient, ZERO) if patient is not None else None
    if overpaid:
        warnings.append(
            "Family payments exceed the stated patient share; review reimbursement separately."
        )
    components = [dict(key=k, label=label, amount=amounts[k]) for k, label in COMPONENTS.items()]
    fingerprint_data = dict(
        selection=selection.model_dump(mode="json"),
        facts=facts,
        inventory=[(str(d.id), str(d.extraction_status)) for d in docs],
        family_records=family_records,
        receipt_inventory=[(str(d.id), str(d.extraction_status)) for d in pending_receipts],
        issues=issues,
    )
    fingerprint = hashlib.sha256(json.dumps(fingerprint_data, sort_keys=True).encode()).hexdigest()
    confirmed = bool(review and review.details.get("input_fingerprint") == fingerprint)
    return dict(
        case_id=str(case.id),
        currency=case.currency,
        selection=selection.model_dump(mode="json"),
        input_fingerprint=fingerprint,
        documents=[
            dict(
                id=str(d.id),
                document_type=str(d.document_type),
                extraction_status=str(d.extraction_status),
            )
            for d in docs
        ],
        bills=[
            dict(id=str(b.id), provider=b.provider_name, number=b.bill_number) for b in case.bills
        ],
        hospital_total=to_str(hospital_total) if hospital_total is not None else None,
        itemized_total=to_str(itemized) if itemized is not None else None,
        hospital_stated_total=to_str(bill.printed_total)
        if bill and bill.printed_total is not None
        else None,
        preauthorized=value("preauth", "approved_amount"),
        components=components,
        insurer_paid=to_str(insurer_paid) if insurer_paid is not None else None,
        approved_unpaid=to_str(max(approved - insurer_paid, ZERO))
        if approved is not None and insurer_paid is not None
        else None,
        family_paid=to_str(family),
        patient_share=to_str(patient) if patient is not None else None,
        known_patient_subtotal=to_str(known_patient_subtotal)
        if known_patient_subtotal is not None
        else None,
        patient_balance=to_str(due) if due is not None and not issues else None,
        family_overpayment=to_str(overpaid) if overpaid is not None else None,
        unexplained=to_str(unexplained) if unexplained is not None else None,
        issues=list(dict.fromkeys(issues)),
        warnings=list(dict.fromkeys(warnings)),
        facts=facts,
        reviewed=confirmed,
        review_stale=bool(review and not confirmed),
        review_note=review.details.get("note") if confirmed else None,
    )


def confirm_review(db, actor, case_id, body):
    case = svc._lock_case(db, case_id)
    svc._require_reviewer(case, actor)
    result = reconcile(db, case, body.selection)
    if body.input_fingerprint != result["input_fingerprint"]:
        raise svc.DomainError("Insurance evidence changed. Refresh before confirming.")
    if result["issues"]:
        raise svc.DomainError("Resolve insurance reconciliation issues before confirming.")
    if not result["reviewed"]:
        svc._audit(
            db,
            actor,
            case_id=case.id,
            event_type="INSURANCE_REVIEWED",
            entity_type="care_case",
            entity_id=case.id,
            details=dict(
                selection=result["selection"],
                input_fingerprint=result["input_fingerprint"],
                note=svc._require_note(body.note, "Confirm document and claim membership"),
                patient_share=result["patient_share"],
                patient_balance=result["patient_balance"],
            ),
        )
        db.commit()
    return reconcile(db, case, body.selection)
