"""Read-only, source-linked estimate comparison. All arithmetic stays in Decimal."""

from collections import defaultdict
from decimal import Decimal

from app.money import ZERO, to_str
from app.reconciliation.views import normalize_text


def snapshot(loaded):
    """Use current human revisions and preserve each field's original evidence location."""
    fields = {f.info.path: f for f in loaded.fields}
    lines = []
    for index, line in enumerate(loaded.ex.line_items):
        own = {
            name: fields[f"line_items.{index}.{name}"]
            for name in (
                "description",
                "code",
                "quantity",
                "unit_price",
                "line_total",
                "service_date",
            )
        }
        lines.append(
            {
                "line_number": line.line_number,
                **{name: field.value for name, field in own.items()},
                "sources": [
                    {
                        "path": field.info.path,
                        "source": field.source,
                        "state": field.state,
                        "needs_review": field.needs_review,
                    }
                    for field in own.values()
                    if field.value is not None
                ],
            }
        )
    return {
        "document_id": str(loaded.doc.id),
        "provider": fields["provider_name"].value,
        "currency": fields["currency"].value,
        "total": fields["total"].value,
        "tax": fields["tax_total"].value,
        "total_sources": [
            {"path": name, "source": fields[name].source, "state": fields[name].state}
            for name in ("total", "tax_total")
            if fields[name].value is not None
        ],
        "needs_review": any(f.needs_review for f in loaded.fields),
        "type_matches": loaded.doc.document_type == loaded.ex.document_type,
        "lines": lines,
    }


def _sum(lines, field):
    if any(line[field] is None for line in lines):
        return None
    return sum((Decimal(line[field]) for line in lines), ZERO)


def _price(lines):
    prices = {line["unit_price"] for line in lines}
    return Decimal(next(iter(prices))) if len(prices) == 1 and None not in prices else None


def _groups(doc, warnings, label):
    groups = defaultdict(list)
    if not doc["lines"]:
        warnings.append(f"{label} has no itemized service lines to compare.")
    for line in doc["lines"]:
        # Requiring both fields avoids silently treating changed codes as the same service.
        key = (normalize_text(line["description"]), normalize_text(line["code"]))
        if not key[0]:
            warnings.append(f"{label} line {line['line_number']} has no service description.")
            key = (f"missing description: {label} {line['line_number']}", key[1])
        groups[key].append(line)
    subtotal = _sum(doc["lines"], "line_total")
    total = None if doc["total"] is None else Decimal(doc["total"])
    tax = None if doc["tax"] is None else Decimal(doc["tax"])
    if subtotal is None:
        warnings.append(f"{label} has missing line totals; the difference is incomplete.")
    elif total is None:
        warnings.append(f"{label} has no stated total; only itemized totals can be compared.")
    elif subtotal != total:
        if tax is not None and subtotal + tax == total:
            groups[("stated tax", "caredirect_tax")].append(
                {
                    "description": "Stated tax",
                    "code": None,
                    "quantity": None,
                    "unit_price": None,
                    "line_total": to_str(tax),
                    "line_number": None,
                    "service_date": None,
                    "sources": doc["total_sources"],
                }
            )
        else:
            warnings.append(
                f"{label} itemized charges and tax do not reconcile to its stated total."
            )
    return groups


