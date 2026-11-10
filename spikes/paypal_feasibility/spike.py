"""Minimal PayPal Sandbox Invoicing v2 feasibility spike.

Usage: python spike.py <command> [--label L] [--partial true|false|omit]

Commands: oauth, identity, create, send, record, get, cancel, qr, idem,
          capture-payee, webhook-event-types, webhooks-list

Reads credentials from the project-root .env (or the file named by
PAYPAL_SPIKE_ENV_FILE, used only for the offline fail-closed demo).
Fails closed unless PAYPAL_ENVIRONMENT=sandbox and PAYPAL_BASE_URL is exactly
the Sandbox host. Never prints secrets, tokens or payer URLs. Stores only test
invoice ids (by label) in .state.json next to this file.
"""

import argparse
import json
import os
import sys
import uuid
from datetime import date
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
STATE = Path(__file__).with_name(".state.json")
SANDBOX = "https://api-m.sandbox.paypal.com"

# Spike amounts (USD decimal strings). Invoice covers payable + already-paid;
# the already-paid part is recorded as an external OTHER payment (UPI stand-in).
INVOICE_ITEM_AMOUNT = "230.00"
EXTERNAL_PAID_AMOUNT = "40.00"


def load_env() -> dict[str, str]:
    path = Path(os.environ.get("PAYPAL_SPIKE_ENV_FILE") or ROOT / ".env")
    if not path.is_file():
        sys.exit("Refusing to run: env file not found")
    env = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


ENV = load_env()
if ENV.get("PAYPAL_ENVIRONMENT") != "sandbox":
    sys.exit("Refusing to run: PAYPAL_ENVIRONMENT must be exactly 'sandbox'")
if ENV.get("PAYPAL_BASE_URL") not in (SANDBOX, SANDBOX + "/"):
    sys.exit(f"Refusing to run: PAYPAL_BASE_URL must be set to exactly {SANDBOX}")
BASE = SANDBOX


def redact(value: str | None) -> str | None:
    return f"...{value[-4:]}" if value else None


def oauth_response() -> httpx.Response:
    return httpx.post(
        f"{BASE}/v1/oauth2/token",
        auth=(ENV["PAYPAL_CLIENT_ID"], ENV["PAYPAL_CLIENT_SECRET"]),
        data={"grant_type": "client_credentials"},
        timeout=30,
    )


def token() -> str:
    r = oauth_response()
    if r.status_code != 200:
        report("oauth", r)
        sys.exit(1)
    return r.json()["access_token"]


def client() -> httpx.Client:
    return httpx.Client(
        base_url=BASE,
        headers={"Authorization": f"Bearer {token()}", "Content-Type": "application/json"},
        timeout=30,
    )


def http_info(r: httpx.Response) -> dict:
    out = {"http_status": r.status_code, "debug_id": r.headers.get("paypal-debug-id")}
    if r.status_code >= 400:
        try:
            body = r.json()
            out["error"] = {
                k: body.get(k) for k in ("name", "error", "message", "error_description")
                if body.get(k)
            }
            out["details"] = [
                {k: d.get(k) for k in ("field", "issue", "description")}
                for d in body.get("details", [])
            ]
        except ValueError:
            # Non-JSON body: never echo it; report shape only.
            out["error"] = {
                "non_json_body": True,
                "content_type": r.headers.get("content-type"),
                "length": len(r.content),
            }
    return out


def report(step: str, r: httpx.Response, extra: dict | None = None) -> None:
    out = {"step": step} | http_info(r)
    if extra:
        out.update(extra)
    print(json.dumps(out, indent=2))


def load_state() -> dict:
    if not STATE.exists():
        return {}
    data = json.loads(STATE.read_text())
    if "invoice_id" in data:  # old single-invoice format; drop any stored payer URL
        data = {"phase0-original": data["invoice_id"]}
        STATE.write_text(json.dumps(data))
    return data


def invoice_id(label: str) -> str:
    return load_state()[label]


def save_invoice(label: str, inv_id: str) -> None:
    data = load_state()
    data[label] = inv_id
    STATE.write_text(json.dumps(data))


def summarize(inv: dict) -> dict:
    payments = inv.get("payments", {})
    return {
        "invoice_id": inv.get("id"),
        "invoice_status": inv.get("status"),
        "currency": inv.get("detail", {}).get("currency_code"),
        "total": inv.get("amount", {}).get("value"),
        "due_amount": inv.get("due_amount", {}).get("value"),
        "paid_amount": payments.get("paid_amount", {}).get("value"),
        "payments": [
            {k: t.get(k) for k in ("type", "method", "payment_date")}
            | {"amount": t.get("amount", {}).get("value"), "has_payment_id": bool(t.get("payment_id"))}
            for t in payments.get("transactions", [])
        ],
        "configuration": inv.get("configuration"),
        "has_payer_view_link": any(
            l.get("rel") == "payer-view" for l in inv.get("links", [])
        ) or bool(inv.get("detail", {}).get("metadata", {}).get("recipient_view_url")),
    }


