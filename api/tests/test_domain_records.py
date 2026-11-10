"""Prompt 3 records: evidence documents, provider responses, approval records and PayPal
invoice/payment references (DB-backed). Also zero/negative amounts and overpayment
prevention at the approval boundary. No PayPal call is made; references are synthetic."""

import hashlib
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app import services as svc
from app.errors import DomainError, ImmutableRecordError, ValidationFailed
from app.models import (
    ApprovalRecord,
    EvidenceDocument,
    ExternalPayment,
    PayPalInvoiceRef,
    PayPalPaymentRef,
    ProviderResponse,
)
from app.seed import seed
from app.states import (
    CaseStatus,
    DataSource,
    DocumentType,
    LedgerEntryType,
    PaymentMethod,
    PayPalInvoiceStatus,
    PayPalPaymentSource,
    ProviderResponseType,
    UserRole,
)

PAYEE = "Synthetic City Hospital (Demo)"


@pytest.fixture
def demo(db):
    case = seed(db)
    actor = svc.Actor(user=case.payer, label="PAYER:demo")
    return case, actor


@pytest.fixture
def ready(db, demo):
    case, actor = demo
    svc.transition_case(db, actor, case.id, CaseStatus.READY_FOR_APPROVAL)
    return case, actor


def _flush_fails(db, obj, exc=IntegrityError):
    nested = db.begin_nested()
    db.add(obj)
    with pytest.raises(exc):
        db.flush()
    nested.rollback()


def _doc(case, **kw) -> EvidenceDocument:
    data = {
        "case_id": case.id,
        "document_type": DocumentType.BILL,
        "storage_key": f"private/{uuid.uuid4()}",
        "sha256": hashlib.sha256(uuid.uuid4().bytes).hexdigest(),
        "mime_type": "application/pdf",
        "file_size": 1024,
        "page_count": 2,
        "source_type": DataSource.SEEDED_SYNTHETIC,
        "uploaded_by_role": UserRole.RELATIVE,
    }
    data.update(kw)
    return EvidenceDocument(**data)


def _response(case, flag, **kw) -> ProviderResponse:
    data = {
        "case_id": case.id,
        "flag_id": flag.id,
        "response_type": ProviderResponseType.EXPLAIN,
        "response_text": "Second CBC was a repeat test ordered on the same day.",
        "currency": case.currency,
        "responder_label": "Provider billing desk (synthetic)",
        "actor_verification_method": "TEST_FIXTURE",
    }
    data.update(kw)
    return ProviderResponse(**data)


def _invoice(case, approval, **kw) -> PayPalInvoiceRef:
    data = {
        "case_id": case.id,
        "approval_id": approval.id,
        "paypal_invoice_id": f"INV2-TEST-{uuid.uuid4().hex[:8]}",
        "merchant_account_ref": "TESTMERCHANT",
        "currency": "USD",
        "invoice_total": Decimal("230.00"),
        "amount_due": Decimal("230.00"),
        "invoice_status": PayPalInvoiceStatus.SENT,
    }
    data.update(kw)
    return PayPalInvoiceRef(**data)


# ---------------------------------------------------------------- schema


def test_no_float_columns_exist(db):
    n = db.scalar(
        text(
            "SELECT count(*) FROM information_schema.columns WHERE table_schema='public' "
            "AND data_type IN ('real', 'double precision')"
        )
    )
    assert n == 0


# ---------------------------------------------------------------- seeded case


def test_seed_case_is_25000_split_4000_2000_19000(db, demo):
    case, _ = demo
    b = svc.get_buckets(db, case)
    assert b.bill_total == Decimal("25000.00")
    assert (b.already_paid, b.queried, b.payable_now) == (
        Decimal("4000.00"),
        Decimal("2000.00"),
        Decimal("19000.00"),
    )
    assert b.bill_total == b.already_paid + b.queried + b.payable_now
    # The queried 2000 is held, not deducted: the bill charges still sum to 25000.
    charged = sum(
        (
            e.amount
            for e in svc.case_ledger(db, case.id)
            if e.entry_type == LedgerEntryType.BILL_CHARGE
        ),
        Decimal("0"),
    )
    assert charged == Decimal("25000.00")


# ---------------------------------------------------------------- zero / negative amounts


