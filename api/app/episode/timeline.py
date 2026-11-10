"""Evidence chronology. Document/service dates are distinct from recording dates."""

from dataclasses import dataclass

from sqlalchemy import select

from app import services as svc
from app.episode.records import category, iso_date, load_episode_records
from app.models import ProviderDecision, ProviderResponse
from app.money import to_str


@dataclass(frozen=True)
class TimelineItem:
    id: str
    event_date: str | None
    event_type: str
    title: str
    detail: str
    amount: str | None = None
    currency: str | None = None
    document_id: str | None = None
    flag_id: str | None = None
    status_tone: str = "neutral"
    date_basis: str = "recorded_at"
    sources: tuple[dict, ...] = ()


def reconstruct_timeline(db, case, records=None):
    records = load_episode_records(db, case) if records is None else records
    events = []
    for doc in records:
        if doc["source_available"]:
            events.append(
                TimelineItem(
                    id=f"upload-{doc['id']}",
                    event_date=doc["uploaded_at"],
                    event_type="UPLOAD",
                    title=f"{doc['name']} uploaded",
                    detail=f"Extraction: {doc['extraction_status']}.",
                    document_id=doc["id"],
                    date_basis="uploaded_at",
                )
            )
        kind = doc["document_type"]
        title = {
            "ESTIMATE": "Estimate dated",
            "BILL": "Bill dated",
            "RECEIPT": "Payment evidence dated",
        }.get(kind, "Supporting document dated")
        if kind == "RECEIPT":
            title = (
                "Reconciled advance/prior payment"
                if doc.get("payment_status") == "MATCHED"
                else "Unreconciled payment evidence"
            )
        events.append(
            TimelineItem(
                id=f"document-{doc['id']}",
                event_date=doc["date"],
                event_type=kind,
                title=f"{title}: {doc['provider'] or 'Provider not supplied'}",
                detail=f"Review: {doc['review_state']}. "
                "Document dates do not establish receipt or treatment completion.",
                amount=doc["amount"],
                currency=doc["currency"],
                document_id=doc["id"] if doc["source_available"] else None,
                date_basis=doc["date_basis"] if doc["date"] else "unknown",
                sources=tuple(doc["sources"]),
            )
        )
        if kind != "BILL":
            continue
        for line in doc["lines"]:
            events.append(
                TimelineItem(
                    id=f"service-{line['id']}",
                    event_date=line["service_date"],
                    event_type=category([line["description"] or ""]),
                    title=f"Service listed: {line['description'] or 'Description missing'}",
                    detail=f"Bill line {line['line_number']}; "
                    "service completion is not independently verified.",
                    amount=line["line_total"],
                    currency=doc["currency"],
                    document_id=doc["id"] if doc["source_available"] else None,
                    date_basis="service_date" if line["service_date"] else "unknown",
                    sources=tuple(line["sources"]),
                )
            )
    for flag in svc.case_flags(db, case.id):
        events.append(
            TimelineItem(
                id=f"flag-{flag.id}",
                event_date=iso_date(flag.created_at),
                event_type="DISCREPANCY",
                title=f"Billing question recorded: {str(flag.flag_type).replace('_', ' ').title()}",
                detail=flag.explanation + f" Current status: {flag.status}.",
                amount=to_str(flag.amount_involved),
                currency=case.currency,
                flag_id=str(flag.id),
                status_tone="warning"
                if str(flag.status) not in ("RESOLVED", "DISMISSED")
                else "neutral",
            )
        )
    for response in db.scalars(select(ProviderResponse).where(ProviderResponse.case_id == case.id)):
        events.append(
            TimelineItem(
                id=f"response-{response.id}",
                event_date=iso_date(response.responded_at),
                event_type="PROVIDER_RESPONSE",
                title=f"Provider response received: {response.response_type}",
                detail=response.response_text,
                amount=to_str(response.corrected_amount)
                if response.corrected_amount is not None
                else None,
                currency=response.currency,
                flag_id=str(response.flag_id),
                status_tone="info",
            )
        )
    for decision in db.scalars(select(ProviderDecision).where(ProviderDecision.case_id == case.id)):
        events.append(
            TimelineItem(
                id=f"decision-{decision.id}",
                event_date=iso_date(decision.created_at),
                event_type="RESOLUTION",
                title=f"Payer decision: {decision.decision}",
                detail=decision.note,
                amount=to_str(decision.adjustment),
                currency=decision.currency,
                status_tone="success" if str(decision.decision) == "ACCEPT" else "warning",
            )
        )
    return sorted(
        events, key=lambda item: (item.event_date is None, item.event_date or "", item.id)
    )
