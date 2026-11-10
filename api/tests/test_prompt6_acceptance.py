"""Independent API acceptance of provider proposals and payer financial decisions.

Uses native synthetic USD values; no PayPal request or real medical evidence.
"""

from datetime import date
from decimal import Decimal
from hashlib import sha256

import pytest

from app import services as svc
from app.extraction.synthetic import FIXTURES_BY_NAME, render
from app.models import EvidenceDocument
from app.states import DataSource, DocumentType, PaymentMethod, UserRole


def _case(db, actor):
    case = svc.create_case(db, actor, patient_alias="Synthetic acceptance", currency="USD")
    bill = svc.add_bill(
        db,
        actor,
        case.id,
        svc.BillInput(
            provider_name="Synthetic Harbor Clinic",
            currency="USD",
            bill_date=date(2026, 11, 9),
            printed_total=Decimal("250.00"),
            printed_advance_paid=Decimal("40.00"),
            lines=[
                svc.LineInput(1, "Consultation", Decimal("210.00"), date(2026, 11, 9)),
                svc.LineInput(
                    2,
                    "Laboratory panel",
                    Decimal("20.00"),
                    date(2026, 11, 9),
                    quantity=Decimal("1"),
                    unit_price=Decimal("20.00"),
                ),
                svc.LineInput(
                    3,
                    "Laboratory panel",
                    Decimal("20.00"),
                    date(2026, 11, 9),
                    quantity=Decimal("1"),
                    unit_price=Decimal("20.00"),
                ),
            ],
        ),
    )
    flags = svc.run_checks(db, actor, case.id)
    flag = next(f for f in flags if f.flag_type == "POSSIBLE_EXACT_DUPLICATE")
    for line in bill.line_items:
        svc.accept_line(db, actor, line.id)
    line = bill.line_items[2]
    svc.query_line(db, actor, line.id, "Please clarify the repeated panel", flag.id)
    payment = svc.record_external_payment(
        db,
        actor,
        case.id,
        svc.PaymentInput(
            method=PaymentMethod.OTHER,
            amount=Decimal("40.00"),
            currency="USD",
            paid_on=date(2026, 11, 9),
            reference="SYNTHETIC-USD-PRIOR",
            payee_name="Synthetic Harbor Clinic",
            bill_id=bill.id,
        ),
    )
    svc.reconcile_external_payment(db, actor, payment.id)
    assert svc.get_buckets(db, case).already_paid == Decimal("40.00")
    return case, bill, line, flag


def _link(client, headers, line, flag):
    result = client.post(
        f"/api/flags/{flag.id}/provider-links",
        headers=headers,
        json={
            "line_item_id": str(line.id),
            "question": "Please explain or correct the repeated laboratory panel.",
        },
    )
    assert result.is_success, result.text
    return result.json()


def _response(client, token, response_type="CORRECT", amount="0.00"):
    body = {
        "response_type": response_type,
        "response_text": "Synthetic billing review: the proposed amount is shown for payer review.",
        "responder_label": "Synthetic billing desk",
    }
    if response_type == "CORRECT":
        body["corrected_amount"] = amount
    result = client.post(f"/api/provider/respond/{token}", json=body)
    assert result.is_success, result.text
    return result.json()


def _preview(client, headers, response):
    result = client.get(f"/api/provider-responses/{response['id']}/preview", headers=headers)
    assert result.is_success, result.text
    return result.json()


def _decide(client, headers, response, preview, decision="ACCEPT"):
    return client.post(
        f"/api/provider-responses/{response['id']}/decision",
        headers=headers,
        json={
            "decision": decision,
            "note": "Payer reviewed the exact proposal against synthetic evidence.",
            "state_fingerprint": preview["state_fingerprint"],
        },
    )


@pytest.mark.parametrize(
    ("response_type", "proposed", "net", "payable"),
    [
        ("ACCEPT", None, "230.00", "190.00"),
        ("CORRECT", "0.00", "230.00", "190.00"),
        ("CORRECT", "25.00", "255.00", "215.00"),
        ("EXPLAIN", None, "250.00", "210.00"),
    ],
)
def test_native_usd_proposals_require_separate_exact_payer_acceptance(
    client, db, actor, headers, response_type, proposed, net, payable
):
    case, bill, line, flag = _case(db, actor)
    link = _link(client, headers, line, flag)
    before = svc.get_buckets(db, case)
    response = _response(client, link["token"], response_type, proposed)
    assert svc.get_buckets(db, case) == before
    preview = _preview(client, headers, response)
    assert preview["can_accept"] is True
    assert preview["after"]["net_bill_total"] == net
    assert preview["after"]["payable_now"] == payable
    assert _decide(client, headers, response, preview).is_success
    after = svc.get_buckets(db, case)
    assert after.original_bill_total == Decimal("250.00")
    assert after.net_bill_total == Decimal(net)
    assert after.payable_now == Decimal(payable)
    assert after.queried == Decimal("0.00")
    assert after.already_paid == Decimal("40.00")
    assert after.consistent
    assert bill.printed_total == Decimal("250.00")
    assert line.line_total == Decimal("20.00")
    entries = len(svc.case_ledger(db, case.id))
    assert _decide(client, headers, response, preview).status_code == 409
    assert len(svc.case_ledger(db, case.id)) == entries