@pytest.mark.parametrize("bad", ["0.00", "-1.00"])
def test_zero_or_negative_bill_line_rejected(db, actor, bad):
    case = svc.create_case(db, actor, patient_alias="P", currency="INR")
    with pytest.raises(ValidationFailed):
        svc.add_bill(
            db,
            actor,
            case.id,
            svc.BillInput(
                provider_name="H",
                currency="INR",
                lines=[svc.LineInput(1, "X", Decimal(bad))],
            ),
        )


@pytest.mark.parametrize("bad", ["0.00", "-500.00"])
def test_zero_or_negative_external_payment_rejected(db, actor, bad):
    case = svc.create_case(db, actor, patient_alias="P", currency="INR")
    with pytest.raises(ValidationFailed):
        svc.record_external_payment(
            db,
            actor,
            case.id,
            svc.PaymentInput(method=PaymentMethod.UPI, amount=Decimal(bad), currency="INR"),
        )


@pytest.mark.parametrize("bad", ["0.00", "-0.01"])
def test_ledger_helper_refuses_non_positive_amount(db, demo, bad):
    case, actor = demo
    with pytest.raises(DomainError):
        svc._ledger(db, actor, case, LedgerEntryType.BILL_CHARGE, Decimal(bad), "x")


# ---------------------------------------------------------------- approvals / overpayment


def test_approval_snapshots_buckets(db, ready):
    case, actor = ready
    a = svc.record_approval(db, actor, case.id, Decimal("19000.00"), PAYEE)
    db.expire_all()
    a = db.get(ApprovalRecord, a.id)
    assert (a.approved_amount, a.bill_total, a.payable_now, a.queried, a.already_paid) == (
        Decimal("19000.00"),
        Decimal("25000.00"),
        Decimal("19000.00"),
        Decimal("2000.00"),
        Decimal("4000.00"),
    )
    assert a.currency == "INR" and a.payee_label == PAYEE
    assert a.ledger_seq == max(e.seq for e in svc.case_ledger(db, case.id))
    events = [e.event_type for e in svc.case_audit(db, case.id)]
    assert events.count("PAYMENT_APPROVED") == 1


@pytest.mark.parametrize("amount", ["19000.01", "21000.00", "23000.00", "25000.00", "18999.99"])
def test_approval_must_equal_payable_now(db, ready, amount):
    # Approving more would pay the queried or already-paid amount again.
    case, actor = ready
    with pytest.raises(ValidationFailed):
        svc.record_approval(db, actor, case.id, Decimal(amount), PAYEE)
    assert svc.case_approvals(db, case.id) == []


def test_approval_rejects_sub_paise_and_float(db, ready):
    case, actor = ready
    from app.money import MoneyError

    with pytest.raises(MoneyError):
        svc.record_approval(db, actor, case.id, Decimal("19000.001"), PAYEE)
    with pytest.raises(MoneyError):
        svc.record_approval(db, actor, case.id, 19000.0, PAYEE)


def test_same_figures_cannot_be_approved_twice(db, ready):
    case, actor = ready
    svc.record_approval(db, actor, case.id, Decimal("19000.00"), PAYEE)
    with pytest.raises(DomainError):
        svc.record_approval(db, actor, case.id, Decimal("19000.00"), PAYEE)
    assert len(svc.case_approvals(db, case.id)) == 1


def test_approval_requires_ready_for_approval(db, demo):
    case, actor = demo
    assert case.status == CaseStatus.UNDER_REVIEW
    with pytest.raises(DomainError):
        svc.record_approval(db, actor, case.id, Decimal("19000.00"), PAYEE)


def test_db_rejects_approval_above_payable(db, ready):
    case, actor = ready
    _flush_fails(
        db,
        ApprovalRecord(
            case_id=case.id,
            approved_by=actor.user_id,
            actor_label="x",
            currency="INR",
            approved_amount=Decimal("21000.00"),
            bill_total=Decimal("25000.00"),
            payable_now=Decimal("19000.00"),
            queried=Decimal("2000.00"),
            already_paid=Decimal("4000.00"),
            payee_label=PAYEE,
            ledger_seq=1,
        ),
    )


