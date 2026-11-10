"""Mocked payment domain regressions. Lead serializes all database execution."""

import copy
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app import payments
from app import services as svc
from app.config import Settings
from app.errors import DomainError
from app.models import ApprovalRecord, LedgerEntry, PaymentOperation
from app.paypal_client import PayPalError
from app.states import CaseStatus, FlagStatus, PaymentMethod


class FakePayPal:
    def __init__(self):
        self.settings = Settings(
            _env_file=None,
            paypal_enabled=True,
            paypal_client_id="synthetic-app",
            paypal_client_secret="synthetic-secret",
            paypal_expected_merchant_id="SYNTHETICMERCHANT",
            paypal_binding_capture_id="BINDCAPTURE",
            paypal_provider_email="provider@example.invalid",
            paypal_buyer_email="buyer@example.invalid",
        )
        self.fingerprint = "a" * 64
        self.posts = []
        self.inv = None
        self.fail_stage = None
        self.completed = False
        self.invoice_id = "INV2-SYNTHETIC"
        self.capture_status = "COMPLETED"
        self.capture_amount = "190.00"
        self.capture_currency = "USD"
        self.capture_payee = "SYNTHETICMERCHANT"

    def require_config(self):
        pass

    def capture(self, capture_id):
        return {
            "id": capture_id,
            "status": self.capture_status,
            "payee": {"merchant_id": self.capture_payee},
            "amount": {"currency_code": self.capture_currency, "value": self.capture_amount},
        }

    def request(self, method, path, body=None, request_id=None):
        assert method == "POST"
        self.posts.append((path, copy.deepcopy(body)))
        if path == "/v2/invoicing/invoices":
            self.inv = {
                **copy.deepcopy(body),
                "id": self.invoice_id,
                "status": "DRAFT",
                "amount": {"currency_code": "USD", "value": "230.00"},
                "due_amount": {"currency_code": "USD", "value": "230.00"},
                "payments": {"transactions": []},
            }
            response = {"id": self.inv["id"]}
            stage = "CREATE"
        elif path.endswith("/send"):
            assert body == {"send_to_invoicer": False, "send_to_recipient": False}
            self.inv["status"] = "SENT"
            response, stage = {}, "SEND"
        else:
            self.inv["payments"]["transactions"].append(
                {**body, "payment_id": "EXTR-SYNTHETIC", "type": "EXTERNAL"}
            )
            self.inv["due_amount"]["value"] = "190.00"
            self.inv["status"] = "PARTIALLY_PAID"
            response, stage = {"payment_id": "EXTR-SYNTHETIC"}, "EXTERNAL"
        if self.fail_stage == stage:
            raise PayPalError("SYNTHETIC_TIMEOUT", uncertain=True)
        return response

    def invoice(self, invoice_id):
        inv = copy.deepcopy(self.inv)
        if self.completed:
            inv["payments"]["transactions"].append(
                {
                    "payment_id": "PAYPALCAPTURE",
                    "type": "PAYPAL",
                    "amount": {"currency_code": "USD", "value": "190.00"},
                }
            )
            inv["status"], inv["due_amount"]["value"] = "PAID", "0.00"
        return inv


def payment_case(db, actor):
    case = svc.create_case(
        db, actor, patient_alias="Synthetic payment", currency="USD", is_demo=True
    )
    bill = svc.add_bill(
        db,
        actor,
        case.id,
        svc.BillInput(
            provider_name="Synthetic Clinic",
            currency="USD",
            bill_date=date(2026, 11, 9),
            printed_total=Decimal("230.00"),
            printed_advance_paid=Decimal("40.00"),
            lines=[svc.LineInput(1, "Reviewed services", Decimal("230.00"), date(2026, 11, 9))],
        ),
    )
    svc.accept_line(db, actor, bill.line_items[0].id)
    p = svc.record_external_payment(
        db,
        actor,
        case.id,
        svc.PaymentInput(
            method=PaymentMethod.OTHER,
            amount=Decimal("40.00"),
            currency="USD",
            paid_on=date(2026, 11, 9),
            reference="SYNTHETIC-PRIOR",
            payee_name="Synthetic Clinic",
            bill_id=bill.id,
        ),
    )
    svc.reconcile_external_payment(db, actor, p.id)
    svc.run_checks(db, actor, case.id)
    for f in svc.case_flags(db, case.id):
        if f.status == FlagStatus.OPEN:
            svc.change_flag_status(
                db, actor, f.id, FlagStatus.DISMISSED, "Reviewed synthetic evidence"
            )
    case.status = CaseStatus.READY_FOR_APPROVAL
    db.commit()
    return case, bill


