"""Server-only Sandbox REST adapter. No automatic retries of mutating requests."""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from functools import lru_cache
from urllib.parse import urlsplit

import httpx

from app.config import Settings, get_settings
from app.errors import DomainError

_ID = re.compile(r"^[A-Za-z0-9-]{1,64}$")


class PayPalError(DomainError):
    def __init__(self, code="PAYPAL_UNAVAILABLE", uncertain=False):
        super().__init__(
            "PayPal could not confirm this operation. Verify its state before continuing."
        )
        self.code = code
        self.uncertain = uncertain


def resource_id(value):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise DomainError("Invalid PayPal resource reference.")
    return value


def safe_checkout_url(value):
    if not isinstance(value, str):
        return None
    try:
        u = urlsplit(value)
    except ValueError:
        return None
    if (
        u.scheme == "https"
        and u.netloc == "www.sandbox.paypal.com"
        and u.path.startswith(("/invoice/p/", "/invoice/s/pay/"))
        and not u.fragment
    ):
        return value
    return None


class PayPalClient:
    def __init__(self, settings: Settings, transport=None):
        self.settings = settings
        self._token = None
        self._expires = 0
        self._lock = threading.Lock()
        self.http = httpx.Client(
            base_url="https://api-m.sandbox.paypal.com",
            timeout=20,
            follow_redirects=False,
            transport=transport,
        )

    def require_config(self):
        s = self.settings
        if (
            not s.paypal_enabled
            or s.paypal_environment != "sandbox"
            or s.paypal_base_url != "https://api-m.sandbox.paypal.com"
            or not all(
                [
                    s.paypal_client_id,
                    s.paypal_client_secret,
                    s.paypal_expected_merchant_id,
                    s.paypal_binding_capture_id,
                    s.paypal_provider_email,
                    s.paypal_buyer_email,
                ]
            )
        ):
            raise DomainError(
                "Sandbox payments need backend configuration and receiving-account evidence."
            )

    @property
    def fingerprint(self):
        return hashlib.sha256(self.settings.paypal_client_id.encode()).hexdigest()

    def token(self):
        self.require_config()
        with self._lock:
            if self._token and time.monotonic() < self._expires:
                return self._token
            try:
                r = self.http.post(
                    "/v1/oauth2/token",
                    data={"grant_type": "client_credentials"},
                    auth=(self.settings.paypal_client_id, self.settings.paypal_client_secret),
                )
                if r.status_code != 200:
                    raise PayPalError("OAUTH_REJECTED")
                body = r.json()
                if body.get("token_type", "").lower() != "bearer" or not body.get("access_token"):
                    raise PayPalError("OAUTH_INVALID")
                self._token = body["access_token"]
                self._expires = time.monotonic() + max(0, int(body["expires_in"]) - 60)
                return self._token
            except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as exc:
                raise PayPalError("OAUTH_UNAVAILABLE") from exc

    def request(self, method, path, body=None, request_id=None):
        headers = {"Authorization": f"Bearer {self.token()}", "Prefer": "return=representation"}
        if request_id:
            headers["PayPal-Request-Id"] = request_id
        try:
            response = self.http.request(method, path, json=body, headers=headers)
            if response.status_code == 401:
                self._token, self._expires = None, 0
            if not 200 <= response.status_code < 300:
                raise PayPalError("HTTP_" + str(response.status_code), uncertain=method != "GET")
            payload = response.json() if response.content else {}
            if not isinstance(payload, dict):
                raise PayPalError("INVALID_RESPONSE", uncertain=method != "GET")
            return payload
        except (httpx.HTTPError, ValueError) as exc:
            raise PayPalError("NETWORK_OR_INVALID_RESPONSE", uncertain=method != "GET") from exc

    def capture(self, capture_id):
        return self.request("GET", f"/v2/payments/captures/{resource_id(capture_id)}")

    def invoice(self, invoice_id):
        return self.request("GET", f"/v2/invoicing/invoices/{resource_id(invoice_id)}")

    def verify_webhook(self, headers, raw_body):
        """Official postback verification; retain webhook_event bytes exactly as received.

        No certificate URL is fetched by this application. Verification POST is read-only
        with respect to money and never creates/sends/records an invoice payment.
        """
        if not self.settings.paypal_webhook_id:
            raise PayPalError("WEBHOOK_NOT_CONFIGURED")
        fields = {
            name: headers.get("paypal-" + name.replace("_", "-"))
            for name in (
                "auth_algo",
                "cert_url",
                "transmission_id",
                "transmission_sig",
                "transmission_time",
            )
        }
        if any(not isinstance(v, str) or not v or len(v) > 4096 for v in fields.values()):
            return False
        fields["webhook_id"] = self.settings.paypal_webhook_id
        envelope = json.dumps(fields, separators=(",", ":")).encode()[:-1]
        envelope += b',"webhook_event":' + raw_body + b"}"
        try:
            r = self.http.post(
                "/v1/notifications/verify-webhook-signature",
                content=envelope,
                headers={
                    "Authorization": f"Bearer {self.token()}",
                    "Content-Type": "application/json",
                },
            )
            if r.status_code != 200:
                raise PayPalError("WEBHOOK_VERIFICATION_UNAVAILABLE")
            return r.json().get("verification_status") == "SUCCESS"
        except (httpx.HTTPError, ValueError, AttributeError) as exc:
            raise PayPalError("WEBHOOK_VERIFICATION_UNAVAILABLE") from exc


@lru_cache
def get_paypal_client():
    return PayPalClient(get_settings())
