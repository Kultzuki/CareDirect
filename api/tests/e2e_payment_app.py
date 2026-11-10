"""Isolated browser-test API harness. No production mock switch or remote traffic."""

import json
import os
import uuid
from copy import deepcopy
from decimal import Decimal

import httpx
from fastapi import HTTPException

from app.config import Settings, get_settings
from app.main import app
from app.paypal_client import PayPalClient, get_paypal_client

if os.environ.get("CAREDIRECT_E2E_MOCK") != "1" or not get_settings().database_url.endswith(
    "/caredirect_test"
):
    raise RuntimeError("E2E harness requires explicit opt-in and the isolated test database")

settings = Settings(
    _env_file=None,
    paypal_enabled=True,
    paypal_environment="sandbox",
    paypal_base_url="https://api-m.sandbox.paypal.com",
    paypal_client_id="synthetic-client",
    paypal_client_secret="synthetic-secret",
    paypal_expected_merchant_id="SYNTHETICMERCHANT",
    paypal_binding_capture_id="SYNTHETICBINDING",
    paypal_provider_email="provider@example.invalid",
    paypal_buyer_email="buyer@example.invalid",
)
invoices = {}
captures = {}
counts = {"create": 0, "send": 0, "external": 0}


def amount(value):
    return {"currency_code": "USD", "value": format(value, ".2f")}


def transport(request):
    path = request.url.path
    assert request.url.host == "api-m.sandbox.paypal.com"
    if path == "/v1/oauth2/token":
        return httpx.Response(
            200,
            json={"access_token": "synthetic-token", "token_type": "Bearer", "expires_in": 3600},
        )
    if path == "/v2/payments/captures/SYNTHETICBINDING":
        return httpx.Response(
            200,
            json={
                "id": "SYNTHETICBINDING",
                "status": "COMPLETED",
                "amount": amount(Decimal("1")),
                "payee": {"merchant_id": "SYNTHETICMERCHANT"},
            },
        )
    if path.startswith("/v2/payments/captures/"):
        return httpx.Response(200, json=captures[path.rsplit("/", 1)[-1]])
    if path == "/v2/invoicing/invoices" and request.method == "POST":
        counts["create"] += 1
        body = json.loads(request.content)
        invoice_id = "INV2-" + uuid.uuid4().hex.upper()
        total = Decimal(body["items"][0]["unit_amount"]["value"])
        invoices[invoice_id] = {
            **deepcopy(body),
            "id": invoice_id,
            "status": "DRAFT",
            "amount": amount(total),
            "due_amount": amount(total),
            "payments": {"paid_amount": amount(Decimal("0")), "transactions": []},
        }
        invoices[invoice_id]["detail"]["metadata"] = {
            "recipient_view_url": "https://www.sandbox.paypal.com/invoice/p/SYNTHETIC-NEVER-OPEN"
        }
        return httpx.Response(201, json={"id": invoice_id})
    prefix = "/v2/invoicing/invoices/"
    if path.startswith(prefix):
        parts = path[len(prefix) :].split("/")
        invoice = invoices[parts[0]]
        if request.method == "GET":
            return httpx.Response(200, json=invoice)
        body = json.loads(request.content)
        if parts[-1] == "send":
            assert body.get("send_to_recipient") is False and body.get("send_to_invoicer") is False
            counts["send"] += 1
            invoice["status"] = "SENT"
            return httpx.Response(200, json={})
        if parts[-1] == "payments":
            assert body["method"] == "OTHER"
            counts["external"] += 1
            txn = {**body, "type": "EXTERNAL", "payment_id": "EXTERNAL-" + uuid.uuid4().hex}
            invoice["payments"]["transactions"].append(txn)
            value = Decimal(body["amount"]["value"])
            invoice["due_amount"] = amount(Decimal(invoice["due_amount"]["value"]) - value)
            invoice["payments"]["paid_amount"] = amount(
                Decimal(invoice["amount"]["value"]) - Decimal(invoice["due_amount"]["value"])
            )
            invoice["status"] = "PARTIALLY_PAID"
            return httpx.Response(200, json={"payment_id": txn["payment_id"]})
    raise AssertionError("Unexpected request in isolated PayPal transport")


mock_client = PayPalClient(settings, transport=httpx.MockTransport(transport))
app.dependency_overrides[get_paypal_client] = lambda: mock_client


@app.post("/__test__/invoices/{invoice_id}/complete")
def complete(invoice_id: str):
    """Deterministic test control, never a real checkout or production endpoint."""
    invoice = invoices.get(invoice_id)
    if not invoice:
        raise HTTPException(404)
    if invoice["status"] != "PAID":
        capture_id = "CAPTURE-" + uuid.uuid4().hex
        value = deepcopy(invoice["due_amount"])
        captures[capture_id] = {
            "id": capture_id,
            "status": "COMPLETED",
            "amount": value,
            "payee": {"merchant_id": "SYNTHETICMERCHANT"},
        }
        invoice["payments"]["transactions"].append(
            {"type": "PAYPAL", "payment_id": capture_id, "amount": value}
        )
        invoice["due_amount"] = amount(Decimal("0"))
        invoice["payments"]["paid_amount"] = deepcopy(invoice["amount"])
        invoice["status"] = "PAID"
    return {"provenance": "DETERMINISTIC_TEST_ONLY", "counts": counts}


@app.get("/__test__/counts")
def operation_counts():
    return {"provenance": "DETERMINISTIC_TEST_ONLY", **counts}