def approved(db, actor, fake):
    case, bill = payment_case(db, actor)
    payments.verify_binding(db, actor, case.id, fake)
    p = payments.preview(db, case, fake)
    a = payments.approve(
        db,
        actor,
        case.id,
        fake,
        state_fingerprint=p["state_fingerprint"],
        amount="190.00",
        currency="USD",
        purpose="Reviewed synthetic diagnostic services",
        confirmed=True,
    )
    return case, bill, a


def test_exact_approval_invoice_and_authoritative_unique_credit(db, actor):
    fake = FakePayPal()
    case, bill, a = approved(db, actor, fake)
    assert a.composition["invoice_total"] == "230.00"
    assert a.composition["external_total"] == "40.00"
    payments.start_invoice(db, actor, case.id, fake, a.id)
    assert len(fake.posts) == 3
    assert svc.get_buckets(db, case).already_paid == Decimal("40.00")
    fake.completed = True
    payments.verify(db, actor, case.id, fake)
    payments.verify(db, actor, case.id, fake)
    assert svc.get_buckets(db, case).already_paid == Decimal("230.00")
    assert svc.get_buckets(db, case).payable_now == Decimal("0.00")
    assert payments.workspace(db, actor, case.id, fake)["state"] == "PAID"
    assert len([e for e in svc.case_ledger(db, case.id) if e.entry_type == "PAYPAL_PAYMENT"]) == 1
    payments.start_invoice(db, actor, case.id, fake, a.id)
    assert len(fake.posts) == 3


@pytest.mark.parametrize("stage", ["CREATE", "SEND", "EXTERNAL"])
def test_ambiguous_stage_never_reposts_and_recovers_by_get(db, actor, stage):
    fake = FakePayPal()
    case, bill, a = approved(db, actor, fake)
    fake.fail_stage = stage
    payments.start_invoice(db, actor, case.id, fake, a.id)
    count = len(fake.posts)
    assert payments.workspace(db, actor, case.id, fake)["state"] == "UNCERTAIN"
    payments.start_invoice(db, actor, case.id, fake, a.id)
    assert len(fake.posts) == count
    payments.verify(db, actor, case.id, fake, "INV2-SYNTHETIC")
    op = db.scalar(select(PaymentOperation).where(PaymentOperation.case_id == case.id))
    assert op.paypal_invoice_id == "INV2-SYNTHETIC"
    assert len(fake.posts) == count
    with pytest.raises(DomainError, match="frozen"):
        svc.query_line(db, actor, bill.line_items[0].id, "Cannot alter approved invoice")


def test_nonledger_change_stales_approval_before_network(db, actor):
    fake = FakePayPal()
    case, bill, a = approved(db, actor, fake)
    bill.line_items[0].status_note = "Changed reviewed evidence"
    db.commit()
    with pytest.raises(DomainError, match="stale"):
        payments.start_invoice(db, actor, case.id, fake, a.id)
    assert fake.posts == []


def test_wrong_payee_capture_never_creates_paid_credit(db, actor):
    fake = FakePayPal()
    case, bill, a = approved(db, actor, fake)
    payments.start_invoice(db, actor, case.id, fake, a.id)
    fake.completed, fake.capture_payee = True, "OTHERACCOUNT"
    payments.verify(db, actor, case.id, fake)
    assert svc.get_buckets(db, case).already_paid == Decimal("40.00")
    assert payments.workspace(db, actor, case.id, fake)["state"] == "RECONCILIATION_REQUIRED"