def snapshot(c: httpx.Client, inv_id: str, when: str) -> dict:
    """GET the invoice and report this GET's own status and debug id."""
    r = c.get(f"/v2/invoicing/invoices/{inv_id}")
    out = {"when": when} | http_info(r)
    if r.status_code == 200:
        out["invoice"] = summarize(r.json())
    return out


def mutate(c: httpx.Client, path: str, body: dict, request_id: str | None = None) -> tuple:
    rid = request_id or str(uuid.uuid4())
    r = c.post(path, json=body, headers={"PayPal-Request-Id": rid})
    return r, rid


def invoice_body(partial: str) -> dict:
    config: dict = {"allow_tip": False}
    if partial != "omit":
        # Documented location: configuration.partial_payment.allow_partial_payment
        config["partial_payment"] = {"allow_partial_payment": partial == "true"}
    return {
        "detail": {
            "currency_code": "USD",
            "note": "CareDirect feasibility spike - synthetic test invoice",
            "payment_term": {"term_type": "DUE_ON_RECEIPT"},
        },
        "invoicer": {"email_address": ENV["PAYPAL_PROVIDER_EMAIL"]},
        "primary_recipients": [
            {"billing_info": {"email_address": ENV["PAYPAL_BUYER_EMAIL"]}}
        ],
        "items": [
            {
                "name": "Synthetic hospital bill - spike",
                "quantity": "1",
                "unit_amount": {"currency_code": "USD", "value": INVOICE_ITEM_AMOUNT},
                "unit_of_measure": "AMOUNT",
            }
        ],
        "configuration": config,
    }


def new_invoice_id(r: httpx.Response) -> str | None:
    if r.status_code not in (200, 201) or not r.content:
        return None
    inv = r.json()
    return inv.get("id") or inv.get("href", "").rstrip("/").split("/")[-1] or None


def cmd_oauth(a) -> None:
    r = oauth_response()
    extra = {}
    if r.status_code == 200:
        b = r.json()
        scopes = b.get("scope", "").split()
        extra = {
            "token_type": b.get("token_type"),
            "expires_in": b.get("expires_in"),
            "app_id": redact(b.get("app_id")),
            "invoicing_scope": any("invoicing" in s for s in scopes),
            "scope_count": len(scopes),
        }
    report("oauth", r, extra)


def cmd_identity(a) -> None:
    """Merchant id as assigned by PayPal for the token's account (not echoed input)."""
    expected = ENV.get("PAYPAL_EXPECTED_MERCHANT_ID")
    with client() as c:
        r = c.get("/v1/identity/oauth2/userinfo", params={"schema": "paypalv1.1"})
        extra = {"expected_merchant_id_configured": bool(expected)}
        if r.status_code == 200:
            b = r.json()
            pid = b.get("payer_id")
            extra |= {
                "fields_returned": sorted(b.keys()),
                "payer_id": redact(pid),
                "matches_expected": (pid == expected) if expected and pid else None,
            }
        report("identity_userinfo", r, extra)


def cmd_capture_payee(a) -> None:
    """Payee merchant id on the PAYPAL capture recorded against an invoice."""
    expected = ENV.get("PAYPAL_EXPECTED_MERCHANT_ID")
    with client() as c:
        inv = c.get(f"/v2/invoicing/invoices/{invoice_id(a.label)}")
        if inv.status_code != 200:
            report("capture_payee_invoice_get", inv)
            return
        txns = [t for t in inv.json().get("payments", {}).get("transactions", [])
                if t.get("type") == "PAYPAL" and t.get("payment_id")]
        if not txns:
            print(json.dumps({"step": "capture_payee", "paypal_transaction_found": False}))
            return
        r = c.get(f"/v2/payments/captures/{txns[0]['payment_id']}")
        extra = {"invoice_get": http_info(inv)}
        if r.status_code == 200:
            mid = (r.json().get("payee") or {}).get("merchant_id")
            extra |= {
                "capture_status": r.json().get("status"),
                "payee_merchant_id": redact(mid),
                "matches_expected": (mid == expected) if expected and mid else None,
            }
        report("capture_payee", r, extra)


def cmd_create(a) -> None:
    with client() as c:
        r = c.post(
            "/v2/invoicing/invoices",
            json=invoice_body(a.partial),
            headers={"PayPal-Request-Id": (rid := str(uuid.uuid4())),
                     "Prefer": "return=representation"},
        )
        extra = {"label": a.label, "partial_sent": a.partial, "request_id": rid}
        inv_id = new_invoice_id(r)
        if inv_id:
            save_invoice(a.label, inv_id)
            extra["after"] = snapshot(c, inv_id, "after_create")
        report("create", r, extra)


