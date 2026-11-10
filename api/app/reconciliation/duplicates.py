"""Exact duplicate candidate detection.

A candidate is a group of lines on the same bill with the same service date, the
same normalised description, quantity, unit price and line total. It is a
question for the provider, not proof of an error. Nothing is removed.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from app.money import sum_money
from app.reconciliation.views import LineView, normalize_text

RULE_ID = "possible_exact_duplicate"
RULE_VERSION = "3"


@dataclass(frozen=True)
class DuplicateCandidate:
    line_ids: tuple[uuid.UUID, ...]
    line_numbers: tuple[int, ...]
    first_line_id: uuid.UUID
    repeat_line_ids: tuple[uuid.UUID, ...]
    amount_involved: Decimal
    explanation: str

    @property
    def dedupe_key(self) -> str:
        return "dup:" + ",".join(sorted(str(i) for i in self.line_ids))


def find_exact_duplicates(lines: Sequence[LineView]) -> list[DuplicateCandidate]:
    groups: dict[tuple, list[LineView]] = defaultdict(list)
    for line in lines:
        desc = normalize_text(line.description_raw)
        # Without a description or service date, "same service" cannot be established.
        if (
            not desc
            or line.service_date is None
            or line.quantity is None
            or line.unit_price is None
        ):
            continue
        key = (
            desc,
            normalize_text(line.code),
            line.service_date,
            line.quantity,
            line.unit_price,
            line.line_total,
            line.currency,
        )
        groups[key].append(line)

    candidates: list[DuplicateCandidate] = []
    for members in groups.values():
        if len(members) < 2:
            continue
        members = sorted(members, key=lambda m: m.line_number)
        first, repeats = members[0], members[1:]
        numbers = tuple(m.line_number for m in members)
        listed = ", ".join(str(n) for n in numbers[:-1]) + f" and {numbers[-1]}"
        candidates.append(
            DuplicateCandidate(
                line_ids=tuple(m.id for m in members),
                line_numbers=numbers,
                first_line_id=first.id,
                repeat_line_ids=tuple(m.id for m in repeats),
                amount_involved=sum_money(m.line_total for m in repeats),
                explanation=(
                    f"Possible duplicate entry: lines {listed} have the same service date, "
                    "description, quantity and amount. Please confirm with the provider."
                ),
            )
        )
    candidates.sort(key=lambda c: c.line_numbers)
    return candidates
