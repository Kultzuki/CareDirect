"""Readable, fully synthetic UI showcase. Appends only to caredirect_test; no remote calls."""

import os

from app.config import Settings

os.environ["DATABASE_URL"] = Settings().test_database_url
os.environ["DEEPSEEK_API_KEY"] = " "
os.environ["GEMINI_API_KEY"] = " "

import json
from datetime import date
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import family, insurance
from app import services as svc
from app.db import engine
from app.documents import service as docs
from app.documents.storage import get_storage
from app.extraction import service as extraction
from app.extraction.synthetic import SyntheticFixture, render
from app.models import User
from app.states import DocumentType, ExternalPaymentStatus


def source_document(
    db, actor, case, kind, number, rows=(), insurance_values=None, receipt_values=None
):
    lines = []
    counter = 0

    def field(value, label):
        nonlocal counter
        if value is None:
            return dict(value=None)
        page = counter // 28 + 1
        snippet = f"{label}: {value}"
        lines.append(snippet)
        counter += 1
        return dict(
            value=value,
            confidence="0.990",
            source=dict(document_id="{document_id}", page=page, snippet=snippet),
        )

    raw = dict(
        schema_version="caredirect.extraction.v1",
        document_id="{document_id}",
        document_type=kind,
        provider_name=field("Sample Hospital", "Provider"),
        provider_identifier=field("SYN-HOSP", "Provider code"),
        patient_reference=field("SYN-PARENT", "Patient reference"),
        invoice_number=field(number, "Document reference"),
        invoice_date=field("2026-11-09", "Date"),
        currency=field("INR", "Currency"),
        line_items=[],
        receipt=None,
    )
    for i, (description, code, amount, when) in enumerate(rows, 1):
        raw["line_items"].append(
            dict(
                line_number=i,
                description=field(description, f"Line {i} description"),
                code=field(code, f"Line {i} code"),
                service_date=field(when, f"Line {i} service date"),
                quantity=field("1", f"Line {i} quantity"),
                unit_price=field(amount, f"Line {i} unit price"),
                line_total=field(amount, f"Line {i} amount"),
            )
        )
    total = "80000.00" if kind == "BILL" else "75000.00" if kind == "ESTIMATE" else None
    raw.update(
        subtotal=field(total, "Subtotal"),
        tax_total=field("0.00" if total else None, "Tax"),
        total=field(total, "Total"),
        advance_paid=field("5000.00" if kind == "BILL" else None, "Prior family payment"),
    )
    if insurance_values:
        raw["insurance"] = {
            key: field(value, key.replace("_", " ")) for key, value in insurance_values.items()
        }
    if receipt_values:
        raw["receipt"] = {
            key: field(value, key.replace("_", " ")) for key, value in receipt_values.items()
        }
    pages = [
        ["CAREDIRECT SYNTHETIC DEMO - NOT A REAL MEDICAL DOCUMENT", number, ""] + lines[i : i + 28]
        for i in range(0, len(lines), 28)
    ]
    content = render(SyntheticFixture(number, kind, "application/pdf", pages, {}))
    storage = get_storage()
    _, token = docs.create_upload_link(db, actor, case.id, [DocumentType(kind)], 1)
    document, _ = docs.receive_upload(
        db, storage, docs.get_upload_limits(), token, DocumentType(kind), "application/pdf", content
    )

    class Adapter:
        provider = "mock"
        model = "readable-ui-showcase"
        prompt_version = "ui-showcase-v1"

        def extract(self, **kwargs):
            return json.loads(json.dumps(raw).replace("{document_id}", str(kwargs["document_id"])))

    row = extraction.extract_document(db, actor, storage, Adapter(), document.id)
    loaded = extraction._load(db, row)
    extraction.add_revision(
        db,
        actor,
        row.id,
        [],
        [f.info.path for f in loaded.fields if f.value is not None],
        "Generator-checked synthetic fixture values; not independent human OCR acceptance.",
    )
    return document, row


