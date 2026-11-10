"""Prompt8 API/privacy/webhook regressions. Lead owns database execution."""

import copy
import json
import uuid
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select

from app import evidence, payments, webhooks
from app import services as svc
from app.config import Settings
from app.errors import DomainError
from app.models import PayPalWebhookEvent
from app.paypal_client import PayPalClient, PayPalError, get_paypal_client
from tests.test_payments import FakePayPal, approved


def event(identifier="WH-SYNTHETIC", invoice="INV2-SYNTHETIC", kind="PAID"):
    return {
        "id": identifier,
        "event_type": "INVOICING.INVOICE." + kind,
        "resource": {"id": invoice, "status": "PAID", "amount": {"value": "99999"}},
    }


class WebhookFake(FakePayPal):
    def __init__(self):
        super().__init__()
        self.unique_suffix = uuid.uuid4().hex[:12]
        self.invoice_id = "INV2-" + self.unique_suffix
        self.valid = True
        self.outage = False
        self.verifications = 0
        self.gets = 0

    def event(self, identifier="WH-SYNTHETIC", invoice=None, kind="PAID"):
        return event(identifier, invoice or self.invoice_id, kind)

    def verify_webhook(self, headers, raw_body):
        self.verifications += 1
        if self.outage:
            raise PayPalError("VERIFICATION_UNAVAILABLE")
        return self.valid

    def invoice(self, invoice_id):
        self.gets += 1
        if self.outage:
            raise PayPalError("REFETCH_UNAVAILABLE")
        result = super().invoice(invoice_id)
        for transaction in result["payments"]["transactions"]:
            if transaction["type"] == "PAYPAL":
                transaction["payment_id"] = "CAP-" + self.unique_suffix
        return result


def started(db, actor):
    fake = WebhookFake()
    case, _, approval = approved(db, actor, fake)
    payments.start_invoice(db, actor, case.id, fake, approval.id)
    return case, fake


def test_dashboard_is_personal_and_totals_keep_currency(db, actor, client, headers, other_payer):
    case, fake = started(db, actor)
    svc.create_case(db, actor, patient_alias="Separate INR", currency="INR", is_demo=True)
    svc.create_case(
        db, svc.Actor(user=other_payer, label="Other"), patient_alias="Invisible", currency="USD"
    )
    response = client.get("/api/dashboard", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data["cases"]) == 2
    assert {t["currency"] for t in data["totals"]} == {"USD", "INR"}
    assert next(t for t in data["totals"] if t["currency"] == "USD")["payable_now"] == "190.00"
    assert (
        next(c for c in data["cases"] if c["id"] == str(case.id))["payment_state"]
        == "AWAITING_BUYER"
    )
    assert response.headers["cache-control"] == "no-store"
    assert client.get("/api/dashboard").status_code == 403


def test_evidence_allowlist_exact_history_and_private_headers(
    db, actor, client, headers, other_payer
):
    case, fake = started(db, actor)
    fake.completed = True
    payments.verify(db, actor, case.id, fake)
    response = client.get(f"/api/cases/{case.id}/evidence", headers=headers)
    assert response.status_code == 200
    data, serialized = response.json(), response.text
    assert data["approvals"][0]["approved_amount"] == "190.00"
    assert data["approvals"][0]["composition"]["invoice_total"] == "230.00"
    assert data["buckets"]["already_paid"] == "230.00"
    for forbidden in (
        "storage_key",
        "token_sha256",
        "checkout_url",
        "synthetic-secret",
        "provider@example.invalid",
        "client_fingerprint",
    ):
        assert forbidden not in serialized
    assert "attachment" in response.headers["content-disposition"]
    assert response.headers["cache-control"] == "no-store"
    assert "sandbox" in response.headers["content-security-policy"]
    assert (
        client.get(
            f"/api/cases/{case.id}/evidence", headers={"X-Demo-User-Id": str(other_payer.id)}
        ).status_code
        == 403
    )
    html_response = client.get(f"/api/cases/{case.id}/evidence?format=html", headers=headers)
    assert html_response.status_code == 200
    assert "CareDirect private evidence" in html_response.text
    assert (
        client.get(f"/api/cases/{case.id}/evidence?format=pdf", headers=headers).status_code == 422
    )


