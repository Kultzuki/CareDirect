"""Synthetic insurance evidence: allocations are not payment credits or adjudication."""

import json
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import select

from app import services as svc
from app.extraction.adapter import get_extraction_adapter
from app.insurance import Selection, reconcile
from app.main import app
from app.models import AuditEvent
from app.states import PaymentMethod
from tests.test_documents_api import make_link, upload
from tests.test_upload_validation import make_pdf


@pytest.fixture
def case(db, actor):
    case = svc.create_case(db, actor, patient_alias="Synthetic insurance patient", currency="INR")
    bill = svc.add_bill(
        db,
        actor,
        case.id,
        svc.BillInput(
            provider_name="Synthetic Hospital",
            currency="INR",
            bill_number="HOSP-80",
            bill_date=date(2026, 11, 9),
            printed_total=Decimal("80000"),
            lines=[
                svc.LineInput(
                    1,
                    "Hospital services",
                    Decimal("80000"),
                    date(2026, 11, 9),
                    quantity=Decimal("1"),
                    unit_price=Decimal("80000"),
                )
            ],
        ),
    )
    svc.accept_line(db, actor, bill.line_items[0].id)
    return case


def document(client, headers, case, kind="INSURANCE_SETTLEMENT", *, confirm=True, **values):
    defaults = dict(
        claim_reference="CLAIM-1", bill_reference="HOSP-80", insurer_name="Demo insurer"
    )
    if kind == "INSURANCE_SETTLEMENT":
        defaults.update(
            claimed_total="80000.00",
            approved_amount="55000.00",
            copay="5000.00",
            deductible="0.00",
            noncovered="10000.00",
            pending="10000.00",
            rejected="0.00",
            stated_reason=(
                "Non-covered consumables: 10000.00. Co-pay: 5000.00. Pending review: 10000.00."
            ),
        )
    defaults.update(values)
    if kind == "INSURER_PAYMENT":
        defaults.setdefault("payment_recipient", "Synthetic Hospital")
    link = make_link(client, headers, case.id, (kind,))
    uploaded = upload(
        client, link["token"], make_pdf(1) + str(uuid4()).encode(), document_type=kind
    )
    assert uploaded.status_code == 201, uploaded.text
    doc_id = uploaded.json()["document_id"]

    def field(value, label):
        return (
            dict(
                value=value,
                confidence="0.990",
                source=dict(document_id=doc_id, page=1, snippet=f"{label}: {value}"),
            )
            if value is not None
            else dict(value=None)
        )

    class Adapter:
        provider = "mock"
        model = "synthetic-insurance"
        prompt_version = "test-v1"

        def extract(self, **kwargs):
            return dict(
                schema_version="caredirect.extraction.v1",
                document_id=doc_id,
                document_type=kind,
                provider_name=field("Synthetic Hospital", "Hospital"),
                provider_identifier=field(None, ""),
                patient_reference=field(None, ""),
                invoice_number=field(None, ""),
                invoice_date=field("2026-11-09", "Date"),
                currency=field("INR", "Currency"),
                line_items=[],
                subtotal=field(None, ""),
                tax_total=field(None, ""),
                total=field(None, ""),
                advance_paid=field(None, ""),
                receipt=None,
                insurance={k: field(v, k) for k, v in defaults.items()},
            )

    app.dependency_overrides[get_extraction_adapter] = Adapter
    response = client.post(f"/api/documents/{doc_id}/extract", headers=headers)
    assert response.status_code == 201, response.text
    view = response.json()
    assert all(f["needs_review"] for f in view["fields"] if f["value"] is not None)
    if confirm:
        response = client.post(
            f"/api/extractions/{view['id']}/revisions",
            headers=headers,
            json=dict(
                corrections=[],
                confirmed_paths=[f["path"] for f in view["fields"] if f["value"] is not None],
                reason="Compared every populated field with the synthetic source.",
            ),
        )
        assert response.status_code == 201, response.text
    return doc_id, view


def get(client, headers, case):
    response = client.get(f"/api/cases/{case.id}/insurance", headers=headers)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    return response.json()