def compare(estimate, final):
    """Compare one explicitly selected pair; never change payable amounts or infer justification."""
    warnings = []
    for label, doc in (("Estimate", estimate), ("Final bill", final)):
        if doc["needs_review"]:
            warnings.append(
                f"{label} contains values awaiting human review; results are provisional."
            )
        if not doc["type_matches"]:
            return {
                "status": "blocked",
                "warnings": [f"{label} extracted type needs correction."],
                "rows": [],
                "summary": "Review document types before comparing.",
            }
    if (
        not estimate["provider"]
        or not final["provider"]
        or normalize_text(estimate["provider"]) != normalize_text(final["provider"])
    ):
        return {
            "status": "blocked",
            "warnings": ["Provider names must match before comparison."],
            "rows": [],
            "summary": "Review the provider on each document.",
        }
    if not estimate["currency"] or estimate["currency"] != final["currency"]:
        return {
            "status": "blocked",
            "warnings": ["Currencies must match before comparison."],
            "rows": [],
            "summary": "Documents in different currencies cannot be compared.",
        }

    expected = _groups(estimate, warnings, "Estimate")
    actual = _groups(final, warnings, "Final bill")
    rows = []
    for key in sorted(expected.keys() | actual.keys()):
        before, after = expected[key], actual[key]
        old, new = _sum(before, "line_total"), _sum(after, "line_total")
        delta = None if old is None or new is None else new - old
        changes = []
        if not before:
            changes.append("new_service")
        elif not after:
            changes.append("removed_service")
        else:
            oq, nq = _sum(before, "quantity"), _sum(after, "quantity")
            op, np = _price(before), _price(after)
            if oq is not None and nq is not None and nq > oq:
                changes.append("increased_quantity")
            if op is not None and np is not None and np > op:
                changes.append("increased_unit_price")
        if len(after) > 1:
            changes.append("repeated_service")
        if delta:
            changes.append("amount_increased" if delta > ZERO else "amount_decreased")
        if changes:
            changes.append("explanation_needed")
        rows.append(
            {
                "description": (after or before)[0]["description"] or "Unidentified service",
                "code": (after or before)[0]["code"],
                "estimate": None if old is None else to_str(old),
                "final": None if new is None else to_str(new),
                "difference": None if delta is None else to_str(delta),
                "changes": changes,
                "estimate_lines": before,
                "final_lines": after,
            }
        )
    complete = bool(rows) and all(row["difference"] is not None for row in rows)
    item_delta = sum((Decimal(row["difference"]) for row in rows), ZERO) if complete else None
    stated_delta = (
        Decimal(final["total"]) - Decimal(estimate["total"])
        if final["total"] is not None and estimate["total"] is not None
        else None
    )
    if stated_delta is not None and item_delta is not None and stated_delta != item_delta:
        warnings.append("Source lines do not fully explain the stated total difference.")
    net = stated_delta if stated_delta is not None else item_delta
    currency = estimate["currency"]
    summary = "The total difference cannot be calculated until missing amounts are reviewed."
    if net is not None:
        direction = "higher than" if net > ZERO else "lower than" if net < ZERO else "equal to"
        summary = (
            f"Your final bill is {currency} {to_str(abs(net))} {direction} the estimate."
            if net
            else "Your final bill total equals the estimate."
        )
        increases = sorted(
            (r for r in rows if r["difference"] is not None and Decimal(r["difference"]) > ZERO),
            key=lambda r: Decimal(r["difference"]),
            reverse=True,
        )
        if increases:
            summary += (
                " The largest increases are: "
                + ", ".join(
                    f"{r['description']} (+{currency} {r['difference']})" for r in increases[:2]
                )
                + "."
            )
    if any(row["changes"] for row in rows):
        summary += (
            " Changed or repeated services need an itemized explanation. "
            "This comparison does not establish whether the provider has justified them."
        )
    return {
        "status": "needs_review" if warnings else "compared",
        "currency": currency,
        "estimate_document_id": estimate["document_id"],
        "final_document_id": final["document_id"],
        "estimate_total": estimate["total"],
        "final_total": final["total"],
        "difference": None if net is None else to_str(net),
        "itemized_difference": None if item_delta is None else to_str(item_delta),
        "rows": rows,
        "warnings": warnings,
        "summary": summary,
        "total_sources": {"estimate": estimate["total_sources"], "final": final["total_sources"]},
        "limitations": [
            "Services match by exact normalized description and code; renamed services may appear "
            "as removed and new. Repeated services may be legitimate.",
            "Only the selected documents are compared. Estimates are not payable amounts.",
            "Provider explanations are not inferred from amounts or descriptions.",
        ],
    }
