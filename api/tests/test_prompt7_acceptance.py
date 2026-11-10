"""Independent Prompt7 acceptance. Synthetic credentials; network fully replaced."""

import httpx
import pytest

from app.config import Settings
from app.errors import DomainError
from app.paypal_client import PayPalClient, PayPalError


def test_reservations_visible_to_independent_session_before_each_post(engine):
    """Uses real commits, unlike the usual outer-transaction test fixture."""
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from app import payments
    from app import services as svc
    from app.models import PaymentOperation, User
    from app.states import UserRole
    from tests.test_payments import FakePayPal, approved

    class ObservedPayPal(FakePayPal):
        def request(self, method, path, body=None, request_id=None):
            with Session(engine) as observer:
                operation = observer.scalar(
                    select(PaymentOperation).where(PaymentOperation.case_id == self.case_id)
                )
                assert operation is not None
                assert operation.stages[operation.stage]["state"] == "RESERVED"
                assert operation.stages[operation.stage]["request_id"] == request_id
                other_actor = svc.Actor(
                    user=observer.get(User, self.user_id), label="Independent duplicate caller"
                )
                # An overlapping second session must see the durable operation and
                # return without entering a second mutating network request.
                payments.start_invoice(
                    observer, other_actor, self.case_id, self, operation.approval_id
                )
            return super().request(method, path, body, request_id)

    with Session(engine, expire_on_commit=False) as durable:
        payer = svc.create_user(
            durable, "Synthetic durable acceptance", UserRole.PAYER, is_demo=True
        )
        durable.commit()
        actor = svc.Actor(user=payer, label="Synthetic durable acceptance")
        fake = ObservedPayPal()
        case, _bill, approval = approved(durable, actor, fake)
        fake.case_id, fake.user_id = case.id, payer.id
        payments.start_invoice(durable, actor, case.id, fake, approval.id)
        assert len(fake.posts) == 3


def test_process_crash_reservation_remains_uncertain_without_repost(engine):
    from sqlalchemy.orm import Session

    from app import payments
    from app import services as svc
    from app.models import User
    from app.states import UserRole
    from tests.test_payments import FakePayPal, approved

    class ProcessExit(BaseException):
        pass

    class CrashingPayPal(FakePayPal):
        def request(self, *args, **kwargs):
            raise ProcessExit("Synthetic process exit after reservation")

    with Session(engine, expire_on_commit=False) as durable:
        payer = svc.create_user(durable, "Synthetic crash acceptance", UserRole.PAYER, is_demo=True)
        durable.commit()
        actor = svc.Actor(user=payer, label="Synthetic crash acceptance")
        fake = CrashingPayPal()
        case, _bill, approval = approved(durable, actor, fake)
        case_id, payer_id, approval_id = case.id, payer.id, approval.id
        with pytest.raises(ProcessExit):
            payments.start_invoice(durable, actor, case_id, fake, approval_id)
    with Session(engine) as restarted:
        actor = svc.Actor(user=restarted.get(User, payer_id), label="Synthetic restarted worker")
        assert payments.workspace(restarted, actor, case_id, fake)["state"] == "UNCERTAIN"
        payments.start_invoice(restarted, actor, case_id, fake, approval_id)
        assert fake.posts == []


def sandbox_settings(**overrides):
    values = dict(
        paypal_enabled=True,
        paypal_environment="sandbox",
        paypal_base_url="https://api-m.sandbox.paypal.com",
        paypal_client_id="synthetic-client",
        paypal_client_secret="synthetic-secret",
        paypal_expected_merchant_id="SYNTHETICMERCHANT",
        paypal_binding_capture_id="SYNTHETICCAPTURE",
        paypal_provider_email="provider@example.invalid",
        paypal_buyer_email="buyer@example.invalid",
    )
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.mark.parametrize(
    "url",
    [
        "https://api-m.paypal.com",
        "https://api-m.sandbox.paypal.com.evil.invalid",
        "http://api-m.sandbox.paypal.com",
    ],
)
def test_independent_client_refuses_other_hosts_without_network(url):
    calls = []

    def transport(request):
        calls.append(request)
        raise AssertionError("configuration refusal must precede network")

    client = PayPalClient(
        sandbox_settings(paypal_base_url=url), transport=httpx.MockTransport(transport)
    )
    with pytest.raises(DomainError):
        client.capture("SYNTHETICCAPTURE")
    assert calls == []


def test_independent_oauth_cache_and_ambiguous_post_no_retry():
    paths = []

    def transport(request):
        paths.append((request.method, request.url.path))
        assert request.url.host == "api-m.sandbox.paypal.com"
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(
                200,
                json={
                    "access_token": "synthetic-token",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                },
            )
        if request.method == "POST":
            raise httpx.ReadTimeout("synthetic ambiguous outcome")
        return httpx.Response(200, json={"id": "SYNTHETICCAPTURE", "status": "COMPLETED"})

    client = PayPalClient(sandbox_settings(), transport=httpx.MockTransport(transport))
    client.capture("SYNTHETICCAPTURE")
    client.capture("SYNTHETICCAPTURE")
    with pytest.raises(PayPalError) as outcome:
        client.request("POST", "/v2/invoicing/invoices", {"synthetic": True})
    assert outcome.value.uncertain
    assert paths.count(("POST", "/v1/oauth2/token")) == 1
    assert paths.count(("POST", "/v2/invoicing/invoices")) == 1


def test_independent_mutating_redirect_is_uncertain_and_never_followed():
    paths = []

    def transport(request):
        paths.append(request.url.host)
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(
                200,
                json={
                    "access_token": "synthetic-token",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                },
            )
        return httpx.Response(307, headers={"Location": "https://example.invalid/collect"})

    client = PayPalClient(sandbox_settings(), transport=httpx.MockTransport(transport))
    with pytest.raises(PayPalError) as outcome:
        client.request("POST", "/v2/invoicing/invoices", {})
    assert outcome.value.uncertain
    assert paths == ["api-m.sandbox.paypal.com", "api-m.sandbox.paypal.com"]