def test_example_keeps_patient_pending_and_approved_separate_and_preserves_ledger(
    db, actor, case, client, headers
):
    before = len(svc.case_ledger(db, case.id))
    document(client, headers, case)
    result = get(client, headers, case)
    assert result["hospital_total"] == "80000.00"
    assert result["patient_share"] == result["patient_balance"] == "15000.00"
    assert result["family_paid"] == "0.00"
    assert result["insurer_paid"] is None
    assert result["unexplained"] == "0.00" and not result["issues"]
    assert not result["reviewed"]
    response = client.post(
        f"/api/cases/{case.id}/insurance/review",
        headers=headers,
        json=dict(
            selection=result["selection"],
            input_fingerprint=result["input_fingerprint"],
            note="Confirmed claim membership and disjoint categories.",
        ),
    )
    assert response.status_code == 200, response.text
    assert response.json()["reviewed"]
    assert len(svc.case_ledger(db, case.id)) == before
    assert svc.get_buckets(db, case).bill_total == Decimal("80000")
    assert any("gross-bill collection" in issue for issue in svc.approval_blockers(db, case))
    detail = client.get(f"/api/cases/{case.id}", headers=headers).json()
    assert detail["buckets"]["insurance_present"]


def test_paid_insurer_and_family_are_compared_without_double_credit(
    db, actor, case, client, headers
):
    document(client, headers, case)
    document(
        client,
        headers,
        case,
        "INSURER_PAYMENT",
        insurer_paid="40000.00",
        payment_reference="REMIT-1",
        paid_on="2026-11-09",
    )
    payment = svc.record_external_payment(
        db,
        actor,
        case.id,
        svc.PaymentInput(
            method=PaymentMethod.CASH,
            amount=Decimal("5000"),
            currency="INR",
            paid_on=date(2026, 11, 9),
            bill_id=case.bills[0].id,
            payee_name="Synthetic Hospital",
        ),
    )
    svc.reconcile_external_payment(db, actor, payment.id)
    svc.confirm_external_payment(db, actor, payment.id, "Verified synthetic family cash receipt.")
    result = get(client, headers, case)
    assert result["insurer_paid"] == "40000.00"
    assert result["approved_unpaid"] == "15000.00"
    assert result["family_paid"] == "5000.00"
    assert result["patient_balance"] == "10000.00"
    assert svc.get_buckets(db, case).already_paid == Decimal("5000")


def test_preauthorisation_not_used_as_final_settlement(case, client, headers):
    document(client, headers, case, "INSURANCE_PREAUTH", approved_amount="60000.00")
    result = get(client, headers, case)
    assert result["preauthorized"] == "60000.00"
    assert result["patient_balance"] is None
    assert any("final settlement" in text for text in result["issues"])


@pytest.mark.parametrize(
    "changes,expected",
    [
        (dict(deductible=None), "not stated"),
        (dict(approved_amount="54000.00"), "do not reconcile"),
        (dict(copay="-1.00"), "negative"),
        (dict(bill_reference="DIFFERENT"), "different hospital bill"),
    ],
)
def test_unknown_conflicting_or_overlapping_components_do_not_produce_payable(
    case, client, headers, changes, expected
):
    document(client, headers, case, **changes)
    result = get(client, headers, case)
    assert result["patient_balance"] is None
    assert any(expected in issue for issue in result["issues"])


def test_rejected_claim_is_not_assigned_to_patient(case, client, headers):
    document(client, headers, case, pending="0.00", rejected="10000.00")
    result = get(client, headers, case)
    assert result["patient_balance"] == "15000.00"
    assert next(c["amount"] for c in result["components"] if c["key"] == "rejected") == "10000.00"


def test_duplicate_remittances_and_conflicting_claims_are_flagged(case, client, headers):
    document(client, headers, case)
    for claim in ("CLAIM-1", "OTHER-CLAIM"):
        document(
            client,
            headers,
            case,
            "INSURER_PAYMENT",
            insurer_paid="10000.00",
            payment_reference="SAME-REF",
            paid_on="2026-11-09",
            claim_reference=claim,
        )
    result = get(client, headers, case)
    assert any("Duplicate insurer" in issue for issue in result["issues"])
    assert any("conflicting claim" in issue for issue in result["issues"])
    assert result["patient_balance"] is None