def test_db_rejects_unbalanced_snapshot(db, ready):
    case, actor = ready
    _flush_fails(
        db,
        ApprovalRecord(
            case_id=case.id,
            approved_by=actor.user_id,
            actor_label="x",
            currency="INR",
            approved_amount=Decimal("21000.00"),
            bill_total=Decimal("25000.00"),
            payable_now=Decimal("21000.00"),  # queried silently deducted: 21000+2000+4000
            queried=Decimal("2000.00"),
            already_paid=Decimal("4000.00"),
            payee_label=PAYEE,
            ledger_seq=1,
        ),
    )


def test_approval_is_append_only(db, ready):
    case, actor = ready
    a = svc.record_approval(db, actor, case.id, Decimal("19000.00"), PAYEE)
    a.approved_amount = Decimal("21000.00")
    with pytest.raises(ImmutableRecordError):
        db.flush()
    db.rollback()
    for sql in ("UPDATE approval_records SET note = 'x'", "DELETE FROM approval_records"):
        nested = db.begin_nested()
        with pytest.raises(DBAPIError, match="append-only"):
            db.execute(text(sql))
        nested.rollback()


# ---------------------------------------------------------------- evidence documents


def test_evidence_document_only_extraction_status_may_change(db, demo):
    case, _ = demo
    doc = _doc(case)
    db.add(doc)
    db.flush()
    nested = db.begin_nested()
    db.execute(text("UPDATE evidence_documents SET extraction_status = 'EXTRACTED'"))
    nested.commit()
    for sql in (
        "UPDATE evidence_documents SET storage_key = 'public/x'",
        "UPDATE evidence_documents SET sha256 = repeat('0', 64)",
        "DELETE FROM evidence_documents",
    ):
        nested = db.begin_nested()
        with pytest.raises(DBAPIError, match="immutable|append-only"):
            db.execute(text(sql))
        nested.rollback()


def test_evidence_document_orm_guard(db, demo):
    case, _ = demo
    doc = _doc(case)
    db.add(doc)
    db.flush()
    doc.file_size = 1
    with pytest.raises(ImmutableRecordError):
        db.flush()
    db.rollback()


@pytest.mark.parametrize(
    "kw",
    [
        {"mime_type": "text/html"},
        {"sha256": "not-a-hash"},
        {"file_size": 0},
        {"page_count": 0},
    ],
)
def test_evidence_document_constraints(db, demo, kw):
    case, _ = demo
    _flush_fails(db, _doc(case, **kw))


def test_duplicate_document_in_case_rejected(db, demo):
    case, _ = demo
    first = _doc(case)
    db.add(first)
    db.flush()
    _flush_fails(db, _doc(case, sha256=first.sha256))


# ---------------------------------------------------------------- provider responses


def test_provider_response_does_not_change_buckets(db, demo):
    case, _ = demo
    [flag] = svc.case_flags(db, case.id)
    doc = _doc(case, document_type=DocumentType.PROVIDER_SUPPORTING)
    db.add(doc)
    db.flush()
    db.add(
        _response(
            case,
            flag,
            response_type=ProviderResponseType.CORRECT,
            corrected_amount=Decimal("0.00"),
            supporting_document_id=doc.id,
        )
    )
    db.flush()
    b = svc.get_buckets(db, case)
    assert (b.payable_now, b.queried, b.already_paid) == (
        Decimal("19000.00"),
        Decimal("2000.00"),
        Decimal("4000.00"),
    )


@pytest.mark.parametrize(
    "kw",
    [
        {"response_type": ProviderResponseType.CORRECT},  # no corrected amount
        {"response_type": ProviderResponseType.EXPLAIN, "corrected_amount": Decimal("1.00")},
        {"response_type": ProviderResponseType.CORRECT, "corrected_amount": Decimal("-1.00")},
        {"response_text": "   "},
    ],
)
def test_provider_response_constraints(db, demo, kw):
    case, _ = demo
    [flag] = svc.case_flags(db, case.id)
    _flush_fails(db, _response(case, flag, **kw))


def test_provider_response_is_append_only(db, demo):
    case, _ = demo
    [flag] = svc.case_flags(db, case.id)
    r = _response(case, flag)
    db.add(r)
    db.commit()
    r.response_text = "edited"
    with pytest.raises(ImmutableRecordError):
        db.flush()
    db.rollback()
    for sql in (
        "UPDATE provider_responses SET response_text = 'x'",
        "DELETE FROM provider_responses",
    ):
        nested = db.begin_nested()
        with pytest.raises(DBAPIError, match="append-only"):
            db.execute(text(sql))
        nested.rollback()


