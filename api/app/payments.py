"""Exact human approval, single-attempt reservation and authoritative reconciliation."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select

from app import services as svc
from app.errors import DomainError, NotFound, ValidationFailed
from app.models import (
    ApprovalRecord,
    Bill,
    BillingFlag,
    BillLineItem,
    CareCase,
    DocumentExtraction,
    EvidenceDocument,
    ExternalPayment,
    ExtractionRevision,
    LedgerEntry,
    PaymentOperation,
    PayPalAccountBinding,
    PayPalInvoiceRef,
    PayPalPaymentRef,
    ProviderDecision,
    ProviderLink,
    ProviderResponse,
)
from app.money import ZERO, money, to_str
from app.paypal_client import PayPalError, resource_id, safe_checkout_url
from app.states import (
    ExternalPaymentStatus,
    LedgerEntryType,
    PayPalInvoiceStatus,
    PayPalPaymentSource,
)

BASIS = (
    "Configured completed Sandbox capture confirms this REST app's receiving account; "
    "not legal provider identity verification."
)


class PaymentReconciliationError(DomainError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


MANUAL_RECONCILIATION_CODES = frozenset({"REFUND_OBSERVED", "CAPTURE_REVERSED"})


def _now():
    return datetime.now(UTC)


def _lock(db, case_id, actor=None):
    case = db.scalar(
        select(CareCase)
        .where(CareCase.id == case_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if case is None:
        raise NotFound("Case unavailable.")
    if actor:
        svc._require_payment_approver(case, actor)
    db.expire_all()
    return db.get(CareCase, case_id)


def _op(db, case_id):
    return db.scalar(
        select(PaymentOperation)
        .where(PaymentOperation.case_id == case_id)
        .execution_options(populate_existing=True)
    )


def _binding(db, client):
    return db.scalar(
        select(PayPalAccountBinding)
        .where(
            PayPalAccountBinding.client_fingerprint == client.fingerprint,
            PayPalAccountBinding.merchant_ref == client.settings.paypal_expected_merchant_id,
            PayPalAccountBinding.capture_ref == client.settings.paypal_binding_capture_id,
        )
        .order_by(PayPalAccountBinding.verified_at.desc())
    )


def verify_binding(db, actor, case_id, client):
    _lock(db, case_id, actor)
    client.require_config()
    capture = client.capture(client.settings.paypal_binding_capture_id)
    if (
        capture.get("id") != client.settings.paypal_binding_capture_id
        or capture.get("status") != "COMPLETED"
        or capture.get("payee", {}).get("merchant_id")
        != client.settings.paypal_expected_merchant_id
    ):
        raise DomainError("Configured Sandbox receiving-account evidence did not match.")
    binding = PayPalAccountBinding(
        id=uuid.uuid4(),
        client_fingerprint=client.fingerprint,
        merchant_ref=client.settings.paypal_expected_merchant_id,
        capture_ref=client.settings.paypal_binding_capture_id,
    )
    db.add(binding)
    db.commit()
    return binding


def _json(value):
    if isinstance(value, (datetime, uuid.UUID, Decimal)):
        return str(value)
    return str(value)


def fingerprint(db, case, client):
    """All domain inputs, including non-ledger changes; workflow audit is excluded."""
    from app.models import FamilyMembership

    state = {
        "case": {
            k: getattr(case, k)
            for k in (
                "id",
                "currency",
                "patient_alias",
                "payer_user_id",
                "case_reference",
                "status",
                "is_demo",
            )
        },
        "client": client.fingerprint,
        "merchant": client.settings.paypal_expected_merchant_id,
        "provider_email_hash": hashlib.sha256(
            client.settings.paypal_provider_email.encode()
        ).hexdigest(),
        "buyer_email_hash": hashlib.sha256(client.settings.paypal_buyer_email.encode()).hexdigest(),
        "binding_capture": client.settings.paypal_binding_capture_id,
    }
    for model in (
        Bill,
        FamilyMembership,
        BillLineItem,
        ExternalPayment,
        BillingFlag,
        LedgerEntry,
        EvidenceDocument,
        DocumentExtraction,
        ExtractionRevision,
        ProviderLink,
        ProviderResponse,
        ProviderDecision,
    ):
        rows = db.scalars(
            select(model).where(model.case_id == case.id).execution_options(populate_existing=True)
        ).all()
        if model is LedgerEntry:
            rows = [r for r in rows if r.entry_type != LedgerEntryType.PAYPAL_PAYMENT]
        state[model.__tablename__] = sorted(
            [{c.key: getattr(row, c.key) for c in model.__table__.columns} for row in rows],
            key=lambda r: str(r["id"]),
        )
    return hashlib.sha256(
        json.dumps(state, default=_json, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def preview(db, case, client):
    b = svc.get_buckets(db, case)
    from app.insurance import has_insurance, reconcile

    insurance = reconcile(db, case) if has_insurance(db, case.id) else None
    payments = [
        p for p in svc.case_payments(db, case.id) if p.status == ExternalPaymentStatus.MATCHED
    ]
    binding = _binding(db, client)
    return {
        "state_fingerprint": fingerprint(db, case, client),
        "currency": case.currency,
        "invoice_total": (insurance["patient_share"] or "0.00")
        if insurance
        else to_str(b.bill_total - b.queried),
        "external_total": to_str(sum((p.amount for p in payments), ZERO)),
        "collect_amount": (insurance["patient_balance"] or "0.00")
        if insurance and insurance["reviewed"]
        else ("0.00" if insurance else to_str(b.payable_now)),
        "queried": to_str(b.queried),
        "provider_label": case.bills[0].provider_name if case.bills else "Provider not supplied",
        "external_payments": [
            {
                "id": str(p.id),
                "amount": to_str(p.amount),
                "currency": p.currency,
                "paid_on": p.paid_on.isoformat() if p.paid_on else None,
                "reference_suffix": p.reference[-4:] if p.reference else None,
            }
            for p in payments
        ],
        "account_binding": {
            "status": "VERIFIED" if binding else "REQUIRED",
            "basis": BASIS,
            "merchant_ref_suffix": binding.merchant_ref[-4:] if binding else None,
            "client_fingerprint": client.fingerprint if binding else None,
        },
    }


def blockers(db, case, client):
    result = svc.approval_blockers(db, case)
    if case.status == "CLOSED":
        result.append("A closed case cannot approve a new payment.")
    if case.currency != "USD":
        result.append(
            "The confirmed Sandbox flow requires a USD-native case. "
            "Currency conversion is unavailable."
        )
    if len(case.bills) != 1:
        result.append("Sandbox invoicing requires one provider bill per case.")
    if not case.is_demo:
        result.append("Only synthetic demo cases can use this Sandbox workflow.")
    try:
        client.require_config()
    except DomainError as exc:
        result.append(str(exc))
    if not _binding(db, client):
        result.append("Verify the configured Sandbox receiving account before approval.")
    if any(
        p.status == ExternalPaymentStatus.MATCHED and not p.paid_on
        for p in svc.case_payments(db, case.id)
    ):
        result.append("Matched external evidence needs a payment date before invoice recording.")
    return result


def approve(db, actor, case_id, client, *, state_fingerprint, amount, currency, purpose, confirmed):
    case = _lock(db, case_id, actor)
    if _op(db, case_id):
        raise DomainError("A payment attempt already exists; verify it instead.")
    p = preview(db, case, client)
    if not confirmed or state_fingerprint != p["state_fingerprint"]:
        raise DomainError("The case changed. Review the current exact payment before approving.")
    if money(amount) != money(p["collect_amount"]) or currency != case.currency:
        raise ValidationFailed("Approval must match the exact collection amount and currency.")
    purpose = svc._require_note(purpose, "payment purpose")
    reasons = blockers(db, case, client)
    if reasons:
        raise DomainError(" ".join(reasons))
    existing = db.scalar(
        select(ApprovalRecord).where(
            ApprovalRecord.case_id == case_id, ApprovalRecord.state_fingerprint == state_fingerprint
        )
    )
    if existing:
        return existing
    b = svc.get_buckets(db, case)
    binding = _binding(db, client)
    snapshot = dict(p)
    snapshot["external_payments"] = [dict(x) for x in p["external_payments"]]
    approval = ApprovalRecord(
        id=uuid.uuid4(),
        case_id=case_id,
        approved_by=actor.user_id,
        actor_label=actor.label,
        currency=currency,
        approved_amount=money(amount),
        bill_total=b.bill_total,
        payable_now=b.payable_now,
        queried=b.queried,
        already_paid=b.already_paid,
        payee_label=p["provider_label"],
        provider_merchant_ref=binding.merchant_ref,
        ledger_seq=db.scalar(
            select(func.max(LedgerEntry.seq)).where(LedgerEntry.case_id == case_id)
        )
        or 0,
        note=purpose,
        purpose=purpose,
        state_fingerprint=state_fingerprint,
        account_binding={
            "client_fingerprint": binding.client_fingerprint,
            "merchant_ref": binding.merchant_ref,
            "capture_ref": binding.capture_ref,
            "provider_email_hash": hashlib.sha256(
                client.settings.paypal_provider_email.encode()
            ).hexdigest(),
            "buyer_email_hash": hashlib.sha256(
                client.settings.paypal_buyer_email.encode()
            ).hexdigest(),
            "basis": BASIS,
        },
        composition=snapshot,
    )
    db.add(approval)
    svc._audit(
        db,
        actor,
        case_id=case_id,
        event_type="PAYMENT_APPROVED",
        entity_type="approval_record",
        entity_id=approval.id,
        details={"currency": currency, "collect_amount": to_str(money(amount))},
    )
    db.commit()
    return approval


def _approval(db, op):
    a = db.get(ApprovalRecord, op.approval_id)
    if not a or not a.account_binding or not a.composition:
        raise DomainError("A complete immutable payment approval is required.")
    return a


def _account_matches(a, client):
    return (
        a.account_binding["client_fingerprint"] == client.fingerprint
        and a.account_binding["merchant_ref"] == client.settings.paypal_expected_merchant_id
        and a.account_binding["capture_ref"] == client.settings.paypal_binding_capture_id
    )


def _body(op, a, client):
    return {
        "detail": {
            "invoice_number": "CD-" + op.id.hex[:24],
            "reference": str(op.id),
            "currency_code": a.currency,
            "invoice_date": _now().date().isoformat(),
            "payment_term": {"term_type": "DUE_ON_RECEIPT"},
        },
        "invoicer": {"email_address": client.settings.paypal_provider_email},
        "primary_recipients": [
            {"billing_info": {"email_address": client.settings.paypal_buyer_email}}
        ],
        "items": [
            {
                "name": "Synthetic CareDirect approved bill",
                "quantity": "1",
                "unit_amount": {
                    "currency_code": a.currency,
                    "value": a.composition["invoice_total"],
                },
                "unit_of_measure": "AMOUNT",
            }
        ],
        "configuration": {"partial_payment": {"allow_partial_payment": False}, "allow_tip": False},
    }


def _mutate(db, op, client, stage, path, body):
    """Commit reservation BEFORE network. A reserved stage is never automatically retried."""
    case = _lock(db, op.case_id)
    db.refresh(op)
    if stage in op.stages:
        raise DomainError("This network operation was already reserved. Use verification/recovery.")
    if _approval(db, op).state_fingerprint != fingerprint(db, case, client):
        op.state, op.error_code = "RECONCILIATION_REQUIRED", "FAMILY_PERMISSION_CHANGED"
        svc._audit(
            db,
            svc.SYSTEM,
            case_id=case.id,
            event_type="PAYPAL_AUTHORITY_CHANGED",
            entity_type="payment_operation",
            entity_id=op.id,
        )
        db.commit()
        return None
    stages = dict(op.stages)
    request_id = str(uuid.uuid4())
    stages[stage] = {"state": "RESERVED", "request_id": request_id}
    op.stages = stages
    op.stage, op.state = stage, "CREATING"
    svc._audit(
        db,
        svc.SYSTEM,
        case_id=op.case_id,
        event_type="PAYPAL_OPERATION_RESERVED",
        entity_type="payment_operation",
        entity_id=op.id,
        details={"stage": stage, "request_id": request_id},
    )
    db.commit()
    try:
        response = client.request("POST", path, body, request_id)
    except Exception as exc:
        _lock(db, op.case_id)
        db.refresh(op)
        op.state = "UNCERTAIN"
        op.error_code = exc.code if isinstance(exc, PayPalError) else "UNKNOWN_OUTCOME"
        svc._audit(
            db,
            svc.SYSTEM,
            case_id=op.case_id,
            event_type="PAYPAL_OUTCOME_UNCERTAIN",
            entity_type="payment_operation",
            entity_id=op.id,
            details={"stage": stage, "code": op.error_code},
        )
        db.commit()
        return None
    _lock(db, op.case_id)
    db.refresh(op)
    stages = dict(op.stages)
    stages[stage] = {**stages[stage], "state": "CONFIRMED"}
    op.stages = stages
    svc._audit(
        db,
        svc.SYSTEM,
        case_id=op.case_id,
        event_type="PAYPAL_OPERATION_CONFIRMED",
        entity_type="payment_operation",
        entity_id=op.id,
        details={"stage": stage},
    )
    db.commit()
    return response


def start_invoice(db, actor, case_id, client, approval_id):
    case = _lock(db, case_id, actor)
    if _op(db, case_id):
        return
    a = db.get(ApprovalRecord, approval_id)
    if (
        not a
        or a.case_id != case_id
        or not a.composition
        or not a.account_binding
        or a.state_fingerprint != fingerprint(db, case, client)
        or not _account_matches(a, client)
    ):
        raise DomainError(
            "Payment approval is missing or stale. Review and approve the current case."
        )
    if blockers(db, case, client):
        raise DomainError("Payment prerequisites changed. Review blockers before continuing.")
    capture = client.capture(client.settings.paypal_binding_capture_id)
    if (
        capture.get("id") != client.settings.paypal_binding_capture_id
        or capture.get("status") != "COMPLETED"
        or capture.get("payee", {}).get("merchant_id") != a.provider_merchant_ref
    ):
        raise DomainError("Sandbox receiving-account verification failed.")
    # Recheck after the remote read while holding the case lock.
    if a.state_fingerprint != fingerprint(db, case, client):
        raise DomainError("The case changed during account verification.")
    op = PaymentOperation(
        id=uuid.uuid4(),
        case_id=case_id,
        approval_id=a.id,
        state="CREATING",
        stage="CREATE",
        stages={},
    )
    db.add(op)
    db.commit()  # freezes all financially relevant domain mutation before any POST
    created = _mutate(db, op, client, "CREATE", "/v2/invoicing/invoices", _body(op, a, client))
    if created is None:
        return
    invoice_id = created.get("id")
    if not invoice_id:
        for link in created.get("links", []):
            if link.get("rel") == "self":
                invoice_id = link.get("href", "").rsplit("/", 1)[-1]
    try:
        op.paypal_invoice_id = resource_id(invoice_id)
        db.commit()
        inv = client.invoice(op.paypal_invoice_id)
        validate_invoice(inv, op, a)
    except Exception:
        op.state, op.error_code = "UNCERTAIN", "CREATE_NEEDS_RECOVERY"
        db.commit()
        return
    if (
        _mutate(
            db,
            op,
            client,
            "SEND",
            f"/v2/invoicing/invoices/{op.paypal_invoice_id}/send",
            {"send_to_invoicer": False, "send_to_recipient": False},
        )
        is None
    ):
        return
    for p in a.composition["external_payments"]:
        if (
            _mutate(
                db,
                op,
                client,
                "EXTERNAL:" + p["id"],
                f"/v2/invoicing/invoices/{op.paypal_invoice_id}/payments",
                {
                    "method": "OTHER",
                    "payment_date": p["paid_on"],
                    "amount": {"currency_code": a.currency, "value": p["amount"]},
                    "note": "CareDirect evidence " + p["id"],
                },
            )
            is None
        ):
            return
    verify(db, actor, case_id, client)


def _amount(obj, expected_currency):
    if not isinstance(obj, dict) or obj.get("currency_code") != expected_currency:
        raise DomainError("PayPal currency does not match approval.")
    return money(obj.get("value"))


def validate_invoice(inv, op, a):
    provider = inv.get("invoicer", {}).get("email_address", "")
    recipients = inv.get("primary_recipients", [])
    buyer = (
        recipients[0].get("billing_info", {}).get("email_address", "")
        if len(recipients) == 1
        else ""
    )
    if (
        hashlib.sha256(provider.encode()).hexdigest() != a.account_binding["provider_email_hash"]
        or hashlib.sha256(buyer.encode()).hexdigest() != a.account_binding["buyer_email_hash"]
    ):
        raise DomainError("PayPal invoice parties differ from the approved composition.")
    if (
        inv.get("id") != op.paypal_invoice_id
        or inv.get("detail", {}).get("reference") != str(op.id)
        or inv.get("detail", {}).get("invoice_number") != "CD-" + op.id.hex[:24]
        or inv.get("detail", {}).get("currency_code") != a.currency
        or _amount(inv.get("amount"), a.currency) != money(a.composition["invoice_total"])
    ):
        raise DomainError("PayPal invoice composition/reference differs from approved operation.")
    items = inv.get("items", [])
    if (
        len(items) != 1
        or money(items[0].get("quantity")) != Decimal("1")
        or items[0].get("name") != "Synthetic CareDirect approved bill"
        or _amount(items[0].get("unit_amount"), a.currency) != money(a.composition["invoice_total"])
    ):
        raise DomainError("PayPal invoice line composition differs from approval.")
    if (
        inv.get("configuration", {}).get("partial_payment", {}).get("allow_partial_payment")
        is not False
        or inv.get("configuration", {}).get("allow_tip") is not False
    ):
        raise DomainError("PayPal partial-payment configuration differs from approved flow.")


def _apply_verified(db, op, a, inv, client):
    validate_invoice(inv, op, a)
    persisted = db.scalar(select(PayPalInvoiceRef).where(PayPalInvoiceRef.approval_id == a.id))
    if (
        persisted
        and persisted.invoice_status == PayPalInvoiceStatus.PAID
        and inv.get("status")
        not in ("PAID", "REFUNDED", "PARTIALLY_REFUNDED", "MARKED_AS_REFUNDED")
        and not inv.get("refunds", {}).get("transactions", [])
    ):
        raise PayPalError("STALE_RESOURCE")
    txns = inv.get("payments", {}).get("transactions", [])
    externals = [t for t in txns if t.get("type") == "EXTERNAL"]
    expected = a.composition["external_payments"]
    if len(externals) != len(expected):
        if persisted and persisted.invoice_status == PayPalInvoiceStatus.PAID:
            raise PayPalError("STALE_RESOURCE")
        raise DomainError("External invoice payments need reconciliation with approved evidence.")
    unmatched = list(externals)
    linked = []
    for p in expected:
        # The deterministic note binds same-value payments to their exact immutable evidence.
        matches = [
            t
            for t in unmatched
            if t.get("note") == "CareDirect evidence " + p["id"]
            and t.get("method") == "OTHER"
            and t.get("payment_date") == p["paid_on"]
            and _amount(t.get("amount"), a.currency) == money(p["amount"])
        ]
        if len(matches) != 1:
            raise DomainError(
                "External invoice payment does not match its approved evidence reference."
            )
        t = matches[0]
        unmatched.remove(t)
        linked.append((t, p))
    refunds = inv.get("refunds", {}).get("transactions", [])
    if refunds or inv.get("status") in ("REFUNDED", "PARTIALLY_REFUNDED", "MARKED_AS_REFUNDED"):
        raise PaymentReconciliationError(
            "REFUND_OBSERVED", "Refund observed; financial reconciliation is required."
        )
    known_captures = set(
        db.scalars(
            select(PayPalPaymentRef.paypal_transaction_id).where(
                PayPalPaymentRef.case_id == op.case_id,
                PayPalPaymentRef.payment_source == PayPalPaymentSource.PAYPAL,
            )
        ).all()
    )
    if not known_captures.issubset(
        {t.get("payment_id") for t in txns if t.get("type") == "PAYPAL"}
    ):
        raise PayPalError("STALE_RESOURCE")
    verified = []
    for t in txns:
        if t.get("type") == "PAYPAL":
            capture_id = resource_id(t.get("payment_id"))
            capture = client.capture(capture_id)
            if (
                capture.get("id") != capture_id
                or capture.get("payee", {}).get("merchant_id") != a.provider_merchant_ref
                or _amount(capture.get("amount"), a.currency)
                != _amount(t.get("amount"), a.currency)
            ):
                raise DomainError(
                    "PayPal capture amount/currency/receiving account differs from invoice."
                )
            if capture.get("status") != "COMPLETED":
                if capture.get("status") in (
                    "REFUNDED",
                    "PARTIALLY_REFUNDED",
                    "DECLINED",
                    "FAILED",
                ):
                    raise PaymentReconciliationError(
                        "CAPTURE_REVERSED", "Capture requires financial reconciliation."
                    )
                if persisted and persisted.invoice_status == PayPalInvoiceStatus.PAID:
                    raise PayPalError("STALE_CAPTURE")
                op.state = "VERIFICATION_PENDING"
                return
            verified.append((t, capture))
        elif t.get("type") != "EXTERNAL":
            raise DomainError("Unrecognized PayPal invoice transaction.")
    paid_paypal = sum((_amount(t[0]["amount"], a.currency) for t in verified), ZERO)
    if paid_paypal > a.approved_amount:
        raise DomainError("PayPal collected above the approved amount.")
    external_total = sum((money(p["amount"]) for p in expected), ZERO)
    due = _amount(inv.get("due_amount"), a.currency)
    if due != money(a.composition["invoice_total"]) - external_total - paid_paypal:
        raise DomainError("PayPal amount due does not reconcile with invoice transactions.")
    if inv.get("status") == "PAID" and (due != ZERO or paid_paypal != a.approved_amount):
        raise DomainError("Paid invoice lacks the exact completed approved collection.")
    ref = db.scalar(select(PayPalInvoiceRef).where(PayPalInvoiceRef.approval_id == a.id))
    if not ref:
        ref = PayPalInvoiceRef(
            id=uuid.uuid4(),
            case_id=op.case_id,
            approval_id=a.id,
            paypal_invoice_id=op.paypal_invoice_id,
            merchant_account_ref=a.provider_merchant_ref,
            currency=a.currency,
            invoice_total=money(a.composition["invoice_total"]),
            amount_due=due,
            invoice_status=PayPalInvoiceStatus(inv["status"]),
            last_verified_at=_now(),
        )
        db.add(ref)
        db.flush()
    else:
        ref.amount_due, ref.invoice_status, ref.last_verified_at = (
            due,
            PayPalInvoiceStatus(inv["status"]),
            _now(),
        )
    for t, p in linked:
        _payment_ref(db, ref, t, a, p)
    for t, _capture in verified:
        payment = _payment_ref(db, ref, t, a, None)
        exists = db.scalar(
            select(LedgerEntry.id).where(LedgerEntry.paypal_payment_ref_id == payment.id)
        )
        if not exists:
            entry = LedgerEntry(
                id=uuid.uuid4(),
                case_id=op.case_id,
                entry_type=LedgerEntryType.PAYPAL_PAYMENT,
                amount=payment.amount,
                currency=a.currency,
                paypal_payment_ref_id=payment.id,
                reason="Authoritative completed PayPal capture verified",
                actor_label="system:paypal",
            )
            db.add(entry)
            db.flush()
            svc._audit(
                db,
                svc.SYSTEM,
                case_id=op.case_id,
                event_type="PAYPAL_CAPTURE_CREDITED",
                entity_type="paypal_payment_ref",
                entity_id=payment.id,
                ledger_entry=entry,
                details={
                    "amount": to_str(payment.amount),
                    "currency": a.currency,
                    "reference_suffix": payment.paypal_transaction_id[-4:],
                },
            )
    op.state = (
        "PAID"
        if inv["status"] == "PAID"
        else "CANCELLED"
        if inv["status"] == "CANCELLED"
        else "VERIFICATION_PENDING"
        if inv["status"] == "PAYMENT_PENDING"
        else "AWAITING_BUYER"
    )
    op.error_code = None
    op.stage = "VERIFIED"
    db.flush()


def _payment_ref(db, ref, t, a, external):
    txn = resource_id(t.get("payment_id"))
    existing = db.scalar(
        select(PayPalPaymentRef).where(
            PayPalPaymentRef.invoice_ref_id == ref.id, PayPalPaymentRef.paypal_transaction_id == txn
        )
    )
    if existing:
        if (
            existing.amount != _amount(t["amount"], a.currency)
            or existing.currency != a.currency
            or existing.payment_source
            != (PayPalPaymentSource.EXTERNAL if external else PayPalPaymentSource.PAYPAL)
            or existing.external_payment_id != (uuid.UUID(external["id"]) if external else None)
        ):
            raise DomainError("Previously verified payment changed.")
        return existing
    if not external and db.scalar(
        select(PayPalPaymentRef.id).where(
            PayPalPaymentRef.paypal_transaction_id == txn,
            PayPalPaymentRef.payment_source == "PAYPAL",
        )
    ):
        raise DomainError("This PayPal capture is already linked to another invoice.")
    payment = PayPalPaymentRef(
        id=uuid.uuid4(),
        case_id=ref.case_id,
        invoice_ref_id=ref.id,
        paypal_transaction_id=txn,
        payment_source=PayPalPaymentSource.EXTERNAL if external else PayPalPaymentSource.PAYPAL,
        external_payment_id=uuid.UUID(external["id"]) if external else None,
        amount=_amount(t["amount"], a.currency),
        currency=a.currency,
        paypal_status="RECORDED" if external else "COMPLETED",
        verified_at=_now(),
    )
    db.add(payment)
    db.flush()
    return payment


def verify(db, actor, case_id, client, invoice_id=None):
    _lock(db, case_id, actor)
    op = _op(db, case_id)
    if not op:
        raise DomainError("No payment attempt exists to verify.")
    a = _approval(db, op)
    if not _account_matches(a, client):
        raise DomainError(
            "Configured Sandbox account changed. Restore the approved binding before verification."
        )
    if invoice_id:
        invoice_id = resource_id(invoice_id)
        if op.paypal_invoice_id and invoice_id != op.paypal_invoice_id:
            raise DomainError("Cannot replace an existing invoice reference.")
    else:
        invoice_id = op.paypal_invoice_id
    if not invoice_id:
        op.state = "UNCERTAIN"
        db.commit()
        raise DomainError(
            "Invoice creation outcome is unknown. "
            "Supply its PayPal invoice reference for read-only recovery."
        )
    original_id = op.paypal_invoice_id
    manual_code = op.error_code if op.error_code in MANUAL_RECONCILIATION_CODES else None
    try:
        inv = client.invoice(invoice_id)
        op.paypal_invoice_id = invoice_id
        validate_invoice(inv, op, a)
        if op.error_code in MANUAL_RECONCILIATION_CODES:
            # An observed reversal is durable evidence. A later lagging PAID read
            # must not silently clear it; no automatic ledger reversal is allowed.
            db.commit()
            return
        prior_ref = db.scalar(select(PayPalInvoiceRef).where(PayPalInvoiceRef.case_id == case_id))
        # Identity/composition recovery is separate from settlement. A correct draft is
        # retained even before external records exist; recovery never repeats a POST.
        if not prior_ref and (
            inv.get("status") == "DRAFT"
            or len(
                [
                    t
                    for t in inv.get("payments", {}).get("transactions", [])
                    if t.get("type") == "EXTERNAL"
                ]
            )
            < len(a.composition["external_payments"])
        ):
            op.state, op.stage, op.error_code = (
                "UNCERTAIN",
                "RECOVERY_INCOMPLETE",
                "MANUAL_RECONCILIATION_REQUIRED",
            )
            db.commit()
            return
        _apply_verified(db, op, a, inv, client)
    except Exception as exc:
        db.rollback()
        _lock(db, case_id, actor)
        op = _op(db, case_id)
        # Only a completely validated recovered invoice is persisted.
        op.paypal_invoice_id = original_id
        if manual_code:
            op.state, op.error_code = "RECONCILIATION_REQUIRED", manual_code
            db.commit()
            return
        verified_ref = db.scalar(
            select(PayPalInvoiceRef).where(PayPalInvoiceRef.case_id == case_id)
        )
        op.state = (
            "PAID"
            if isinstance(exc, PayPalError)
            and verified_ref
            and verified_ref.invoice_status == PayPalInvoiceStatus.PAID
            else "UNCERTAIN"
            if isinstance(exc, PayPalError)
            else "RECONCILIATION_REQUIRED"
        )
        op.error_code = (
            exc.code
            if isinstance(exc, (PayPalError, PaymentReconciliationError))
            else "RESOURCE_MISMATCH"
        )
    db.commit()


def workspace(db, actor, case_id, client):
    case = svc.get_case(db, case_id)
    svc._require_case_member(case, actor)
    from app.family import access

    permissions = access(case, actor)
    p = preview(db, case, client)
    op = _op(db, case_id)
    a = (
        _approval(db, op)
        if op
        else db.scalar(
            select(ApprovalRecord)
            .where(ApprovalRecord.case_id == case_id, ApprovalRecord.state_fingerprint.is_not(None))
            .order_by(ApprovalRecord.created_at.desc())
        )
    )
    reasons = blockers(db, case, client) if not op else []
    state = (
        op.state
        if op
        else "BLOCKED"
        if reasons
        else "APPROVED"
        if a and a.state_fingerprint == p["state_fingerprint"]
        else "APPROVAL_REQUIRED"
    )
    # A worker may have died at any point after reserving a stage. Never resume POST.
    if op and op.state == "CREATING":
        state = "UNCERTAIN"
    invoice = None
    ref = db.scalar(select(PayPalInvoiceRef).where(PayPalInvoiceRef.case_id == case_id))
    if ref:
        invoice = {
            "id": str(ref.id),
            "paypal_invoice_id": ref.paypal_invoice_id,
            "status": ref.invoice_status,
            "invoice_total": to_str(ref.invoice_total),
            "amount_due": to_str(ref.amount_due),
            "currency": ref.currency,
            "last_verified_at": ref.last_verified_at,
            "checkout_url": None,
        }
        # Checkout metadata is never stored in audit/export.
        if state == "AWAITING_BUYER" and permissions["can_approve"]:
            # The metadata URL is obtained by GET, not constructed from untrusted request input.
            try:
                inv = client.invoice(ref.paypal_invoice_id)
                validate_invoice(inv, op, a)
                invoice["checkout_url"] = safe_checkout_url(
                    inv.get("detail", {}).get("metadata", {}).get("recipient_view_url")
                )
            except DomainError:
                invoice["checkout_url"] = None
    transactions = db.scalars(
        select(PayPalPaymentRef).where(PayPalPaymentRef.case_id == case_id)
    ).all()
    return {
        "can_approve": permissions["can_approve"],
        "state": state,
        "blockers": reasons,
        "preview": p,
        "approval": {
            "id": str(a.id),
            "approved_amount": to_str(a.approved_amount),
            "currency": a.currency,
            "purpose": a.purpose,
            "approved_by": a.actor_label,
            "snapshot": a.composition,
            "approved_at": a.created_at,
            "state_fingerprint": a.state_fingerprint,
            "current": a.state_fingerprint == p["state_fingerprint"],
        }
        if a
        else None,
        "operation": {
            "id": str(op.id),
            "state": state,
            "stage": op.stage,
            "error_code": op.error_code,
        }
        if op
        else None,
        "invoice": invoice,
        "transactions": [
            {
                "id": str(t.id),
                "source": t.payment_source,
                "amount": to_str(t.amount),
                "currency": t.currency,
                "status": t.paypal_status,
                "verified_at": t.verified_at,
                "reference_suffix": t.paypal_transaction_id[-4:],
            }
            for t in transactions
        ],
    }
