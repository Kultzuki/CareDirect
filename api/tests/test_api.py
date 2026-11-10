"""HTTP API tests through FastAPI's TestClient on the test database."""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.main import app
from app.seed import seed


@pytest.fixture
def demo(db):
    case = seed(db)
    return case, {"X-Demo-User-Id": str(case.payer_user_id)}


def test_health(client):
    assert client.get("/health").json() == {"status": "ok", "database": "ok"}


class _FailingEngine:
    def __init__(self, exc: Exception):
        self._exc = exc

    def connect(self):
        raise self._exc


def _raw_client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def test_unknown_route_is_structured_404():
    r = _raw_client().get("/no-such-route")
    assert r.status_code == 404
    body = r.json()
    assert body["error"] == "not_found"
    assert "detail" not in body


def test_method_not_allowed_is_structured_405():
    r = _raw_client().delete("/health")
    assert r.status_code == 405
    assert r.json()["error"] == "method_not_allowed"
    assert "allow" in {k.lower() for k in r.headers}


def test_health_db_unavailable_returns_503(monkeypatch):
    exc = OperationalError("SELECT 1", None, Exception("secret-ish text"))
    monkeypatch.setattr("app.main.engine", _FailingEngine(exc))
    r = _raw_client().get("/health")
    assert r.status_code == 503
    assert r.json() == {"status": "error", "database": "unavailable"}
    assert "secret-ish" not in r.text


def test_unhandled_error_is_structured_500(monkeypatch):
    monkeypatch.setattr("app.main.engine", _FailingEngine(RuntimeError("boom-internal")))
    r = _raw_client().get("/health")
    assert r.status_code == 500
    assert r.json()["error"] == "internal_error"
    assert "boom-internal" not in r.text


def test_requires_demo_identity(client, demo):
    case, _ = demo
    assert client.get(f"/api/cases/{case.id}").status_code == 403


def test_other_payer_cannot_see_case(client, demo, other_payer):
    case, _ = demo
    r = client.get(f"/api/cases/{case.id}", headers={"X-Demo-User-Id": str(other_payer.id)})
    assert r.status_code == 403


