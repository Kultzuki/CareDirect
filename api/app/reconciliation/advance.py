"""Advance/prior payment reconciliation against the bill's printed advance.

This matches receipt evidence to bill evidence. It is not bank verification, and
results are labelled accordingly. Any problem leaves the payment out of the
"already paid" bucket until a human resolves it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from app.money import ZERO
from app.reconciliation.views import BillView, PaymentView, normalize_text
from app.states import DataSource

RULE_ID = "advance_payment_match"
RULE_VERSION = "1"
MIN_AI_CONFIDENCE = Decimal("0.900")
MATCH_LABEL = "Matched to bill evidence (not bank-verified)"


@dataclass(frozen=True)
class MatchResult:
    matched: bool
    basis: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    def as_json(self) -> dict:
        return {
            "rule_id": RULE_ID,
            "rule_version": RULE_VERSION,
            "label": MATCH_LABEL if self.matched else "Needs clarification",
            "basis": list(self.basis),
            "problems": list(self.problems),
        }


def match_advance_payment(
    payment: PaymentView, bill: BillView, already_matched_on_bill: Decimal = ZERO
) -> MatchResult:
    basis: list[str] = []
    problems: list[str] = []

    if payment.currency != bill.currency:
        problems.append(
            f"Receipt currency {payment.currency} differs from bill currency {bill.currency}."
        )
    else:
        basis.append(f"Currency matches ({bill.currency}).")

    if bill.printed_advance_paid is None:
        problems.append(
            "The bill does not show an advance or prior payment, so the receipt cannot be "
            "matched to it."
        )
    else:
        remaining = bill.printed_advance_paid - already_matched_on_bill
        if payment.amount > remaining:
            problems.append(
                f"Receipt amount {payment.amount} exceeds the printed advance not yet "
                f"matched ({remaining})."
            )
        elif payment.amount == remaining:
            basis.append(f"Amount {payment.amount} equals the printed advance on the bill.")
        else:
            basis.append(
                f"Amount {payment.amount} is part of the printed advance {remaining} "
                "not yet matched."
            )

    if payment.paid_on is None:
        problems.append("Payment date not present in supplied evidence.")
    elif bill.bill_date is not None and payment.paid_on > bill.bill_date:
        problems.append(
            f"Payment date {payment.paid_on} is after the bill date {bill.bill_date}, so it "
            "is not covered by the printed advance."
        )
    else:
        basis.append(f"Payment date {payment.paid_on} is on or before the bill date.")

    payee = normalize_text(payment.payee_name)
    provider = normalize_text(bill.provider_name)
    if not payee:
        problems.append("Payee not present in supplied evidence.")
    elif payee in provider or provider in payee:
        basis.append("Payee name on receipt matches the provider name on the bill.")
    else:
        problems.append("Payee name on receipt does not match the provider name on the bill.")

    if not (payment.reference or "").strip():
        problems.append("Transaction reference not present in supplied evidence.")
    else:
        basis.append("Transaction reference present on receipt.")

    if payment.source_type == DataSource.AI_EXTRACTED and (
        payment.extraction_confidence is None or payment.extraction_confidence < MIN_AI_CONFIDENCE
    ):
        problems.append("Receipt values were extracted with low confidence; human review required.")

    return MatchResult(matched=not problems, basis=basis, problems=problems)