def test_reviews_stale_on_corrected_evidence_and_reject_stale_forms(case, client, headers):
    _, view = document(client, headers, case)
    result = get(client, headers, case)
    body = dict(
        selection=result["selection"],
        input_fingerprint=result["input_fingerprint"],
        note="Reviewed synthetic claim.",
    )
    assert (
        client.post(
            f"/api/cases/{case.id}/insurance/review", headers=headers, json=body
        ).status_code
        == 200
    )
    response = client.post(
        f"/api/extractions/{view['id']}/revisions",
        headers=headers,
        json=dict(
            corrections=[dict(path="insurance.stated_reason", value="Corrected stated reason.")],
            confirmed_paths=[],
            reason="Source clarification.",
        ),
    )
    assert response.status_code == 201, response.text
    assert get(client, headers, case)["review_stale"]
    assert (
        client.post(
            f"/api/cases/{case.id}/insurance/review", headers=headers, json=body
        ).status_code
        == 409
    )
    body.pop("note")
    assert (
        client.post(
            f"/api/cases/{case.id}/insurance/explain", headers=headers, json=body
        ).status_code
        == 409
    )


def test_explanations_use_exact_arithmetic_and_existing_reasons_only(case, client, headers, db):
    document(client, headers, case)
    result = get(client, headers, case)
    with patch("httpx.Client.post", side_effect=AssertionError("No model on GET")):
        get(client, headers, case)
    response = client.post(
        f"/api/cases/{case.id}/insurance/explain",
        headers=headers,
        json=dict(selection=result["selection"], input_fingerprint=result["input_fingerprint"]),
    )
    assert response.status_code == 200, response.text
    explanation = response.json()
    assert explanation["coverage_gap"] == "25000.00"
    assert explanation["status"] == "local_evidence"
    assert explanation["evidence"][0]["source"]["page"] == 1
    assert "Non-covered consumables" in explanation["evidence"][0]["value"]
    assert db.scalar(select(AuditEvent).where(AuditEvent.event_type == "INSURANCE_EXPLAINED"))


@pytest.mark.parametrize("ids", [["foreign"], ["reason", "reason"], []])
def test_model_cannot_invent_sources_or_duplicate_facts(case, client, headers, ids):
    document(client, headers, case)
    result = get(client, headers, case)
    reason = next(f["id"] for f in result["facts"] if f["id"].endswith("insurance.stated_reason"))
    response = MagicMock()
    response.json.return_value = {
        "choices": [
            dict(
                finish_reason="stop",
                message=dict(
                    content=json.dumps(dict(fact_ids=[reason if i == "reason" else i for i in ids]))
                ),
            )
        ]
    }
    with (
        patch("app.insurance_explanation.DeepSeekClient") as factory,
        patch("app.insurance_explanation.httpx.Client") as transport,
    ):
        factory.return_value.is_configured = True
        factory.return_value.model = "fake"
        factory.return_value.base_url = "https://example.invalid"
        factory.return_value.api_key = "fake"
        transport.return_value.__enter__.return_value.post.return_value = response
        output = client.post(
            f"/api/cases/{case.id}/insurance/explain",
            headers=headers,
            json=dict(selection=result["selection"], input_fingerprint=result["input_fingerprint"]),
        )
    assert output.status_code == 200, output.text
    assert output.json()["status"] == "provider_unavailable"
    assert output.json()["evidence"][0]["id"] == reason


def test_unreviewed_extraction_requires_human_confirmation_and_never_promotes(
    case, client, headers
):
    _, view = document(client, headers, case, confirm=False)
    result = get(client, headers, case)
    assert any("Confirm all" in issue for issue in result["issues"])
    assert client.post(f"/api/extractions/{view['id']}/promote", headers=headers).status_code == 409
    assert (
        client.post(
            f"/api/cases/{case.id}/insurance/explain",
            headers=headers,
            json=dict(selection=result["selection"], input_fingerprint=result["input_fingerprint"]),
        ).status_code
        == 409
    )


def test_insurance_endpoints_are_case_scoped(case, client, headers, other_payer, db, actor):
    document(client, headers, case)
    result = get(client, headers, case)
    other = {"X-Demo-User-Id": str(other_payer.id)}
    assert client.get(f"/api/cases/{case.id}/insurance", headers=other).status_code == 403
    body = dict(selection=result["selection"], input_fingerprint=result["input_fingerprint"])
    for path in ("explain", "review"):
        data = {**body, "note": "Review"} if path == "review" else body
        assert (
            client.post(
                f"/api/cases/{case.id}/insurance/{path}", headers=other, json=data
            ).status_code
            == 403
        )
    with pytest.raises(svc.ValidationFailed):
        reconcile(db, case, Selection(bill_id=uuid4()))


