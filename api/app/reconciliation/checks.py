"""Read-only rule discovery. These candidates never alter charges or the ledger."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Bill, BillingFlag, CareCase, DocumentExtraction, EvidenceDocument
from app.money import ZERO, to_str
from app.reconciliation import arithmetic, duplicates
from app.reconciliation.views import normalize_text
from app.states import DocumentType, FlagType


def _evidence(bill, lines):
    confidences = [li.extraction_confidence for li in lines if li.extraction_confidence is not None]
    return {
        "source_document_ref": bill.source_document_ref,
        "sources": [
            {"line_id": str(li.id), "page": li.source_page, "snippet": li.source_text}
            for li in lines
        ],
        "confidence": None if not confidences else format(min(confidences), "f"),
        "limitations": [
            "Deterministic comparison of supplied evidence, not medical or bank verification.",
            "Missing identifiers and source locations are not inferred.",
        ],
    }


def collect_flags(db: Session, case: CareCase) -> list[BillingFlag]:
    """Calculate current candidates without writes, commits, or trusting model arithmetic."""
    # Lazy import avoids the service -> rules -> service import cycle.
    from app import services as svc

    found = []
    bills = list(db.scalars(select(Bill).where(Bill.case_id == case.id)))
    for bill in bills:
        lines = list(bill.line_items)
        views = [svc._line_view(li) for li in lines]
        for candidate in duplicates.find_exact_duplicates(views):
            own = [li for li in lines if li.id in candidate.line_ids]
            evidence = _evidence(bill, own)
            evidence.update(
                {
                    "line_numbers": list(candidate.line_numbers),
                    "first_line_id": str(candidate.first_line_id),
                    "repeat_line_ids": [str(i) for i in candidate.repeat_line_ids],
                }
            )
            found.append(
                BillingFlag(
                    case_id=case.id,
                    bill_id=bill.id,
                    flag_type=FlagType.POSSIBLE_EXACT_DUPLICATE,
                    line_item_ids=[str(i) for i in candidate.line_ids],
                    amount_involved=candidate.amount_involved,
                    explanation=candidate.explanation,
                    evidence=evidence,
                    rule_id=duplicates.RULE_ID,
                    rule_version=duplicates.RULE_VERSION,
                    dedupe_key=candidate.dedupe_key,
                )
            )
        for issue in arithmetic.check_bill_arithmetic(svc._bill_view(bill), views):
            evidence = _evidence(bill, [li for li in lines if li.id in issue.line_ids])
            evidence.update(
                {
                    "kind": issue.kind,
                    "expected": to_str(issue.expected),
                    "printed": to_str(issue.printed),
                }
            )
            found.append(
                BillingFlag(
                    case_id=case.id,
                    bill_id=bill.id,
                    flag_type=FlagType.ARITHMETIC_MISMATCH,
                    line_item_ids=[str(i) for i in issue.line_ids],
                    amount_involved=issue.difference,
                    explanation=issue.explanation,
                    evidence=evidence,
                    rule_id=arithmetic.RULE_ID,
                    rule_version=arithmetic.RULE_VERSION,
                    dedupe_key=issue.dedupe_key,
                )
            )
        found.extend(_estimate_flags(db, case, bill, lines))
    found.extend(_episode_flags(db, case))
    return found


def _episode_flags(db, case):
    from app.episode.overlap import analyze_episode_overlaps
    from app.episode.records import assess_affinity, load_episode_records

    records = assess_affinity(load_episode_records(db, case), case.currency)
    analysis = analyze_episode_overlaps(db, case, records)
    by_line = {str(li.id): bill for bill in case.bills for li in bill.line_items}
    found = []
    for candidate in analysis.overlaps:
        ids = [line_id for line_id in candidate.line_item_ids if line_id in by_line]
        if not ids:
            continue
        evidence = dict(
            overlap_type=candidate.overlap_type,
            sources=list(candidate.sources),
            involved_document_ids=list(candidate.involved_document_ids),
            amount_basis="Possible repeated exposure; no automatic deduction or savings.",
        )
        key = hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest()[:40]
        found.append(
            BillingFlag(
                case_id=case.id,
                bill_id=by_line[ids[0]].id,
                flag_type=(
                    FlagType.POSSIBLE_NEAR_DUPLICATE
                    if candidate.overlap_type == "NEAR_DUPLICATE"
                    else FlagType.CROSS_DOCUMENT_OVERLAP
                ),
                line_item_ids=ids,
                amount_involved=candidate.amount,
                explanation=candidate.description,
                evidence=evidence,
                rule_id="episode_overlap",
                rule_version="2",
                dedupe_key=f"episode-overlap:v2:{key}",
            )
        )
    return found


def _estimate_flags(db, case, bill, lines):
    from app.extraction.service import _load

    documents = list(
        db.scalars(
            select(EvidenceDocument)
            .where(
                EvidenceDocument.case_id == case.id,
                EvidenceDocument.document_type == DocumentType.ESTIMATE,
            )
            .order_by(EvidenceDocument.id)
        )
    )
    rows = list(
        db.scalars(
            select(DocumentExtraction)
            .join(EvidenceDocument, DocumentExtraction.document_id == EvidenceDocument.id)
            .where(
                DocumentExtraction.case_id == case.id,
                EvidenceDocument.document_type == DocumentType.ESTIMATE,
            )
            .order_by(DocumentExtraction.created_at, DocumentExtraction.id)
        )
    )
    extracted_ids = {row.document_id for row in rows}
    pending = [
        doc
        for doc in documents
        if doc.id not in extracted_ids or doc.extraction_status != "EXTRACTED"
    ]
    if pending:
        states = [(str(doc.id), str(doc.extraction_status)) for doc in pending]
        fingerprint = hashlib.sha256(json.dumps(states).encode()).hexdigest()[:24]
        evidence = _evidence(bill, lines)
        evidence.update(
            {
                "estimate_document_ids": [str(doc.id) for doc in pending],
                "estimate_statuses": dict(states),
                "item_changes": [],
                "limitations": evidence["limitations"]
                + ["No estimate amounts are inferred before a validated extraction is available."],
            }
        )
        return [
            BillingFlag(
                case_id=case.id,
                bill_id=bill.id,
                flag_type=FlagType.ESTIMATE_DRIFT,
                line_item_ids=[str(li.id) for li in lines],
                amount_involved=ZERO,
                explanation=(
                    "Supplied estimate awaits a successful extraction; needs clarification."
                ),
                evidence=evidence,
                rule_id="estimate_drift",
                rule_version="1",
                dedupe_key=f"estimate:{bill.id}:pending:{fingerprint}",
            )
        ]
    if not rows:
        return []
    loaded = [_load(db, row) for row in rows]
    matches = []
    for estimate in loaded:
        fields = {f.info.path: f for f in estimate.fields}
        provider = fields["provider_name"].value
        currency = fields["currency"].value
        if (
            normalize_text(provider) == normalize_text(bill.provider_name)
            and currency == bill.currency
        ):
            matches.append((estimate, fields))
    fingerprint = hashlib.sha256(
        json.dumps(
            [
                {
                    "id": str(e.doc.id),
                    "revisions": len(e.revisions),
                    "values": [(f.info.path, f.value, f.state) for f in e.fields],
                }
                for e in loaded
            ],
            sort_keys=True,
        ).encode()
    ).hexdigest()[:24]
    evidence = _evidence(bill, lines)
    evidence.update(
        {
            "estimate_document_ids": [str(e.doc.id) for e in loaded],
            "estimate_sources": [
                {"path": f.info.path, "source": f.source}
                for e in loaded
                for f in e.fields
                if f.value is not None
            ],
            "estimate_revision_counts": {str(e.doc.id): len(e.revisions) for e in loaded},
        }
    )
    problems = []
    deltas = []
    amount = ZERO
    if len(matches) != 1:
        problems.append(
            "Estimate comparison needs clarification: select one matching provider/currency "
            "estimate; automatic selection is ambiguous or unavailable."
        )
    else:
        estimate, fields = matches[0]
        if estimate.ex.document_type != DocumentType.ESTIMATE:
            problems.append("The extracted document type does not match the uploaded estimate.")
        if any(f.needs_review for f in estimate.fields):
            problems.append("Estimate contains low-confidence values awaiting human review.")
        expected = defaultdict(lambda: ZERO)
        actual = defaultdict(lambda: ZERO)
        for index, _line in enumerate(estimate.ex.line_items):
            prefix = f"line_items.{index}."
            desc, code, total = (
                fields[prefix + name].value for name in ("description", "code", "line_total")
            )
            if desc is None or total is None:
                problems.append(f"Estimate line {index + 1} lacks a description or total.")
                continue
            expected[(normalize_text(desc), normalize_text(code))] += Decimal(total)
        tax_text = fields["tax_total"].value
        estimate_total_text = fields["total"].value
        estimated_lines = sum(expected.values(), ZERO)
        if tax_text is not None and Decimal(tax_text) != ZERO:
            if estimate_total_text is None:
                problems.append("Estimate tax treatment needs a stated total for comparison.")
            elif estimated_lines + Decimal(tax_text) == Decimal(estimate_total_text):
                expected[("stated tax", "CAREDIRECT_TAX")] = Decimal(tax_text)
            elif estimated_lines != Decimal(estimate_total_text):
                problems.append("Estimate line totals and stated tax do not reconcile.")
        elif estimate_total_text is not None and estimated_lines != Decimal(estimate_total_text):
            problems.append("Estimate line totals differ from its stated total.")
        for line in lines:
            if getattr(line, "code", None) == "CAREDIRECT_TAX":
                actual[("stated tax", "CAREDIRECT_TAX")] += line.line_total
                continue
            actual[
                (normalize_text(line.description_raw), normalize_text(getattr(line, "code", None)))
            ] += line.line_total
        for key in sorted(set(expected) | set(actual)):
            delta = actual[key] - expected[key]
            if delta:
                amount += abs(delta)
                deltas.append(
                    {
                        "description": key[0],
                        "code": key[1] or None,
                        "estimate": to_str(expected[key]),
                        "bill": to_str(actual[key]),
                        "difference": to_str(delta),
                    }
                )
        if deltas:
            problems.append(
                "Bill line amounts differ from the supplied estimate; needs clarification."
            )
        evidence["estimate_document_id"] = str(estimate.doc.id)
        evidence["estimate_confidence"] = min(
            (
                format(f.model_confidence, "f")
                for f in estimate.fields
                if f.model_confidence is not None
            ),
            default=None,
        )
    if not problems:
        return []
    evidence["item_changes"] = deltas
    evidence["amount_basis"] = (
        "Sum of absolute item-total differences; not savings or an adjustment."
    )
    evidence["limitations"].append(
        "Exact description/code comparison only; estimate changes may be justified. "
        "No medical necessity or reference-price judgment is made."
    )
    return [
        BillingFlag(
            case_id=case.id,
            bill_id=bill.id,
            flag_type=FlagType.ESTIMATE_DRIFT,
            line_item_ids=[str(li.id) for li in lines],
            amount_involved=amount,
            explanation=" ".join(problems),
            evidence=evidence,
            rule_id="estimate_drift",
            rule_version="1",
            dedupe_key=f"estimate:{bill.id}:{fingerprint}",
        )
    ]
