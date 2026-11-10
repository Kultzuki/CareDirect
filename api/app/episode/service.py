"""Episode review with explicit, fingerprinted AI requests and ledger-derived totals."""

import hashlib
import json
from dataclasses import asdict

from sqlalchemy import select

from app import services as svc
from app.episode.deepseek import DeepSeekClient
from app.episode.overlap import analyze_episode_overlaps
from app.episode.records import assess_affinity, load_episode_records
from app.episode.timeline import reconstruct_timeline
from app.models import AuditEvent, CareCase
from app.money import to_str
from app.reconciliation.semantic import evidence_fingerprint
from app.schemas import (
    CareEpisodeOut,
    EpisodeDocumentOut,
    EpisodeOverlapOut,
    EpisodeTimelineEventOut,
)


def get_care_episode(db, case_id, *, analyze=False, actor=None, expected_fingerprint=None):
    case = db.get(CareCase, case_id)
    if case is None:
        raise svc.NotFound(f"case {case_id} not found")
    records = assess_affinity(load_episode_records(db, case), case.currency)
    overlap = analyze_episode_overlaps(db, case, records)
    documents = [EpisodeDocumentOut.model_validate(doc) for doc in records]
    timeline = [
        EpisodeTimelineEventOut.model_validate(asdict(event))
        for event in reconstruct_timeline(db, case, records)
    ]
    overlaps = [
        EpisodeOverlapOut(
            overlap_type=f.overlap_type,
            title=f.title,
            description=f.description,
            amount=to_str(f.amount),
            currency=f.currency,
            involved_document_ids=list(f.involved_document_ids),
            line_item_ids=list(f.line_item_ids),
            sources=list(f.sources),
        )
        for f in overlap.overlaps
    ]
    case_data = dict(
        case_id=str(case.id),
        patient_alias=case.patient_alias,
        episode_title=case.episode_title,
        clinical_context=case.clinical_context,
        currency=case.currency,
    )
    packet = dict(
        case_data=case_data,
        documents=[d.model_dump(mode="json") for d in documents],
        timeline_events=[t.model_dump(mode="json") for t in timeline],
        overlaps=[o.model_dump(mode="json") for o in overlaps],
    )
    client = DeepSeekClient()
    versioned = dict(
        evidence=dict(case_data=case_data, billing_evidence=evidence_fingerprint(records)),
        model=client.model,
        endpoint=client.base_url,
        thinking=client.thinking,
        schema_version="episode-v3-services",
    )
    fingerprint = hashlib.sha256(json.dumps(versioned, sort_keys=True).encode()).hexdigest()
    if expected_fingerprint is not None and expected_fingerprint != fingerprint:
        raise svc.DomainError("Episode evidence changed. Refresh before requesting analysis.")
    previous = db.scalar(
        select(AuditEvent)
        .where(
            AuditEvent.case_id == case.id,
            AuditEvent.event_type == "EPISODE_ANALYZED",
        )
        .order_by(AuditEvent.seq.desc())
        .limit(1)
    )
    cached = previous.details if previous else {}
    fresh = cached.get("input_fingerprint") == fingerprint
    insights = cached.get("insights") if fresh else None
    if not isinstance(insights, dict) or (analyze and insights.get("provider") != "deepseek"):
        # GET is always local. Browsing never dispatches or silently retries a provider request.
        if analyze:
            if actor is None:
                raise svc.Forbidden("an actor is required for episode analysis")
            svc._require_reviewer(case, actor)
            # Minimize external data: no source snippets, private file URLs or raw document bytes.
            minimized = [
                dict(
                    id=d["id"],
                    document_type=d["document_type"],
                    provider=d["provider"],
                    currency=d["currency"],
                    patient_reference=d["patient_reference"],
                    date=d["date"],
                    review_state=d["review_state"],
                    affinity_status=d["affinity_status"],
                    lines=[{k: v for k, v in li.items() if k != "sources"} for li in d["lines"]],
                )
                for d in packet["documents"]
            ]
            insights = client.analyze_episode(
                case_data,
                minimized,
                [{k: v for k, v in t.items() if k != "sources"} for t in packet["timeline_events"]],
                [{k: v for k, v in o.items() if k != "sources"} for o in packet["overlaps"]],
            )
            if insights.get("provider") == "deepseek":
                svc._audit(
                    db,
                    actor,
                    case_id=case.id,
                    event_type="DUPLICATE_SERVICES_ANALYZED",
                    entity_type="care_case",
                    entity_id=case.id,
                    details=dict(
                        input_fingerprint=evidence_fingerprint(records),
                        suggestions=insights.get("service_matches", []),
                        provider=insights["provider"],
                        model=client.model,
                    ),
                )
                db.flush()
            # Deterministic conflicts cannot be overridden by model optimism.
            if any(d.affinity_status == "conflict" for d in documents):
                insights["belongs_together"] = False
                insights["affinity_explanation"] = (
                    "Conflicting document evidence requires payer review."
                )
            svc._audit(
                db,
                actor,
                case_id=case.id,
                event_type="EPISODE_ANALYZED",
                entity_type="care_case",
                entity_id=case.id,
                details=dict(input_fingerprint=fingerprint, insights=insights),
            )
            db.flush()
            if insights.get("provider") == "deepseek":
                # Return current backend-checked matches in the POST response as well as GET.
                return get_care_episode(db, case_id)
        else:
            insights = client._heuristic_analysis(**packet)
            if previous and not fresh:
                insights["analysis_status"] = "stale"
    buckets = svc.get_buckets(db, case)
    warnings = [
        "Evidence totals can include summary and component bills. Overlaps are not deductions.",
        "Recorded net and payable amounts come only from the ledger and reconciliation workflow.",
    ]
    if any(d.affinity_status == "conflict" for d in documents):
        warnings.append(
            "Conflicting patient references or currencies need review before accepting membership."
        )
    if any(d.review_state in ("needs_review", "awaiting_extraction") for d in documents):
        warnings.append(
            "Some records await extraction or field review; episode analysis is incomplete."
        )
    if any(d.amount is None for d in documents if d.document_type == "BILL"):
        warnings.append("Some bill amounts are missing; the evidence total is incomplete.")
    if any(d.is_synthetic for d in documents):
        warnings.append("This episode includes synthetic/demo evidence.")
    return CareEpisodeOut(
        case_id=case.id,
        case_reference=case.case_reference,
        patient_alias=case.patient_alias,
        episode_title=case.episode_title or f"Care Episode: {case.patient_alias}",
        clinical_context=case.clinical_context,
        currency=case.currency,
        total_billed=to_str(overlap.gross_billed),
        overlap_deductions="0.00",
        potential_overlap_amount=to_str(overlap.overlap_amount),
        net_episode_total=to_str(buckets.net_bill_total),
        recorded_bill_total=to_str(buckets.original_bill_total),
        confirmed_adjustments=to_str(buckets.adjustments),
        payable_now=to_str(buckets.payable_now),
        queried=to_str(buckets.queried),
        already_paid=to_str(buckets.already_paid),
        documents=documents,
        timeline=timeline,
        overlaps=overlaps,
        ai_insights=insights,
        blockers=svc.approval_blockers(db, case),
        warnings=warnings,
        input_fingerprint=fingerprint,
        ai_configured=client.is_configured,
    )