@pytest.mark.parametrize("decision", ["REJECT", "KEEP_OPEN"])
def test_rejection_keeps_money_held_and_requires_fresh_provider_link(
    client, db, actor, headers, decision
):
    case, _, line, flag = _case(db, actor)
    link = _link(client, headers, line, flag)
    before = svc.get_buckets(db, case)
    response = _response(client, link["token"])
    preview = _preview(client, headers, response)
    assert _decide(client, headers, response, preview, decision).is_success
    assert svc.get_buckets(db, case) == before
    replay = client.post(
        f"/api/provider/respond/{link['token']}",
        json={
            "response_type": "EXPLAIN",
            "response_text": "A later answer",
            "responder_label": "Desk",
        },
    )
    assert replay.status_code in (403, 409)
    fresh = _link(client, headers, line, flag)
    assert fresh["token"] != link["token"]


def test_provider_view_and_workflow_reads_are_scoped(client, db, actor, headers, other_payer):
    case, _, line, flag = _case(db, actor)
    link = _link(client, headers, line, flag)
    page = client.get(f"/api/provider/respond/{link['token']}")
    assert page.is_success
    body = page.json()
    # The question and one line are sufficient. No alias, receipts or arbitrary source URL.
    assert body["line"]["id"] == str(line.id)
    serialized = page.text
    for private in ("Synthetic acceptance", "SYNTHETIC-USD-PRIOR", str(actor.user_id)):
        assert private not in serialized
    assert "token_sha256" not in serialized and "storage_key" not in serialized
    assert "document_id" not in serialized
    outsider = {"X-Demo-User-Id": str(other_payer.id)}
    assert (
        client.get(f"/api/cases/{case.id}/provider-workflow", headers=outsider).status_code == 403
    )
    response = _response(client, link["token"])
    assert (
        client.get(
            f"/api/provider-responses/{response['id']}/preview", headers=outsider
        ).status_code
        == 403
    )


def test_legacy_mutations_cannot_skip_pending_provider_decision(client, db, actor, headers):
    case, _, line, flag = _case(db, actor)
    link = _link(client, headers, line, flag)
    response = _response(client, link["token"])
    before = svc.get_buckets(db, case)
    assert (
        client.post(
            f"/api/line-items/{line.id}/accept", headers=headers, json={"note": "Skip review"}
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/flags/{flag.id}/status",
            headers=headers,
            json={"status": "RESOLVED", "note": "Skip review"},
        ).status_code
        == 409
    )
    assert svc.get_buckets(db, case) == before
    assert _preview(client, headers, response)["can_accept"] is True


def test_private_source_preview_requires_case_payer_and_security_headers(
    client, db, actor, headers, other_payer, storage
):
    case, _, _, _ = _case(db, actor)
    content = render(FIXTURES_BY_NAME["clean_bill"])
    key = storage.new_key(case.id)
    storage.put(key, content)
    document = EvidenceDocument(
        case_id=case.id,
        document_type=DocumentType.BILL,
        storage_key=key,
        sha256=sha256(content).hexdigest(),
        mime_type="application/pdf",
        file_size=len(content),
        page_count=2,
        source_type=DataSource.MANUAL_ENTRY,
        uploaded_by=actor.user_id,
        uploaded_by_role=UserRole.PAYER,
    )
    db.add(document)
    db.commit()
    endpoint = f"/api/documents/{document.id}/content"
    assert client.get(endpoint).status_code == 403
    assert client.get(endpoint, headers={"X-Demo-User-Id": str(other_payer.id)}).status_code == 403
    response = client.get(endpoint, headers=headers)
    assert response.status_code == 200 and response.content == content
    assert response.headers["content-type"] == "application/pdf"
    assert "no-store" in response.headers["cache-control"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "sandbox" in response.headers["content-security-policy"]
    storage.discard(key)
    missing = client.get(endpoint, headers=headers)
    assert missing.status_code == 404 and key not in missing.text