# ---------------------------------------------------------------- PayPal references


def test_paypal_invoice_ref_lifecycle(db, ready):
    case, actor = ready
    a = svc.record_approval(db, actor, case.id, Decimal("19000.00"), PAYEE)
    inv = _invoice(case, a)
    db.add(inv)
    db.commit()
    # Status and amount due follow PayPal GET results.
    inv.invoice_status = PayPalInvoiceStatus.PARTIALLY_PAID
    inv.amount_due = Decimal("190.00")
    inv.last_verified_at = datetime.now(UTC)
    db.commit()
    inv.invoice_total = Decimal("1.00")
    with pytest.raises(ImmutableRecordError):
        db.flush()
    db.rollback()
    for sql in (
        "UPDATE paypal_invoice_refs SET paypal_invoice_id = 'other'",
        "UPDATE paypal_invoice_refs SET invoice_total = 1",
        "DELETE FROM paypal_invoice_refs",
    ):
        nested = db.begin_nested()
        with pytest.raises(DBAPIError, match="immutable|append-only"):
            db.execute(text(sql))
        nested.rollback()


def test_one_invoice_per_approval_and_unique_paypal_id(db, ready):
    case, actor = ready
    a = svc.record_approval(db, actor, case.id, Decimal("19000.00"), PAYEE)
    first = _invoice(case, a)
    db.add(first)
    db.flush()
    _flush_fails(db, _invoice(case, a))  # second invoice for the same approval


@pytest.mark.parametrize(
    "kw",
    [
        {"invoice_total": Decimal("0.00"), "amount_due": Decimal("0.00")},
        {"amount_due": Decimal("230.01")},  # due above total
        {"amount_due": Decimal("-1.00")},
        {"currency": "usd"},
    ],
)
def test_paypal_invoice_ref_constraints(db, ready, kw):
    case, actor = ready
    a = svc.record_approval(db, actor, case.id, Decimal("19000.00"), PAYEE)
    _flush_fails(db, _invoice(case, a, **kw))


def test_paypal_payment_refs(db, ready):
    case, actor = ready
    a = svc.record_approval(db, actor, case.id, Decimal("19000.00"), PAYEE)
    inv = _invoice(case, a)
    db.add(inv)
    db.flush()
    ext = db.scalar(select(ExternalPayment).where(ExternalPayment.case_id == case.id))
    now = datetime.now(UTC)
    common = {"case_id": case.id, "invoice_ref_id": inv.id, "currency": "USD", "verified_at": now}
    db.add_all(
        [
            PayPalPaymentRef(
                **common,
                paypal_transaction_id="EXTR-TEST-1",
                payment_source=PayPalPaymentSource.EXTERNAL,
                external_payment_id=ext.id,
                amount=Decimal("40.00"),
                paypal_status="COMPLETED",
            ),
            PayPalPaymentRef(
                **common,
                paypal_transaction_id="PAY-TEST-1",
                payment_source=PayPalPaymentSource.PAYPAL,
                amount=Decimal("190.00"),
                paypal_status="COMPLETED",
            ),
        ]
    )
    db.flush()
    bad = [
        {"paypal_transaction_id": "PAY-TEST-1", "payment_source": PayPalPaymentSource.PAYPAL},
        {"paypal_transaction_id": "Z1", "payment_source": PayPalPaymentSource.EXTERNAL},
        {
            "paypal_transaction_id": "Z2",
            "payment_source": PayPalPaymentSource.PAYPAL,
            "external_payment_id": ext.id,
        },
    ]
    for kw in bad:
        _flush_fails(
            db,
            PayPalPaymentRef(**common, amount=Decimal("1.00"), paypal_status="COMPLETED", **kw),
        )
    for amount in ("0.00", "-1.00"):
        _flush_fails(
            db,
            PayPalPaymentRef(
                **common,
                paypal_transaction_id=f"NEG-{amount}",
                payment_source=PayPalPaymentSource.PAYPAL,
                amount=Decimal(amount),
                paypal_status="COMPLETED",
            ),
        )
    for sql in ("UPDATE paypal_payment_refs SET amount = 1", "DELETE FROM paypal_payment_refs"):
        nested = db.begin_nested()
        with pytest.raises(DBAPIError, match="append-only"):
            db.execute(text(sql))
        nested.rollback()
