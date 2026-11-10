"""Three-bucket accounting derived from the append-only ledger.

bill_total = payable_now + queried + already_paid

Bucket values come from ledger entries. They are then cross-checked against the
independent record state (line-item statuses, matched payments). Any disagreement,
currency mix or negative bucket is reported as an issue; callers move the case to
RECONCILIATION_REQUIRED instead of guessing.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from app.money import ZERO
from app.reconciliation.views import LedgerView, LineView, PaymentView
from app.states import ExternalPaymentStatus, LedgerEntryType, LineItemStatus

# Which bucket each ledger entry type moves, and in which direction.
LEDGER_EFFECT: dict[LedgerEntryType, tuple[str, int]] = {
    LedgerEntryType.BILL_CHARGE: ("bill_total", 1),
    LedgerEntryType.QUERY_HOLD: ("queried", 1),
    LedgerEntryType.QUERY_RELEASE: ("queried", -1),
    LedgerEntryType.EXTERNAL_PAYMENT: ("already_paid", 1),
    LedgerEntryType.PAYPAL_PAYMENT: ("already_paid", 1),
    LedgerEntryType.ADJUSTMENT_CREDIT: ("adjustments", -1),
    LedgerEntryType.ADJUSTMENT_DEBIT: ("adjustments", 1),
}


@dataclass(frozen=True)
class Buckets:
    currency: str
    bill_total: Decimal
    payable_now: Decimal
    queried: Decimal
    already_paid: Decimal
    pending_review: Decimal  # part of `payable_now` that the payer has not yet reviewed
    issues: tuple[str, ...]
    original_bill_total: Decimal = ZERO
    adjustments: Decimal = ZERO

    @property
    def net_bill_total(self) -> Decimal:
        return self.bill_total

    @property
    def invariant_holds(self) -> bool:
        return self.bill_total == self.payable_now + self.queried + self.already_paid

    @property
    def consistent(self) -> bool:
        return self.invariant_holds and not self.issues


def compute_buckets(
    currency: str,
    ledger: Sequence[LedgerView],
    lines: Sequence[LineView],
    payments: Sequence[PaymentView],
    paypal_paid: Decimal = ZERO,
) -> Buckets:
    issues: list[str] = []
    totals = {"bill_total": ZERO, "adjustments": ZERO, "queried": ZERO, "already_paid": ZERO}
    line_adjustments: dict = {}

    for entry in ledger:
        if entry.currency != currency:
            issues.append(
                f"Ledger entry in {entry.currency} on a {currency} case; currencies must not mix."
            )
            continue
        bucket, sign = LEDGER_EFFECT[entry.entry_type]
        totals[bucket] += sign * entry.amount
        if bucket == "adjustments":
            if entry.line_item_id is None:
                issues.append("An adjustment is missing its original line reference.")
            line_adjustments[entry.line_item_id] = (
                line_adjustments.get(entry.line_item_id, ZERO) + sign * entry.amount
            )

    original_bill_total = totals["bill_total"]
    adjustments = totals["adjustments"]
    bill_total = original_bill_total + adjustments
    queried = totals["queried"]
    already_paid = totals["already_paid"]
    payable = bill_total - queried - already_paid

    state_total = sum((ln.line_total for ln in lines), ZERO)
    state_queried = sum(
        (
            ln.line_total + line_adjustments.get(ln.id, ZERO)
            for ln in lines
            if ln.status == LineItemStatus.QUERIED
        ),
        ZERO,
    )
    state_paid = sum(
        (p.amount for p in payments if p.status == ExternalPaymentStatus.MATCHED), ZERO
    )
    pending = sum(
        (
            ln.line_total + line_adjustments.get(ln.id, ZERO)
            for ln in lines
            if ln.status == LineItemStatus.PENDING_REVIEW
        ),
        ZERO,
    )

    if original_bill_total != state_total:
        issues.append(
            f"Ledger bill total {original_bill_total} differs from line items {state_total}."
        )
    line_ids = {ln.id for ln in lines}
    if any(key not in line_ids for key in line_adjustments):
        issues.append("An adjustment references an unknown case line.")
    if any(ln.line_total + line_adjustments.get(ln.id, ZERO) < ZERO for ln in lines):
        issues.append("An adjusted line amount is negative.")
    if queried != state_queried:
        issues.append(f"Ledger queried {queried} differs from queried lines {state_queried}.")
    state_paid += paypal_paid
    if already_paid != state_paid:
        issues.append(
            f"Ledger already-paid {already_paid} differs from matched payments {state_paid}."
        )
    if queried < 0:
        issues.append(f"Queried bucket is negative ({queried}).")
    if payable < 0:
        issues.append(
            f"Already paid plus queried exceeds the bill total by {-payable}; "
            "reconciliation required."
        )

    return Buckets(
        currency=currency,
        bill_total=bill_total,
        payable_now=payable,
        queried=queried,
        already_paid=already_paid,
        pending_review=pending,
        issues=tuple(issues),
        original_bill_total=original_bill_total,
        adjustments=adjustments,
    )
