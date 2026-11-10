"""Advisory service matching; model equivalence never establishes a duplicate."""

import hashlib
import json
from decimal import Decimal
from itertools import combinations

from sqlalchemy import select

from app.models import AuditEvent
from app.reconciliation.views import normalize_text

# A deliberately small, transparent fallback, not a claim of model analysis.
ALIASES = {
    "cbc": "blood_count",
    "cbc test": "blood_count",
    "complete blood count": "blood_count",
    "complete blood count cbc": "blood_count",
    "haemogram": "blood_count",
    "hemogram": "blood_count",
}


def evidence_fingerprint(records):
    """Only current billing evidence, independent of flags, timeline and model advice."""
    evidence = [
        {
            k: doc.get(k)
            for k in (
                "id",
                "document_type",
                "currency",
                "provider",
                "patient_reference",
                "date",
                "review_state",
                "affinity_status",
                "lines",
            )
        }
        for doc in sorted(records, key=lambda d: d["id"])
    ]
    return hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest()


def saved_suggestions(db, case, records):
    if db is None:
        return []
    event = db.scalar(
        select(AuditEvent)
        .where(
            AuditEvent.case_id == case.id,
            AuditEvent.event_type == "DUPLICATE_SERVICES_ANALYZED",
        )
        .order_by(AuditEvent.seq.desc())
        .limit(1)
    )
    if event and event.details.get("input_fingerprint") == evidence_fingerprint(records):
        return event.details.get("suggestions", [])
    return []


def eligible_documents(records, currency):
    return [
        d
        for d in records
        if d["document_type"] == "BILL"
        and d["currency"] == currency
        and d.get("provider")
        and d.get("affinity_status") != "conflict"
        and d["review_state"] in ("recorded", "extracted")
    ]


def near_pairs(records, currency, suggestions=()):
    """Require same provider/date/quantity, compatible codes and reviewed context.

    Missing or differing codes are disclosed or rejected respectively. Prices may
    differ: they are evidence for the reviewer, never arithmetic supplied by AI.
    """
    entries = [
        (doc, li)
        for doc in eligible_documents(records, currency)
        for li in doc["lines"]
        if li.get("description")
    ]
    entries.sort(key=lambda entry: (entry[0]["id"], entry[1]["line_number"], entry[1]["id"]))
    proposed = {tuple(sorted((s["left_line_id"], s["right_line_id"]))) for s in suggestions}
    for (left_doc, left), (right_doc, right) in combinations(entries, 2):
        a, b = normalize_text(left["description"]), normalize_text(right["description"])
        if a == b:
            continue  # Exact rules own identical descriptions.
        pair = tuple(sorted((left["id"], right["id"])))
        alias = ALIASES.get(a) is not None and ALIASES.get(a) == ALIASES.get(b)
        if not alias and pair not in proposed:
            continue
        if normalize_text(left_doc["provider"]) != normalize_text(right_doc["provider"]):
            continue
        if not left.get("service_date") or left["service_date"] != right.get("service_date"):
            continue
        if left.get("quantity") is None or right.get("quantity") is None:
            continue
        if Decimal(left["quantity"]) <= 0 or Decimal(left["quantity"]) != Decimal(
            right["quantity"]
        ):
            continue
        codes = [normalize_text(li.get("code")) for li in (left, right)]
        if all(codes) and codes[0] != codes[1]:
            continue
        if any(li.get("line_total") is None for li in (left, right)):
            continue
        yield (
            left_doc,
            left,
            right_doc,
            right,
            ("Local service-name alias" if alias else "AI-proposed service equivalence"),
            ("Service codes agree." if all(codes) else "Service code evidence is incomplete."),
        )