def test_export_escapes_active_markup_and_removes_private_links():
    data = evidence.safe(
        {
            "reason": "<script>alert(1)</script> https://private.invalid/uploads/secret",
            "token": "a" * 43,
        }
    )
    rendered = evidence.as_html(data)
    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered
    assert "https://private.invalid" not in rendered
    assert "a" * 43 not in rendered
    assert "/api/documents/private/content" not in evidence.safe(
        "/api/documents/private/content /cases/case/documents/doc/source"
    )


def test_verified_duplicate_event_refetches_once_and_credits_once(db, actor):
    case, fake = started(db, actor)
    fake.completed = True
    initial = fake.gets
    assert webhooks.process(db, fake.event(), fake) == ("processed", False)
    assert webhooks.process(db, fake.event(), fake) == ("duplicate", False)
    assert fake.gets == initial + 1
    assert svc.get_buckets(db, case).already_paid == Decimal("230.00")
    assert len([r for r in svc.case_ledger(db, case.id) if r.entry_type == "PAYPAL_PAYMENT"]) == 1
    assert len(fake.posts) == 3


def test_refetch_outage_remains_durably_retryable(db, actor):
    case, fake = started(db, actor)
    fake.outage = True
    assert webhooks.process(db, fake.event(), fake) == ("retry", True)
    receipt = db.scalar(select(PayPalWebhookEvent))
    assert receipt.outcome == "RETRY" and receipt.attempts == 1
    fake.outage, fake.completed = False, True
    assert webhooks.process(db, fake.event(), fake) == ("processed", False)
    assert receipt.attempts == 2
    assert svc.get_buckets(db, case).already_paid == Decimal("230.00")


@pytest.mark.parametrize(
    "status,remove_external", [("SENT", False), ("DRAFT", False), ("PAID", True)]
)
def test_delayed_event_cannot_regress_confirmed_paid(db, actor, status, remove_external):
    case, fake = started(db, actor)
    fake.completed = True
    assert webhooks.process(db, fake.event(), fake) == ("processed", False)
    fake.completed = False
    fake.inv["status"] = status
    if remove_external:
        fake.inv["payments"]["transactions"] = []
    assert webhooks.process(db, fake.event("WH-DELAYED", kind="SENT"), fake)[1] is True
    assert payments._op(db, case.id).state == "PAID"
    assert svc.get_buckets(db, case).already_paid == Decimal("230.00")
    assert len(fake.posts) == 3


def test_signed_paid_payload_alone_never_credits(db, actor):
    case, fake = started(db, actor)
    assert webhooks.process(db, fake.event(), fake) == ("processed", False)
    assert payments._op(db, case.id).state == "AWAITING_BUYER"
    assert svc.get_buckets(db, case).already_paid == Decimal("40.00")


def test_unknown_invoice_retry_and_unsupported_event_ignored(db, actor):
    _, fake = started(db, actor)
    assert webhooks.process(db, fake.event(invoice="INV2-UNKNOWN"), fake) == ("retry", True)
    assert webhooks.process(db, fake.event("WH-OTHER", kind="NOT_SUPPORTED"), fake) == (
        "ignored",
        False,
    )


def test_conflicting_duplicate_rejected(db, actor):
    _, fake = started(db, actor)
    original = fake.event()
    webhooks.process(db, original, fake)
    changed = copy.deepcopy(original)
    changed["resource"]["status"] = "CANCELLED"
    with pytest.raises(DomainError):
        webhooks.process(db, changed, fake)


def test_api_signature_required_before_persistence(client, db, actor):
    from app.main import app

    fake = WebhookFake()
    app.dependency_overrides[get_paypal_client] = lambda: fake
    fake.valid = False
    assert client.post("/api/paypal/webhooks", json=fake.event()).status_code == 400
    assert db.scalar(select(PayPalWebhookEvent.id)) is None
    fake.outage = True
    assert client.post("/api/paypal/webhooks", json=fake.event()).status_code == 503
    assert db.scalar(select(PayPalWebhookEvent.id)) is None
    assert (
        client.post("/api/paypal/webhooks", content=b'{"id":"one","id":"two"}').status_code == 400
    )
    assert client.post("/api/paypal/webhooks", content=b"x" * (256 * 1024 + 1)).status_code == 413


