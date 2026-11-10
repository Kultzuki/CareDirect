"""Private, explicit export projections. Never serialize arbitrary ORM columns/audits."""

from __future__ import annotations

import html
import json
import re
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from sqlalchemy import select

from app import services as svc
from app.api.cases import _buckets, _summary
from app.models import (
    ApprovalRecord,
    CareCase,
    DocumentExtraction,
    EvidenceDocument,
    ExtractionRevision,
    PaymentOperation,
    PayPalInvoiceRef,
    PayPalPaymentRef,
    ProviderDecision,
    ProviderLink,
    ProviderResponse,
)
from app.money import ZERO, to_str

PROVENANCE = (
    "Synthetic/demo data where marked; extraction remains recorded-output mock. "
    "Private evidence, not proof of medical necessity or receipt authenticity."
)
_URL = re.compile(
    r"(?:https?://|(?:/api/)?(?:uploads?|provider/respond)/|"
    r"/api/documents/|/cases/[^\s/]+/documents/)[^\s<>\"']+",
    re.I,
)
_CAPABILITY = re.compile(r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{43}(?![A-Za-z0-9_-])")


def safe(value):
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (datetime, UUID)):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {k: safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe(v) for v in value]
    if isinstance(value, str):
        return _CAPABILITY.sub(
            "[private capability omitted]", _URL.sub("[private link omitted]", value)
        )
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def project(row, fields):
    return {key: safe(getattr(row, key)) for key in fields.split()}


def rows(db, cls, case_id):
    return db.scalars(select(cls).where(cls.case_id == case_id)).all()


def document_ref(value):
    """Export source references only as UUIDs, never private paths or URLs."""
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        return None


def basis_projection(value):
    value = value or {}
    result = {
        key: safe(value.get(key))
        for key in (
            "confidence",
            "limitations",
            "kind",
            "expected",
            "printed",
            "line_numbers",
            "first_line_id",
            "repeat_line_ids",
            "estimate_document_ids",
            "estimate_document_id",
            "estimate_confidence",
            "amount_basis",
            "rule_id",
            "rule_version",
            "label",
            "basis",
            "problems",
            "bill_id",
            "bill_link",
            "payer_note",
        )
        if key in value
    }
    result["source_document_id"] = document_ref(value.get("source_document_ref"))
    result["sources"] = [
        {
            "line_id": safe(source.get("line_id")),
            "document_id": document_ref(source.get("source_document_ref")),
            "page": safe(source.get("page")),
            "snippet": safe(source.get("snippet")),
        }
        for source in value.get("sources", [])
        if isinstance(source, dict)
    ]
    result["item_changes"] = [
        {
            key: safe(change.get(key))
            for key in ("description", "code", "estimate", "bill", "difference")
        }
        for change in value.get("item_changes", [])
        if isinstance(change, dict)
    ]
    result["estimate_sources"] = [
        {
            "path": safe(source.get("path")),
            "source": {
                key: safe((source.get("source") or {}).get(key))
                for key in ("document_id", "page", "snippet", "bbox")
            },
        }
        for source in value.get("estimate_sources", [])
        if isinstance(source, dict)
    ]
    return result


def dashboard(db, actor):
    from app.extraction.service import _promoted_to
    from app.family import visible_case_ids

    # A dashboard is a personal workspace, including for an administrator.
    cases = db.scalars(
        select(CareCase).where(visible_case_ids(actor)).order_by(CareCase.created_at.desc())
    ).all()
    totals, items = {}, []
    for case in cases:
        item = _summary(db, case).model_dump(mode="json")
        flags = svc.case_flags(db, case.id)
        questions = rows(db, ProviderLink, case.id)
        responses = rows(db, ProviderResponse, case.id)
        decisions = {d.response_id for d in rows(db, ProviderDecision, case.id)}
        from app.extraction.service import _load
        from app.insurance import INSURANCE_TYPES

        def needs_review(doc):
            if doc.document_type in INSURANCE_TYPES:
                extraction = db.scalar(
                    select(DocumentExtraction).where(DocumentExtraction.document_id == doc.id)
                )
                return extraction is None or any(
                    f.needs_review for f in _load(db, extraction).fields
                )
            return doc.document_type != "ESTIMATE" and _promoted_to(db, doc) is None

        documents_to_review = sum(needs_review(doc) for doc in rows(db, EvidenceDocument, case.id))
        pending_responses = sum(r.id not in decisions for r in responses)
        pending_lines = sum(line.status == "PENDING_REVIEW" for line in svc.case_lines(db, case.id))
        activity = svc.case_audit(db, case.id)
        latest = max(activity, key=lambda a: a.seq) if activity else None
        op = db.scalar(select(PaymentOperation).where(PaymentOperation.case_id == case.id))
        item.update(
            provider_name=", ".join(dict.fromkeys(b.provider_name for b in case.bills))
            or "Provider not supplied",
            provider_names=list(dict.fromkeys(b.provider_name for b in case.bills)),
            open_questions=sum(str(f.status) not in ("RESOLVED", "DISMISSED") for f in flags)
            + sum(
                line.status == "QUERIED"
                and not any(
                    str(line.id) in f.line_item_ids
                    and str(f.status) not in ("RESOLVED", "DISMISSED")
                    for f in flags
                )
                for line in svc.case_lines(db, case.id)
            ),
            active_provider_links=sum(q.state == "ACTIVE" for q in questions),
            pending_responses=pending_responses,
            documents_to_review=documents_to_review,
            attention_count=(
                sum(f.status == "OPEN" for f in flags)
                + pending_responses
                + pending_lines
                + documents_to_review
            ),
            payment_state=("UNCERTAIN" if op.state == "CREATING" else op.state)
            if op
            else "NOT_STARTED",
            latest_activity=project(latest, "event_type actor_label created_at")
            if latest
            else None,
            latest_activity_at=safe(latest.created_at) if latest else None,
        )
        items.append(safe(item))
        group = totals.setdefault(
            case.currency,
            {
                key: ZERO
                for key in (
                    "payable_now",
                    "queried",
                    "already_paid",
                    "pending_review",
                    "net_bill_total",
                )
            },
        )
        for key in group:
            group[key] += Decimal(item["buckets"][key])
    return {
        "cases": items,
        "totals": [
            {"currency": currency, **{k: to_str(v) for k, v in values.items()}}
            for currency, values in sorted(totals.items())
        ],
        "generated_at": datetime.now(UTC).isoformat(),
        "provenance": PROVENANCE,
    }