def test_approval_is_immutable_and_snapshot_has_exact_amounts(db, actor):
    fake = FakePayPal()
    case, bill, a = approved(db, actor, fake)
    a = db.get(ApprovalRecord, a.id)
    assert a.account_binding["merchant_ref"] == "SYNTHETICMERCHANT"
    assert (
        payments.workspace(db, actor, case.id, fake)["approval"]["snapshot"]["collect_amount"]
        == "190.00"
    )
    assert not db.scalars(
        select(LedgerEntry).where(
            LedgerEntry.case_id == case.id, LedgerEntry.entry_type == "PAYPAL_PAYMENT"
        )
    ).all()


@pytest.mark.parametrize(
    "defect",
    [
        "PENDING",
        "WRONG_AMOUNT",
        "WRONG_CURRENCY",
        "REFUND",
        "EXTERNAL_ONLY",
        "TIP_ENABLED",
        "WRONG_DATE",
    ],
)
def test_adversarial_authoritative_states_never_credit_unverified_payment(db, actor, defect):
    fake = FakePayPal()
    case, bill, a = approved(db, actor, fake)
    payments.start_invoice(db, actor, case.id, fake, a.id)
    fake.completed = defect not in ("EXTERNAL_ONLY", "WRONG_DATE", "TIP_ENABLED")
    if defect == "PENDING":
        fake.capture_status = "PENDING"
    elif defect == "WRONG_AMOUNT":
        fake.capture_amount = "189.99"
    elif defect == "WRONG_CURRENCY":
        fake.capture_currency = "EUR"
    elif defect == "REFUND":
        fake.inv["refunds"] = {
            "transactions": [{"amount": {"currency_code": "USD", "value": "1.00"}}]
        }
    elif defect == "EXTERNAL_ONLY":
        fake.inv["status"], fake.inv["due_amount"]["value"] = "PAID", "0.00"
    elif defect == "TIP_ENABLED":
        fake.inv["configuration"]["allow_tip"] = True
    elif defect == "WRONG_DATE":
        fake.inv["payments"]["transactions"][0]["payment_date"] = "2026-11-08"
    payments.verify(db, actor, case.id, fake)
    assert svc.get_buckets(db, case).already_paid == Decimal("40.00")
    expected = "VERIFICATION_PENDING" if defect == "PENDING" else "RECONCILIATION_REQUIRED"
    assert payments.workspace(db, actor, case.id, fake)["state"] == expected


def test_capture_cannot_credit_a_second_case(db, actor):
    first = FakePayPal()
    case, bill, a = approved(db, actor, first)
    payments.start_invoice(db, actor, case.id, first, a.id)
    first.completed = True
    payments.verify(db, actor, case.id, first)
    second = FakePayPal()
    second.invoice_id = "INV2-SECOND"
    other, other_bill, other_a = approved(db, actor, second)
    payments.start_invoice(db, actor, other.id, second, other_a.id)
    second.completed = True
    payments.verify(db, actor, other.id, second)
    assert svc.get_buckets(db, other).already_paid == Decimal("40.00")
    assert payments.workspace(db, actor, other.id, second)["state"] == "RECONCILIATION_REQUIRED"