def test_postback_preserves_raw_event_and_requires_success():
    raw = b'{ "id" : "WH-SYNTHETIC", "event_type": "INVOICING.INVOICE.PAID" }'
    observed = []

    def transport(request):
        if request.url.path.endswith("/token"):
            return httpx.Response(
                200, json={"token_type": "Bearer", "access_token": "synthetic", "expires_in": 3600}
            )
        observed.append(request)
        return httpx.Response(200, json={"verification_status": "SUCCESS"})

    settings = Settings(
        _env_file=None,
        **{**FakePayPal().settings.model_dump(), "paypal_webhook_id": "WH-CONFIGURED"},
    )
    client = PayPalClient(settings, httpx.MockTransport(transport))
    headers = {
        "paypal-" + k: "synthetic"
        for k in (
            "auth-algo",
            "cert-url",
            "transmission-id",
            "transmission-sig",
            "transmission-time",
        )
    }
    assert client.verify_webhook(headers, raw) is True
    assert b'"webhook_event":' + raw in observed[0].content
    payload = json.loads(observed[0].content)
    assert payload["webhook_id"] == "WH-CONFIGURED"
    assert payload["webhook_event"]["id"] == "WH-SYNTHETIC"
    assert client.verify_webhook({}, raw) is False


@pytest.mark.parametrize(
    "payload,status,expected",
    [
        ({"verification_status": "FAILURE"}, 200, False),
        ({"verification_status": "success"}, 200, False),
        ({"verification_status": "SUCCESS"}, 503, None),
        ([], 200, None),
    ],
)
def test_postback_failure_and_malformed_are_never_success(payload, status, expected):
    from tests.test_prompt7_acceptance import sandbox_settings

    def transport(request):
        if request.url.path.endswith("/token"):
            return httpx.Response(
                200, json={"token_type": "Bearer", "access_token": "synthetic", "expires_in": 3600}
            )
        return httpx.Response(status, json=payload)

    client = PayPalClient(
        sandbox_settings(paypal_webhook_id="WH-CONFIGURED"), httpx.MockTransport(transport)
    )
    headers = {
        "paypal-" + k: "synthetic"
        for k in (
            "auth-algo",
            "cert-url",
            "transmission-id",
            "transmission-sig",
            "transmission-time",
        )
    }
    if expected is None:
        with pytest.raises(PayPalError):
            client.verify_webhook(headers, b"{}")
    else:
        assert client.verify_webhook(headers, b"{}") is expected


def test_postback_oauth_outage_never_attempts_verification():
    from tests.test_prompt7_acceptance import sandbox_settings

    calls = []

    def transport(request):
        calls.append(request.url.path)
        return httpx.Response(503)

    client = PayPalClient(
        sandbox_settings(paypal_webhook_id="WH-CONFIGURED"), httpx.MockTransport(transport)
    )
    headers = {
        "paypal-" + k: "synthetic"
        for k in (
            "auth-algo",
            "cert-url",
            "transmission-id",
            "transmission-sig",
            "transmission-time",
        )
    }
    with pytest.raises(PayPalError):
        client.verify_webhook(headers, b"{}")
    assert calls == ["/v1/oauth2/token"]


def test_crashed_processing_lease_can_be_reclaimed(db, actor, monkeypatch):
    from datetime import UTC, datetime, timedelta

    case, fake = started(db, actor)

    class ProcessExit(BaseException):
        pass

    original = payments.verify

    def crash(*args):
        raise ProcessExit()

    monkeypatch.setattr(payments, "verify", crash)
    with pytest.raises(ProcessExit):
        webhooks.process(db, fake.event(), fake)
    db.rollback()
    receipt = db.scalar(select(PayPalWebhookEvent))
    assert receipt.outcome == "PROCESSING"
    assert webhooks.process(db, fake.event(), fake) == ("processing", True)
    receipt.updated_at = datetime.now(UTC) - timedelta(seconds=121)
    db.commit()
    monkeypatch.setattr(payments, "verify", original)
    fake.completed = True
    assert webhooks.process(db, fake.event(), fake) == ("processed", False)
    assert receipt.attempts == 2
    assert svc.get_buckets(db, case).already_paid == Decimal("230.00")