def pack(db, actor, case_id):
    case = svc.get_case(db, case_id)
    svc._require_case_member(case, actor)
    result = {
        "schema_version": "caredirect.evidence.v1",
        "provenance": PROVENANCE,
        "exported_at": datetime.now(UTC).isoformat(),
        "case": project(
            case,
            "id case_reference patient_alias currency status is_demo created_at "
            "episode_title clinical_context",
        ),
        "buckets": _buckets(db, case).model_dump(mode="json"),
        "documents": [
            project(
                r,
                "id document_type sha256 mime_type file_size page_count source_type "
                "extraction_status uploaded_by_role created_at",
            )
            for r in rows(db, EvidenceDocument, case_id)
        ],
        "extractions": [],
        "revisions": [],
        "bills": [
            project(
                r,
                "id provider_name bill_number bill_date currency printed_total "
                "printed_advance_paid printed_balance_due source_type created_at",
            )
            for r in case.bills
        ],
        "lines": [
            project(
                r,
                "id bill_id line_number code description_raw service_date quantity unit_price "
                "line_total recognized_amount currency source_type extraction_confidence "
                "source_page source_text status status_note created_at",
            )
            for r in svc.case_lines(db, case_id)
        ],
        "flags": [
            project(
                r,
                "id flag_type line_item_ids amount_involved explanation rule_id rule_version "
                "status resolution_note resolved_at created_at",
            )
            for r in svc.case_flags(db, case_id)
        ],
        "questions": [
            project(
                r,
                "id flag_id line_item_id question issued_amount expires_at consumed_at "
                "revoked_at created_at",
            )
            for r in rows(db, ProviderLink, case_id)
        ],
        "provider_responses": [
            project(
                r,
                "id flag_id line_item_id provider_link_id response_type response_text "
                "corrected_amount currency supporting_document_id responder_label "
                "actor_verification_method responded_at",
            )
            for r in rows(db, ProviderResponse, case_id)
        ],
        "payer_decisions": [
            project(
                r,
                "id response_id line_item_id decision note original_amount previous_amount "
                "recognized_amount adjustment currency state_fingerprint actor_label created_at",
            )
            for r in rows(db, ProviderDecision, case_id)
        ],
        "approvals": [],
        "external_payments": [
            project(
                r,
                "id bill_id method amount currency paid_on payee_name source_type "
                "extraction_confidence status status_note created_at",
            )
            for r in svc.case_payments(db, case_id)
        ],
        "paypal_invoices": [
            project(
                r,
                "id approval_id paypal_invoice_id currency invoice_total amount_due "
                "invoice_status last_verified_at created_at",
            )
            for r in rows(db, PayPalInvoiceRef, case_id)
        ],
        "paypal_payments": [
            project(
                r,
                "id invoice_ref_id paypal_transaction_id payment_source external_payment_id "
                "amount currency paypal_status verified_at created_at",
            )
            for r in rows(db, PayPalPaymentRef, case_id)
        ],
        "ledger": [
            project(
                r,
                "id seq entry_type amount currency bill_id line_item_id external_payment_id "
                "flag_id provider_decision_id paypal_payment_ref_id reason actor_label "
                "created_at",
            )
            for r in svc.case_ledger(db, case_id)
        ],
        "activity": [
            project(
                r, "id seq actor_label event_type entity_type entity_id ledger_entry_id created_at"
            )
            for r in svc.case_audit(db, case_id)
        ],
    }
    for item, row in zip(result["flags"], svc.case_flags(db, case_id), strict=True):
        item["evidence"] = basis_projection(row.evidence)
    for item, row in zip(result["external_payments"], svc.case_payments(db, case_id), strict=True):
        item["source_document_id"] = document_ref(row.source_document_ref)
        item["match_basis"] = basis_projection(row.match_basis)
    # Payload was already validated through the strict versioned extraction schema.
    # Revalidate before export to prevent historical/DB-added arbitrary key leakage.
    from app.extraction.schema import ExtractionV1

    for r in rows(db, DocumentExtraction, case_id):
        extraction = project(
            r, "id document_id schema_version provider model prompt_version actor_label created_at"
        )
        extraction["payload"] = safe(ExtractionV1.model_validate(r.payload).model_dump(mode="json"))
        result["extractions"].append(extraction)
    for r in rows(db, ExtractionRevision, case_id):
        revision = project(
            r, "id extraction_id revision_number confirmed_paths reason actor_label created_at"
        )
        revision["corrections"] = [
            {
                **{key: safe(c.get(key)) for key in ("path", "value")},
                "source": {
                    key: safe((c.get("source") or {}).get(key))
                    for key in ("page", "snippet", "bbox")
                }
                if c.get("source")
                else None,
            }
            for c in r.corrections
        ]
        result["revisions"].append(revision)
    for r in rows(db, ApprovalRecord, case_id):
        approval = project(
            r,
            "id approved_by actor_label currency approved_amount bill_total payable_now queried "
            "already_paid payee_label state_fingerprint purpose ledger_seq created_at",
        )
        composition = r.composition or {}
        approval["composition"] = {
            key: safe(composition.get(key))
            for key in (
                "currency",
                "invoice_total",
                "external_total",
                "collect_amount",
                "queried",
                "provider_label",
                "state_fingerprint",
            )
        }
        approval["composition"]["external_payments"] = [
            {
                key: safe(p.get(key))
                for key in ("id", "amount", "currency", "paid_on", "reference_suffix")
            }
            for p in composition.get("external_payments", [])
        ]
        account = composition.get("account_binding", {})
        approval["account_binding"] = {
            key: safe(account.get(key)) for key in ("status", "basis", "merchant_ref_suffix")
        }
        approval["account_binding"]["merchant_ref_suffix"] = (
            r.account_binding.get("merchant_ref", "")[-4:] if r.account_binding else None
        )
        result["approvals"].append(approval)
    from app.family import workspace as family_workspace
    from app.insurance import has_insurance, reconcile

    shared = family_workspace(db, actor, case.id)
    result["family_finances"] = {
        key: shared[key]
        for key in (
            "currency",
            "total_contributions",
            "members",
            "ledger",
            "expenses",
            "allocation_history",
        )
    }

    if has_insurance(db, case.id):
        comparison = reconcile(db, case)
        result["insurance_reconciliation"] = {
            key: comparison[key]
            for key in (
                "currency",
                "selection",
                "hospital_total",
                "hospital_stated_total",
                "itemized_total",
                "preauthorized",
                "components",
                "insurer_paid",
                "approved_unpaid",
                "family_paid",
                "patient_share",
                "known_patient_subtotal",
                "patient_balance",
                "family_overpayment",
                "unexplained",
                "issues",
                "warnings",
                "facts",
                "reviewed",
                "review_stale",
                "review_note",
            )
        }
    return safe(result)