def cmd_idem(a) -> None:
    """Repeat an identical create with the same PayPal-Request-Id."""
    body = invoice_body(a.partial)
    rid = str(uuid.uuid4())
    with client() as c:
        results = []
        for attempt in (1, 2):
            r = c.post("/v2/invoicing/invoices", json=body,
                       headers={"PayPal-Request-Id": rid, "Prefer": "return=representation"})
            inv_id = new_invoice_id(r)
            if inv_id:
                save_invoice(f"{a.label}-{attempt}", inv_id)
            results.append({"attempt": attempt} | http_info(r) | {"invoice_id": inv_id})
        ids = [x["invoice_id"] for x in results]
        print(json.dumps({
            "step": "idempotency_create", "request_id": rid, "attempts": results,
            "same_invoice_returned": bool(ids[0]) and ids[0] == ids[1],
        }, indent=2))


def cmd_send(a) -> None:
    inv_id = invoice_id(a.label)
    with client() as c:
        before = snapshot(c, inv_id, "before_send")
        r, rid = mutate(c, f"/v2/invoicing/invoices/{inv_id}/send",
                        {"send_to_invoicer": False, "send_to_recipient": True})
        extra = {"label": a.label, "request_id": rid, "before": before}
        if r.status_code < 300:
            links = r.json().get("links", []) if r.content else []
            extra["send_response_has_payer_view"] = any(
                l.get("rel") == "payer-view" for l in links)
            extra["send_response_link_rels"] = [l.get("rel") for l in links]
        extra["after"] = snapshot(c, inv_id, "after_send")
        report("send", r, extra)


def cmd_record(a) -> None:
    inv_id = invoice_id(a.label)
    with client() as c:
        before = snapshot(c, inv_id, "before_record")
        r, rid = mutate(c, f"/v2/invoicing/invoices/{inv_id}/payments", {
            "method": "OTHER",
            "payment_date": date.today().isoformat(),
            "note": "Synthetic prior UPI payment (spike)",
            "amount": {"currency_code": "USD", "value": EXTERNAL_PAID_AMOUNT},
        })
        extra = {"label": a.label, "request_id": rid, "before": before}
        if r.status_code < 300 and r.content:
            extra["payment_id_returned"] = bool(r.json().get("payment_id"))
        extra["after"] = snapshot(c, inv_id, "after_record")
        report("record_external_payment", r, extra)


def cmd_get(a) -> None:
    with client() as c:
        print(json.dumps({"step": "get", "label": a.label}
                         | snapshot(c, invoice_id(a.label), "get"), indent=2))


def cmd_cancel(a) -> None:
    inv_id = invoice_id(a.label)
    with client() as c:
        before = snapshot(c, inv_id, "before_cancel")
        r, rid = mutate(c, f"/v2/invoicing/invoices/{inv_id}/cancel",
                        {"send_to_invoicer": False, "send_to_recipient": False})
        extra = {"label": a.label, "request_id": rid, "before": before,
                 "after": snapshot(c, inv_id, "after_cancel")}
        report("cancel", r, extra)


def cmd_qr(a) -> None:
    """QR encodes a payer link: report shape only, never print or save the image."""
    inv_id = invoice_id(a.label)
    with client() as c:
        r, rid = mutate(c, f"/v2/invoicing/invoices/{inv_id}/generate-qr-code",
                        {"width": 300, "height": 300, "action": "pay"})
        extra = {"label": a.label, "request_id": rid}
        if r.status_code == 200:
            extra |= {
                "content_type": r.headers.get("content-type"),
                "body_length": len(r.content),
                "contains_base64_png": b"iVBORw0KGgo" in r.content,
            }
        report("generate_qr_code", r, extra)


def cmd_webhook_event_types(a) -> None:
    with client() as c:
        r = c.get("/v1/notifications/webhooks-event-types")
        extra = {}
        if r.status_code == 200:
            names = [e.get("name") for e in r.json().get("event_types", [])]
            extra = {"total": len(names),
                     "invoicing": sorted(n for n in names if n and n.startswith("INVOICING."))}
        report("webhook_event_types", r, extra)


def cmd_webhooks_list(a) -> None:
    with client() as c:
        r = c.get("/v1/notifications/webhooks")
        extra = {}
        if r.status_code == 200:
            extra = {"registered_webhooks": len(r.json().get("webhooks", []))}
        report("webhooks_list", r, extra)


COMMANDS = {
    "oauth": cmd_oauth,
    "identity": cmd_identity,
    "capture-payee": cmd_capture_payee,
    "create": cmd_create,
    "idem": cmd_idem,
    "send": cmd_send,
    "record": cmd_record,
    "get": cmd_get,
    "cancel": cmd_cancel,
    "qr": cmd_qr,
    "webhook-event-types": cmd_webhook_event_types,
    "webhooks-list": cmd_webhooks_list,
}

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=COMMANDS)
    p.add_argument("--label", default="main")
    p.add_argument("--partial", choices=("true", "false", "omit"), default="false")
    args = p.parse_args()
    COMMANDS[args.command](args)
