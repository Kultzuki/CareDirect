"""Exact money handling. Every monetary value in CareDirect passes through `money()`.

Rules:
- Binary floats are rejected outright, including at API boundaries.
- Values are stored with exactly two decimal places (NUMERIC(14,2)).
- Input with more than two decimal places is rejected, never silently rounded.
- The only rounding is the explicit `round_cents` used when comparing a computed
  quantity x unit price against a printed line total.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CENTS = Decimal("0.01")
ZERO = Decimal("0.00")
# NUMERIC(14,2) holds up to 12 integer digits.
MAX_ABS = Decimal("999999999999.99")
QUANTITY_STEP = Decimal("0.001")


class MoneyError(ValueError):
    """Raised when a value cannot be represented exactly as money."""


def _to_decimal(value: object, what: str) -> Decimal:
    if isinstance(value, bool) or isinstance(value, float):
        raise MoneyError(f"{what} must be a decimal string, not {type(value).__name__}")
    if isinstance(value, Decimal):
        d = value
    elif isinstance(value, int):
        d = Decimal(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise MoneyError(f"{what} is empty")
        try:
            d = Decimal(text)
        except InvalidOperation as exc:
            raise MoneyError(f"{what} is not a decimal number: {value!r}") from exc
    else:
        raise MoneyError(f"{what} has unsupported type {type(value).__name__}")
    if not d.is_finite():
        raise MoneyError(f"{what} must be finite")
    return d


def money(value: object) -> Decimal:
    """Parse a monetary value exactly. Returns a Decimal with two decimal places."""
    d = _to_decimal(value, "amount")
    q = d.quantize(CENTS)
    if q != d:
        raise MoneyError(f"amount has more than two decimal places: {value!r}")
    if abs(q) > MAX_ABS:
        raise MoneyError("amount exceeds NUMERIC(14,2) range")
    return q


def quantity(value: object) -> Decimal:
    """Parse a positive quantity with up to three decimal places."""
    d = _to_decimal(value, "quantity")
    q = d.quantize(QUANTITY_STEP)
    if q != d:
        raise MoneyError(f"quantity has more than three decimal places: {value!r}")
    if q <= 0:
        raise MoneyError("quantity must be positive")
    return q


def round_cents(value: Decimal) -> Decimal:
    """Explicit half-up rounding to cents (paise). Used only for computed products."""
    if isinstance(value, float):
        raise MoneyError("refusing to round a float")
    return value.quantize(CENTS, rounding=ROUND_HALF_UP)


def sum_money(values: Iterable[Decimal]) -> Decimal:
    total = ZERO
    for v in values:
        total += money(v)
    return total


def to_str(value: Decimal) -> str:
    """Serialise money as a plain decimal string, e.g. '19000.00'."""
    return format(money(value), "f")
