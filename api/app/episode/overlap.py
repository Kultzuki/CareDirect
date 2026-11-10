"""Source-linked overlap candidates. A candidate never authorizes a deduction."""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app.episode.records import category, load_episode_records
from app.money import ZERO
from app.reconciliation.semantic import near_pairs, saved_suggestions
from app.reconciliation.views import normalize_text


@dataclass(frozen=True)
class OverlapFinding:
    overlap_type: str
    title: str
    description: str
    amount: Decimal
    currency: str
    involved_document_ids: tuple[str, ...]
    line_item_ids: tuple[str, ...]
    sources: tuple[dict, ...] = ()
    candidate_line_ids: tuple[str, ...] = ()


@dataclass
class EpisodeOverlapAnalysis:
    documents: list[dict] = field(default_factory=list)
    overlaps: list[OverlapFinding] = field(default_factory=list)
    gross_billed: Decimal = ZERO
    overlap_amount: Decimal = ZERO
    net_billed: Decimal = ZERO


def find_overlaps(records, currency, suggestions=()):
    groups = defaultdict(list)
    for doc in records:
        if doc["document_type"] != "BILL" or doc["currency"] != currency:
            continue
        if doc.get("affinity_status") == "conflict" or doc["review_state"] == "needs_review":
            continue
        for line in doc["lines"]:
            if (
                not all(
                    line.get(k) is not None
                    for k in ("description", "service_date", "quantity", "unit_price", "line_total")
                )
                or not doc["provider"]
            ):
                continue
            key = (
                normalize_text(doc["provider"]),
                normalize_text(line["description"]),
                normalize_text(line["code"]),
                line["service_date"],
                Decimal(line["quantity"]),
                Decimal(line["unit_price"]),
                Decimal(line["line_total"]),
            )
            groups[key].append((doc, line))
    findings = []
    for members in groups.values():
        by_doc = defaultdict(list)
        for doc, line in members:
            by_doc[doc["id"]].append((doc, line))
        if len(by_doc) < 2:
            continue
        baseline = max(sorted(by_doc), key=lambda key: len(by_doc[key]))
        repeats = [
            (doc, li) for key in sorted(by_doc) if key != baseline for doc, li in by_doc[key]
        ]
        amount = sum((Decimal(li["line_total"]) for _, li in repeats), ZERO)
        findings.append(
            OverlapFinding(
                overlap_type="CROSS_BILL_DUPLICATE",
                title=f"Possible overlap: {members[0][1]['description']}",
                description="Provider, service date, code, description, quantity and price agree. "
                "Ask whether this is a repeated charge or summary inclusion. No deduction is made.",
                amount=amount,
                currency=currency,
                involved_document_ids=tuple(sorted(by_doc)),
                line_item_ids=tuple(
                    sorted(li["ledger_line_id"] for _, li in members if li["ledger_line_id"])
                ),
                sources=tuple(
                    dict(document_id=doc["id"], source_available=doc["source_available"], **li)
                    for doc, li in members
                ),
                candidate_line_ids=tuple(li["id"] for _, li in repeats),
            )
        )
    for left_doc, left, right_doc, right, origin, code_check in near_pairs(
        records, currency, suggestions
    ):
        findings.append(
            OverlapFinding(
                overlap_type="NEAR_DUPLICATE",
                title=f"Possible same service: {left['description']} / {right['description']}",
                description=f"{origin}; provider, service date and quantity agree. {code_check} "
                "Descriptions may refer to the same service. Prices and billing context must be "
                "reviewed against both source lines. Ask whether these are distinct services or "
                "a repeated charge. Human review required; no deduction is made.",
                amount=Decimal(right["line_total"]),
                currency=currency,
                involved_document_ids=tuple(sorted({left_doc["id"], right_doc["id"]})),
                line_item_ids=tuple(
                    sorted(li["ledger_line_id"] for li in (left, right) if li["ledger_line_id"])
                ),
                sources=tuple(
                    dict(document_id=d["id"], source_available=d["source_available"], **li)
                    for d, li in ((left_doc, left), (right_doc, right))
                ),
                candidate_line_ids=(right["id"],),
            )
        )
    exact_members = {li["id"] for finding in findings for li in finding.sources}
    for package in records:
        if (
            package.get("affinity_status") == "conflict"
            or package["review_state"] == "needs_review"
        ):
            continue
        if package["document_type"] != "BILL" or package["currency"] != currency:
            continue
        package_lines = [
            li
            for li in package["lines"]
            if any(
                word in (li["description"] or "").lower()
                for word in ("package", "bundled", "inclusive")
            )
        ]
        if not package_lines or not package["date"] or not package["provider"]:
            continue
        for other in records:
            if (
                other.get("affinity_status") == "conflict"
                or other["review_state"] == "needs_review"
            ):
                continue
            if (
                other["id"] == package["id"]
                or other["document_type"] != "BILL"
                or other["currency"] != currency
            ):
                continue
            if not other["provider"] or not other["date"]:
                continue
            if (
                abs((date.fromisoformat(package["date"]) - date.fromisoformat(other["date"])).days)
                > 30
            ):
                continue
            candidates = [
                li
                for li in other["lines"]
                if li["id"] not in exact_members
                and li["line_total"] is not None
                and (
                    category([li["description"] or ""]) == "DIAGNOSTICS"
                    or normalize_text(li["description"])
                    in ("cbc", "cbc test", "haemogram", "hemogram")
                )
            ]
            if not candidates:
                continue
            findings.append(
                OverlapFinding(
                    overlap_type="PACKAGE_SCOPE",
                    title="Clarify package scope for separately billed diagnostics",
                    description="A hospital package and separately billed diagnostics occur in "
                    "this episode within 30 days, possibly from different providers. "
                    "Episode assignment does not establish matching patient or package coverage. "
                    "Inclusion is unverified. Ask for package terms; no deduction is authorized.",
                    amount=sum((Decimal(li["line_total"]) for li in candidates), ZERO),
                    currency=currency,
                    involved_document_ids=(package["id"], other["id"]),
                    line_item_ids=tuple(
                        sorted(li["ledger_line_id"] for li in candidates if li["ledger_line_id"])
                    ),
                    sources=tuple(
                        dict(document_id=d["id"], source_available=d["source_available"], **li)
                        for d, lines in ((package, package_lines), (other, candidates))
                        for li in lines
                    ),
                    candidate_line_ids=tuple(li["id"] for li in candidates),
                )
            )
    return sorted(findings, key=lambda f: (f.involved_document_ids, f.title))


def analyze_episode_overlaps(db, case, records=None):
    records = load_episode_records(db, case) if records is None else records
    overlaps = find_overlaps(records, case.currency, saved_suggestions(db, case, records))
    involved = {doc_id for finding in overlaps for doc_id in finding.involved_document_ids}
    for doc in records:
        doc["is_overlapping"] = doc["id"] in involved
        doc["overlap_note"] = (
            "Possible overlap; provider clarification required." if doc["is_overlapping"] else None
        )
    gross = sum(
        (
            Decimal(doc["amount"])
            for doc in records
            if doc["document_type"] == "BILL"
            and doc["currency"] == case.currency
            and doc["amount"] is not None
        ),
        ZERO,
    )
    candidates = {
        li["id"]: Decimal(li["line_total"])
        for f in overlaps
        for li in f.sources
        if li["id"] in f.candidate_line_ids
    }
    return EpisodeOverlapAnalysis(records, overlaps, gross, sum(candidates.values(), ZERO), gross)
