"""Bill arithmetic verification against printed values."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from app.money import round_cents, sum_money
from app.reconciliation.views import BillView, LineView

RULE_ID = "bill_arithmetic"
RULE_VERSION = "1"


@dataclass(frozen=True)
class ArithmeticIssue:
    kind: str  # LINE_TOTAL | BILL_TOTAL | BALANCE_DUE
    line_ids: tuple[uuid.UUID, ...]
    expected: Decimal
    printed: Decimal
    explanation: str
    dedupe_key: str

    @property
    def difference(self) -> Decimal:
        return abs(self.printed - self.expected)


def check_bill_arithmetic(bill: BillView, lines: Sequence[LineView]) -> list[ArithmeticIssue]:
    issues: list[ArithmeticIssue] = []

    for line in sorted(lines, key=lambda x: x.line_number):
        if line.quantity is None or line.unit_price is None:
            continue
        expected = round_cents(line.quantity * line.unit_price)
        if expected != line.line_total:
            issues.append(
                ArithmeticIssue(
                    kind="LINE_TOTAL",
                    line_ids=(line.id,),
                    expected=expected,
                    printed=line.line_total,
                    explanation=(
                        f"Arithmetic mismatch on line {line.line_number}: quantity "
                        f"{line.quantity} x unit price {line.unit_price} = {expected}, "
                        f"but the printed line total is {line.line_total}. Needs clarification."
                    ),
                    dedupe_key=f"arith:line:{line.id}",
                )
            )

    line_sum = sum_money(line.line_total for line in lines)
    if bill.printed_total is not None and line_sum != bill.printed_total:
        issues.append(
            ArithmeticIssue(
                kind="BILL_TOTAL",
                line_ids=tuple(line.id for line in lines),
                expected=line_sum,
                printed=bill.printed_total,
                explanation=(
                    f"Arithmetic mismatch: the line items add up to {line_sum}, but the "
                    f"printed bill total is {bill.printed_total}. Needs clarification."
                ),
                dedupe_key=f"arith:total:{bill.id}",
            )
        )

    if (
        bill.printed_total is not None
        and bill.printed_advance_paid is not None
        and bill.printed_balance_due is not None
    ):
        expected_due = bill.printed_total - bill.printed_advance_paid
        if expected_due != bill.printed_balance_due:
            issues.append(
                ArithmeticIssue(
                    kind="BALANCE_DUE",
                    line_ids=(),
                    expected=expected_due,
                    printed=bill.printed_balance_due,
                    explanation=(
                        f"Arithmetic mismatch: printed total {bill.printed_total} minus printed "
                        f"advance {bill.printed_advance_paid} = {expected_due}, but the printed "
                        f"balance due is {bill.printed_balance_due}. Needs clarification."
                    ),
                    dedupe_key=f"arith:balance:{bill.id}",
                )
            )
    return issues