def test_seed_case_detail(client, demo):
    case, h = demo
    r = client.get(f"/api/cases/{case.id}", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["is_demo"] is True
    assert body["buckets"] == {
        "insurance_present": False,
        "currency": "INR",
        "bill_total": "25000.00",
        "original_bill_total": "25000.00",
        "adjustments": "0.00",
        "net_bill_total": "25000.00",
        "payable_now": "19000.00",
        "queried": "2000.00",
        "already_paid": "4000.00",
        "pending_review": "0.00",
        "invariant_holds": True,
        "consistent": True,
        "issues": [],
    }
    [bill] = body["bills"]
    assert bill["source_type"] == "SEEDED_SYNTHETIC"
    assert len(bill["line_items"]) == 6
    assert all(isinstance(li["line_total"], str) for li in bill["line_items"])
    [flag] = body["flags"]
    assert flag["flag_type"] == "POSSIBLE_EXACT_DUPLICATE"
    assert flag["amount_involved"] == "2000.00"
    [payment] = body["external_payments"]
    assert payment["status"] == "MATCHED"
    assert payment["match_basis"]["label"] == "Matched to bill evidence (not bank-verified)"
    assert body["approval_readiness"] == {"ready": True, "blockers": []}


def test_money_never_serialised_as_number(client, demo):
    case, h = demo
    for path in ("", "/ledger", "/buckets", "/line-items", "/flags"):
        text = client.get(f"/api/cases/{case.id}{path}", headers=h).text
        assert '"amount":2' not in text and '"line_total":2' not in text


def test_payment_endpoints_require_payer_and_immutable_approval(client, demo):
    import uuid

    case, headers = demo
    paths = set(client.app.openapi()["paths"])
    assert "/api/cases/{case_id}/payments/invoice" in paths
    # No browser-facing arbitrary PayPal method/URL proxy exists.
    assert not any("proxy" in p or "paypal/{" in p for p in paths)
    root = f"/api/cases/{case.id}/payments"
    assert client.get(root).status_code == 403
    assert (
        client.post(root + "/invoice", json={"approval_id": str(uuid.uuid4())}).status_code == 403
    )
    missing = client.post(
        root + "/invoice", headers=headers, json={"approval_id": str(uuid.uuid4())}
    )
    assert missing.status_code == 409
    assert "approval" in missing.json()["message"].lower()
    assert client.post(root + "/invoice", headers=headers, json={}).status_code == 422


def _new_case(client, h):
    r = client.post("/api/cases", json={"patient_alias": "Patient B", "currency": "INR"}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _bill(**over):
    body = {
        "provider_name": "Synthetic Clinic",
        "currency": "INR",
        "bill_date": "2026-11-04",
        "printed_total": "5000.00",
        "printed_advance_paid": "1000.00",
        "printed_balance_due": "4000.00",
        "lines": [
            {
                "line_number": 1,
                "description_raw": "Consultation",
                "line_total": "1000.00",
                "service_date": "2026-11-02",
                "quantity": "1",
                "unit_price": "1000.00",
            },
            {
                "line_number": 2,
                "description_raw": "MRI",
                "line_total": "2000.00",
                "service_date": "2026-11-02",
                "quantity": "1",
                "unit_price": "2000.00",
            },
            {
                "line_number": 3,
                "description_raw": "mri",
                "line_total": "2000.00",
                "service_date": "2026-11-02",
                "quantity": "1",
                "unit_price": "2000.00",
            },
        ],
    }
    body.update(over)
    return body


def test_float_money_rejected_at_api(client, headers):
    cid = _new_case(client, headers)
    bad = _bill()
    bad["lines"][0]["line_total"] = 1000.0
    r = client.post(f"/api/cases/{cid}/bills", json=bad, headers=headers)
    assert r.status_code == 422
    assert r.json()["error"] == "invalid_request"


def test_sub_paise_money_rejected_at_api(client, headers):
    cid = _new_case(client, headers)
    r = client.post(
        f"/api/cases/{cid}/bills", json=_bill(printed_total="5000.005"), headers=headers
    )
    assert r.status_code == 422


def test_client_cannot_set_source_type(client, headers):
    cid = _new_case(client, headers)
    r = client.post(
        f"/api/cases/{cid}/bills", json=_bill(source_type="AI_EXTRACTED"), headers=headers
    )
    assert r.status_code == 422


def test_full_flow_over_http(client, headers):
    cid = _new_case(client, headers)
    r = client.post(f"/api/cases/{cid}/bills", json=_bill(), headers=headers)
    assert r.status_code == 201, r.text
    lines = {li["line_number"]: li for li in r.json()["line_items"]}

    checks = client.post(f"/api/cases/{cid}/run-checks", headers=headers).json()
    [dup] = checks["flags_created"]
    assert dup["flag_type"] == "POSSIBLE_EXACT_DUPLICATE"
    # Running checks again does not create duplicate flags.
    assert client.post(f"/api/cases/{cid}/run-checks", headers=headers).json() == {
        "flags_created": []
    }

    r = client.post(
        f"/api/line-items/{lines[3]['id']}/query",
        json={"reason": "Possible duplicate of line 2", "flag_id": dup["id"]},
        headers=headers,
    )
    assert r.status_code == 200 and r.json()["status"] == "QUERIED"
    assert r.json()["line_total"] == "2000.00"  # unchanged

    for n in (1, 2):
        assert (
            client.post(
                f"/api/line-items/{lines[n]['id']}/accept", json={}, headers=headers
            ).status_code
            == 200
        )

    pay = client.post(
        f"/api/cases/{cid}/external-payments",
        headers=headers,
        json={
            "method": "UPI",
            "amount": "1000.00",
            "currency": "INR",
            "paid_on": "2026-11-01",
            "reference": "UPI-TEST-1",
            "payee_name": "Synthetic Clinic",
        },
    )
    assert pay.status_code == 201 and pay.json()["status"] == "SUBMITTED"
    # Submitted evidence does not count as paid yet.
    b = client.get(f"/api/cases/{cid}/buckets", headers=headers).json()
    assert (b["payable_now"], b["already_paid"]) == ("3000.00", "0.00")

    rec = client.post(f"/api/external-payments/{pay.json()['id']}/reconcile", headers=headers)
    assert rec.json()["status"] == "MATCHED"

    b = client.get(f"/api/cases/{cid}/buckets", headers=headers).json()
    assert (b["bill_total"], b["payable_now"], b["queried"], b["already_paid"]) == (
        "5000.00",
        "2000.00",
        "2000.00",
        "1000.00",
    )
    assert Decimal(b["bill_total"]) == sum(
        Decimal(b[k]) for k in ("payable_now", "queried", "already_paid")
    )

    # Re-query an already queried line -> 409 invalid transition.
    r = client.post(
        f"/api/line-items/{lines[3]['id']}/query", json={"reason": "again"}, headers=headers
    )
    assert r.status_code == 409 and r.json()["error"] == "invalid_transition"

    # Release the query with a note -> returns to payable.
    r = client.post(
        f"/api/line-items/{lines[3]['id']}/accept",
        json={"note": "Provider confirmed two separate scans"},
        headers=headers,
    )
    assert r.status_code == 200
    b = client.get(f"/api/cases/{cid}/buckets", headers=headers).json()
    assert (b["payable_now"], b["queried"]) == ("4000.00", "0.00")

    ledger = client.get(f"/api/cases/{cid}/ledger", headers=headers).json()
    assert [e["entry_type"] for e in ledger] == [
        "BILL_CHARGE",
        "BILL_CHARGE",
        "BILL_CHARGE",
        "QUERY_HOLD",
        "EXTERNAL_PAYMENT",
        "QUERY_RELEASE",
    ]
    audit = client.get(f"/api/cases/{cid}/audit-events", headers=headers).json()
    assert {e["ledger_entry_id"] for e in audit if e["ledger_entry_id"]} == {
        e["id"] for e in ledger
    }


def test_mismatched_receipt_needs_clarification(client, headers):
    cid = _new_case(client, headers)
    client.post(f"/api/cases/{cid}/bills", json=_bill(), headers=headers)
    pay = client.post(
        f"/api/cases/{cid}/external-payments",
        headers=headers,
        json={
            "method": "UPI",
            "amount": "1200.00",
            "currency": "INR",
            "paid_on": "2026-11-01",
            "reference": "UPI-TEST-2",
            "payee_name": "Synthetic Clinic",
        },
    ).json()
    rec = client.post(f"/api/external-payments/{pay['id']}/reconcile", headers=headers).json()
    assert rec["status"] == "NEEDS_CLARIFICATION"
    assert any("exceeds" in p for p in rec["match_basis"]["problems"])
    b = client.get(f"/api/cases/{cid}/buckets", headers=headers).json()
    assert b["already_paid"] == "0.00"
    flags = client.get(f"/api/cases/{cid}/flags", headers=headers).json()
    assert [f["flag_type"] for f in flags] == ["ADVANCE_PAYMENT_MISMATCH"]


def test_arithmetic_mismatch_flag(client, headers):
    cid = _new_case(client, headers)
    body = _bill(printed_total="5500.00", printed_advance_paid=None, printed_balance_due=None)
    client.post(f"/api/cases/{cid}/bills", json=body, headers=headers)
    flags = client.post(f"/api/cases/{cid}/run-checks", headers=headers).json()["flags_created"]
    arith = [f for f in flags if f["flag_type"] == "ARITHMETIC_MISMATCH"]
    assert len(arith) == 1 and arith[0]["amount_involved"] == "500.00"


def test_currency_mismatch_rejected(client, headers):
    cid = _new_case(client, headers)
    r = client.post(f"/api/cases/{cid}/bills", json=_bill(currency="USD"), headers=headers)
    assert r.status_code == 422


def test_invalid_case_transition_returns_409(client, headers):
    cid = _new_case(client, headers)
    r = client.post(f"/api/cases/{cid}/transition", json={"status": "CLOSED"}, headers=headers)
    assert r.status_code == 409


def test_unknown_case_404(client, headers):
    r = client.get("/api/cases/00000000-0000-0000-0000-000000000000", headers=headers)
    assert r.status_code == 404