def test_reserved_payment_freezes_provider_capability_and_payer_resolution(db, actor):
    from app import providers
    from app.states import ProviderDecisionType, ProviderResponseType
    from tests.test_prompt6_acceptance import _case

    case, bill, line, flag = _case(db, actor)
    case.is_demo = True
    db.commit()
    link, token = providers.create_link(db, actor, flag.id, line.id, "Clarify the held panel")
    response = providers.respond(
        db, token, ProviderResponseType.EXPLAIN, "Both panels supplied", "Synthetic desk"
    )
    decision_preview = providers.preview(db, actor, response.id)
    fake = FakePayPal()
    payments.verify_binding(db, actor, case.id, fake)
    p = payments.preview(db, case, fake)
    a = payments.approve(
        db,
        actor,
        case.id,
        fake,
        state_fingerprint=p["state_fingerprint"],
        amount="190.00",
        currency="USD",
        purpose="Only the reviewed payable portion",
        confirmed=True,
    )
    payments.start_invoice(db, actor, case.id, fake, a.id)
    with pytest.raises(DomainError, match="frozen"):
        providers.decide(
            db,
            actor,
            response.id,
            ProviderDecisionType.ACCEPT,
            "Reviewed response",
            decision_preview["state_fingerprint"],
        )
    with pytest.raises(DomainError, match="frozen"):
        providers.revoke_link(db, actor, link.id, "Revoke after invoice")


def test_reserved_payment_freezes_upload_extraction_and_receipt_changes(db, actor):
    import uuid

    from app.documents.service import create_upload_link
    from app.extraction.service import add_revision, promote_extraction
    from app.models import DocumentExtraction, EvidenceDocument
    from app.states import DataSource, DocumentType, ExtractionStatus

    fake = FakePayPal()
    case, bill = payment_case(db, actor)
    doc = EvidenceDocument(
        id=uuid.uuid4(),
        case_id=case.id,
        document_type=DocumentType.PROVIDER_SUPPORTING,
        storage_key="synthetic-freeze-source",
        sha256="0" * 64,
        mime_type="application/pdf",
        file_size=10,
        page_count=1,
        source_type=DataSource.SEEDED_SYNTHETIC,
        extraction_status=ExtractionStatus.EXTRACTED,
    )
    db.add(doc)
    db.flush()
    extraction = DocumentExtraction(
        id=uuid.uuid4(),
        case_id=case.id,
        document_id=doc.id,
        schema_version="synthetic",
        provider="mock",
        model="mock",
        prompt_version="synthetic",
        payload={},
        raw_output_sha256="1" * 64,
        actor_label="synthetic",
    )
    db.add(extraction)
    db.commit()
    payments.verify_binding(db, actor, case.id, fake)
    p = payments.preview(db, case, fake)
    a = payments.approve(
        db,
        actor,
        case.id,
        fake,
        state_fingerprint=p["state_fingerprint"],
        amount="190.00",
        currency="USD",
        purpose="Freeze synthetic evidence",
        confirmed=True,
    )
    payments.start_invoice(db, actor, case.id, fake, a.id)
    actions = [
        lambda: create_upload_link(db, actor, case.id, [DocumentType.BILL]),
        lambda: add_revision(db, actor, extraction.id, [], ["currency"], "Review evidence"),
        lambda: promote_extraction(db, actor, extraction.id),
        lambda: svc.reconcile_external_payment(db, actor, svc.case_payments(db, case.id)[0].id),
    ]
    for action in actions:
        with pytest.raises(DomainError, match="frozen"):
            action()


def test_database_freeze_rejects_external_ref_as_paypal_credit(db, actor):
    import uuid

    from sqlalchemy import insert
    from sqlalchemy.exc import IntegrityError

    from app.models import PayPalPaymentRef

    fake = FakePayPal()
    case, bill, a = approved(db, actor, fake)
    payments.start_invoice(db, actor, case.id, fake, a.id)
    external = db.scalar(
        select(PayPalPaymentRef).where(
            PayPalPaymentRef.case_id == case.id, PayPalPaymentRef.payment_source == "EXTERNAL"
        )
    )
    with pytest.raises(IntegrityError), db.begin_nested():
        db.execute(
            insert(LedgerEntry).values(
                id=uuid.uuid4(),
                case_id=case.id,
                entry_type="PAYPAL_PAYMENT",
                amount=external.amount,
                currency="USD",
                paypal_payment_ref_id=external.id,
                reason="Rejected raw SQL counterfeit credit",
                actor_label="synthetic-test",
            )
        )
    assert svc.get_buckets(db, case).already_paid == Decimal("40.00")