def test_overlapping_receiver_observes_durable_reservation(engine):
    """A second receiver overlaps the first's network wait in another real session."""
    import uuid

    from sqlalchemy.orm import Session

    from app.states import UserRole

    suffix = uuid.uuid4().hex[:12]
    notification = event("WH-OVERLAP-" + suffix, "INV2-" + suffix)

    class Observed(WebhookFake):
        observe = False

        def invoice(self, invoice_id):
            if self.observe:
                with Session(engine) as other:
                    recorded = other.scalar(
                        select(PayPalWebhookEvent).where(
                            PayPalWebhookEvent.event_id == notification["id"]
                        )
                    )
                    assert recorded.outcome == "PROCESSING" and recorded.attempts == 1
                    assert webhooks.process(other, notification, self) == ("processing", True)
            result = super().invoice(invoice_id)
            for transaction in result["payments"]["transactions"]:
                if transaction["type"] == "PAYPAL":
                    transaction["payment_id"] = "CAP-" + suffix
            return result

    with Session(engine, expire_on_commit=False) as durable:
        payer = svc.create_user(
            durable, "Synthetic overlapping webhook", UserRole.PAYER, is_demo=True
        )
        durable.commit()
        actor = svc.Actor(user=payer, label="Synthetic overlapping webhook")
        fake = Observed()
        fake.invoice_id = notification["resource"]["id"]
        case, _, approval = approved(durable, actor, fake)
        payments.start_invoice(durable, actor, case.id, fake, approval.id)
        fake.observe, fake.completed = True, True
        assert webhooks.process(durable, notification, fake) == ("processed", False)
        assert webhooks.process(durable, notification, fake) == ("duplicate", False)
        assert (
            len([r for r in svc.case_ledger(durable, case.id) if r.entry_type == "PAYPAL_PAYMENT"])
            == 1
        )
        assert len(fake.posts) == 3


def test_dashboard_counts_held_question_without_provider_link(db, actor):
    from tests.test_payments import payment_case

    case, bill = payment_case(db, actor)
    svc.query_line(db, actor, bill.line_items[0].id, "Please clarify this charge")
    data = evidence.dashboard(db, actor)
    item = next(row for row in data["cases"] if row["id"] == str(case.id))
    assert item["open_questions"] == 1
    assert item["active_provider_links"] == 0


@pytest.mark.parametrize("capture_status", ["REFUNDED", "PARTIALLY_REFUNDED", "DECLINED", "FAILED"])
def test_terminal_capture_does_not_wait_or_credit(db, actor, capture_status):
    case, fake = started(db, actor)
    fake.completed, fake.capture_status = True, capture_status
    assert webhooks.process(db, fake.event(), fake) == ("review_required", False)
    assert payments._op(db, case.id).state == "RECONCILIATION_REQUIRED"
    assert svc.get_buckets(db, case).already_paid == Decimal("40.00")
    fake.capture_status = "COMPLETED"
    assert webhooks.process(db, fake.event("WH-LAGGING-PAID"), fake) == ("review_required", False)
    assert payments._op(db, case.id).state == "RECONCILIATION_REQUIRED"
    assert svc.get_buckets(db, case).already_paid == Decimal("40.00")


def test_refund_then_get_outage_and_stale_paid_preserves_manual_review(db, actor):
    case, fake = started(db, actor)
    fake.completed = True
    assert webhooks.process(db, fake.event(), fake) == ("processed", False)
    fake.inv["refunds"] = {"transactions": [{"id": "SYNTHETIC-REFUND"}]}
    assert webhooks.process(db, fake.event("WH-REFUND", kind="REFUNDED"), fake) == (
        "review_required",
        False,
    )
    assert payments._op(db, case.id).error_code == "REFUND_OBSERVED"
    fake.outage = True
    assert webhooks.process(db, fake.event("WH-AFTER-REFUND-OUTAGE"), fake) == (
        "review_required",
        False,
    )
    assert payments._op(db, case.id).state == "RECONCILIATION_REQUIRED"
    assert payments._op(db, case.id).error_code == "REFUND_OBSERVED"
    fake.outage = False
    fake.inv["refunds"] = {"transactions": []}
    assert webhooks.process(db, fake.event("WH-AFTER-REFUND-STALE-PAID"), fake) == (
        "review_required",
        False,
    )
    assert payments._op(db, case.id).state == "RECONCILIATION_REQUIRED"
    assert payments._op(db, case.id).error_code == "REFUND_OBSERVED"
    assert len([r for r in svc.case_ledger(db, case.id) if r.entry_type == "PAYPAL_PAYMENT"]) == 1