def as_html(payload):
    """Standalone readable document; escaped data only, no links or active content."""

    def label(value):
        return html.escape(str(value).replace("_", " ").capitalize())

    def render(value, key=""):
        if key == "payload":
            return (
                "<details><summary>Original recorded extraction fields</summary><pre>"
                + html.escape(json.dumps(value, indent=2, ensure_ascii=False))
                + "</pre></details>"
            )
        if isinstance(value, dict):
            return (
                "<dl>"
                + "".join(
                    "<div><dt>" + label(k) + "</dt><dd>" + render(v, k) + "</dd></div>"
                    for k, v in value.items()
                )
                + "</dl>"
            )
        if isinstance(value, list):
            if not value:
                return "<p>No records</p>"
            return "<ol>" + "".join("<li>" + render(v) + "</li>" for v in value) + "</ol>"
        return html.escape(str(value)) if value is not None else "Not recorded"

    sections = []
    for name, value in payload.items():
        content = render(value)
        sections.append(
            "<section><h2>"
            + html.escape(name.replace("_", " ").capitalize())
            + "</h2>"
            + content
            + "</section>"
        )
    return (
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>CareDirect private evidence</title><style>"
        "body{font:16px/1.6 system-ui,sans-serif;max-width:80ch;margin:2rem auto;"
        "padding:0 1rem;color:#12303a}section{border-top:1px solid #78908c;margin-top:2rem}"
        "pre{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.6 ui-monospace,monospace}"
        "dl{margin:0}dl>div{padding:.4rem 0;border-bottom:1px solid #d5dedb;"
        "display:grid;grid-template-columns:minmax(8rem,1fr) minmax(0,3fr);gap:1rem}"
        "dt{font-weight:600}dd{margin:0;overflow-wrap:anywhere}li{margin:1rem 0}"
        "@media(max-width:36rem){dl>div{display:block}dd{margin-top:.25rem}}"
        "h1,h2{line-height:1.2}</style><body><h1>CareDirect private evidence</h1>"
        + "".join(sections)
        + "</body></html>"
    )