if __name__ == "__main__":
    if not os.environ["DATABASE_URL"].endswith("/caredirect_test"):
        raise RuntimeError("Showcase requires caredirect_test")
    with Session(engine, expire_on_commit=False) as db:
        owner = db.scalar(select(User).where(User.email == "payer@demo.invalid"))
        if not owner:
            raise RuntimeError("Run tests.family_browser_setup first")
        actor = svc.Actor(owner, "Synthetic showcase setup")
        case = svc.create_case(
            db,
            actor,
            patient_alias="Parent (sample patient)",
            currency="INR",
            episode_title="Parent’s hospital care — sample record",
            is_demo=True,
        )
        db.commit()
        users = [
            db.scalar(select(User).where(User.email == email))
            for email in (
                "daughter@family.invalid",
                "uk@family.invalid",
                "india@family.invalid",
                "parent@family.invalid",
            )
        ]
        for index, user in enumerate(users):
            invite = family.invite(
                db,
                actor,
                case.id,
                family.InviteRequest(
                    recipient_email=user.email,
                    role="PATIENT" if index == 3 else "PAYER",
                    can_review=index == 0,
                    can_approve=index == 1,
                ),
            )
            family.accept_invitation(db, svc.Actor(user, user.display_name), invite["token"])
        for user, amount in zip(users[:3], ("30000", "20000", "10000"), strict=True):
            family.contribute(
                db,
                actor,
                case.id,
                family.ContributionRequest(
                    user_id=user.id,
                    amount=amount,
                    currency="INR",
                    contributed_on=date(2026, 11, 9),
                    note="Sample family contribution",
                    request_id=uuid4().hex,
                ),
            )
        final_rows = [
            ("Hospital treatment package", "HSP-1", "79400.00", "2026-11-07"),
            ("CBC Test", "CBC-1", "200.00", "2026-11-08"),
            ("CBC Test", "CBC-1", "200.00", "2026-11-08"),
            ("Haemogram", None, "200.00", "2026-11-08"),
        ]
        estimate_rows = [
            ("Hospital treatment package", "HSP-1", "74400.00", "2026-11-07"),
            *final_rows[1:],
        ]
        source_document(db, actor, case, "ESTIMATE", "SYN-EST-75000", estimate_rows)
        bill_doc, bill_extraction = source_document(
            db, actor, case, "BILL", "SYN-HOSP-80000", final_rows
        )
        bill, _ = extraction.promote_extraction(db, actor, bill_extraction.id)
        for line in bill.line_items:
            svc.accept_line(db, actor, line.id)
        base = dict(
            insurer_name="Sample Insurance",
            claim_reference="SYN-CLAIM-1",
            bill_reference="SYN-HOSP-80000",
        )
        preauth, _ = source_document(
            db,
            actor,
            case,
            "INSURANCE_PREAUTH",
            "SYN-PREAUTH",
            insurance_values={**base, "approved_amount": "60000.00"},
        )
        settlement, _ = source_document(
            db,
            actor,
            case,
            "INSURANCE_SETTLEMENT",
            "SYN-SETTLEMENT",
            insurance_values={
                **base,
                "claimed_total": "80000.00",
                "approved_amount": "55000.00",
                "copay": "5000.00",
                "deductible": "0.00",
                "noncovered": "10000.00",
                "pending": "10000.00",
                "rejected": "0.00",
                "stated_reason": ("Co-pay 5000; non-covered consumables 10000; "
                                  "remaining claim 10000 pending documents."),
            },
        )
        remittance, _ = source_document(
            db,
            actor,
            case,
            "INSURER_PAYMENT",
            "SYN-REMITTANCE",
            insurance_values={
                **base,
                "insurer_paid": "40000.00",
                "payment_reference": "SYN-REMIT-1",
                "payment_recipient": "Sample Hospital",
                "paid_on": "2026-11-09",
            },
        )
        _, receipt = source_document(
            db,
            actor,
            case,
            "RECEIPT",
            "SYN-RECEIPT",
            receipt_values=dict(
                amount="5000.00",
                paid_on="2026-11-09",
                transaction_reference="SYN-FAMILY-CASH",
                payee_name="Sample Hospital",
                payment_method="CASH",
            ),
        )
        _, payment = extraction.promote_extraction(db, actor, receipt.id)
        svc.reconcile_external_payment(db, actor, payment.id)
        if payment.status == ExternalPaymentStatus.NEEDS_CLARIFICATION:
            svc.confirm_external_payment(
                db, actor, payment.id, "Synthetic receipt checked against generated source."
            )
        selection = insurance.Selection(
            bill_id=bill.id,
            preauth_id=preauth.id,
            settlement_id=settlement.id,
            insurer_payment_ids=[remittance.id],
        )
        comparison = insurance.reconcile(db, case, selection)
        insurance.confirm_review(
            db,
            actor,
            case.id,
            insurance.ReviewRequest(
                selection=selection,
                input_fingerprint=comparison["input_fingerprint"],
                note="Synthetic document membership and separate components verified by generator.",
            ),
        )
        _, fingerprint = family.line_basis(db, bill.line_items[0])
        family.allocate(
            db,
            actor,
            case.id,
            family.AllocationRequest(
                line_item_id=bill.line_items[0].id,
                source_fingerprint=fingerprint,
                shares=[
                    family.Share(user_id=u.id, amount=a)
                    for u, a in zip(users[:3], ("30000", "20000", "10000"), strict=True)
                ],
                request_id=uuid4().hex,
                note="Sample family cost-sharing plan; no money is sent.",
            ),
        )
        svc.run_checks(db, actor, case.id)
        output = dict(case_id=str(case.id), bill_document_id=str(bill_doc.id))
        print(json.dumps(output))