@pytest.mark.parametrize(
    "values",
    [
        dict(payment_recipient="Other Hospital"),
        dict(paid_on=None),
        dict(payment_reference=None),
        dict(insurer_paid="0.00"),
    ],
)
def test_incomplete_or_wrong_recipient_remittance_stays_unknown(case, client, headers, values):
    document(client, headers, case)
    payment = dict(insurer_paid="10000.00", payment_reference="REMIT-1", paid_on="2026-11-09")
    payment.update(values)
    document(client, headers, case, "INSURER_PAYMENT", **payment)
    result = get(client, headers, case)
    assert result["insurer_paid"] is None
    assert result["patient_balance"] is None and result["issues"]


def test_successful_ai_evidence_selection_cached_without_money_or_source_invention(
    case, client, headers
):
    document(client, headers, case)
    result = get(client, headers, case)
    reason = next(f["id"] for f in result["facts"] if f["id"].endswith("insurance.stated_reason"))
    response = MagicMock()
    response.json.return_value = {
        "choices": [
            dict(finish_reason="stop", message=dict(content=json.dumps(dict(fact_ids=[reason]))))
        ]
    }
    with (
        patch("app.insurance_explanation.DeepSeekClient") as factory,
        patch("app.insurance_explanation.httpx.Client") as transport,
    ):
        factory.return_value.is_configured = True
        factory.return_value.model = "synthetic"
        factory.return_value.base_url = "https://example.invalid"
        factory.return_value.api_key = "fake"
        transport.return_value.__enter__.return_value.post.return_value = response
        body = dict(selection=result["selection"], input_fingerprint=result["input_fingerprint"])
        for _ in range(2):
            output = client.post(
                f"/api/cases/{case.id}/insurance/explain", headers=headers, json=body
            )
            assert output.status_code == 200, output.text
            assert output.json()["status"] == "model_evidence_selection"
            assert output.json()["evidence"][0]["id"] == reason
            assert output.json()["coverage_gap"] == "25000.00"
        assert transport.return_value.__enter__.return_value.post.call_count == 1


def test_insurance_export_and_dashboard_review_state(case, client, headers):
    document(client, headers, case)
    dashboard = client.get("/api/dashboard", headers=headers).json()
    own = next(item for item in dashboard["cases"] if item["id"] == str(case.id))
    assert own["documents_to_review"] == 0
    result = client.get(f"/api/cases/{case.id}/evidence?format=json", headers=headers)
    assert result.status_code == 200, result.text
    assert result.json()["insurance_reconciliation"]["patient_balance"] == "15000.00"
    assert "storage_key" not in result.text


def test_insurance_payment_preview_never_proposes_gross_family_collection(
    case, client, headers, db
):
    from app import payments
    from tests.test_payments import FakePayPal

    document(client, headers, case)
    preview = payments.preview(db, case, FakePayPal())
    assert preview["collect_amount"] == "0.00"
    assert preview["invoice_total"] == "15000.00"
    result = get(client, headers, case)
    client.post(
        f"/api/cases/{case.id}/insurance/review",
        headers=headers,
        json=dict(
            selection=result["selection"],
            input_fingerprint=result["input_fingerprint"],
            note="Reviewed.",
        ),
    )
    assert payments.preview(db, case, FakePayPal())["collect_amount"] == "15000.00"
    assert any(
        "gross-bill collection" in text for text in payments.blockers(db, case, FakePayPal())
    )


def test_pending_family_payment_does_not_overstate_collectible_balance(
    case, client, headers, db, actor
):
    document(client, headers, case)
    svc.record_external_payment(
        db,
        actor,
        case.id,
        svc.PaymentInput(
            method=PaymentMethod.CASH,
            amount=Decimal("5000"),
            currency="INR",
            paid_on=date(2026, 11, 9),
            bill_id=case.bills[0].id,
        ),
    )
    result = get(client, headers, case)
    assert result["family_paid"] == "0.00"  # Submitted evidence is not a confirmed credit.
    assert result["patient_balance"] is None
    assert any("awaits reconciliation" in issue for issue in result["issues"])
