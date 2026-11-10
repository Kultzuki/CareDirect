"""Plain input views for the deterministic engine. No ORM, no I/O."""

from __future__ import annotations

import re
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.states import DataSource, ExternalPaymentStatus, LedgerEntryType, LineItemStatus


@dataclass(frozen=True)
class LineView:
    id: uuid.UUID
    line_number: int
    description_raw: str
    service_date: date | None
    quantity: Decimal | None
    unit_price: Decimal | None
    line_total: Decimal
    currency: str
    status: LineItemStatus = LineItemStatus.PENDING_REVIEW
    code: str | None = None


@dataclass(frozen=True)
class BillView:
    id: uuid.UUID
    provider_name: str
    bill_date: date | None
    currency: str
    printed_total: Decimal | None
    printed_advance_paid: Decimal | None
    printed_balance_due: Decimal | None


@dataclass(frozen=True)
class PaymentView:
    id: uuid.UUID
    amount: Decimal
    currency: str
    paid_on: date | None
    reference: str | None
    payee_name: str | None
    source_type: DataSource
    extraction_confidence: Decimal | None
    status: ExternalPaymentStatus = ExternalPaymentStatus.SUBMITTED


@dataclass(frozen=True)
class LedgerView:
    entry_type: LedgerEntryType
    amount: Decimal
    currency: str
    line_item_id: uuid.UUID | None = None


_NON_ALNUM = re.compile(r"[^0-9a-z]+")


def normalize_text(text: str | None) -> str:
    """Case/spacing/punctuation-insensitive form used for exact-match comparisons only."""
    if not text:
        return ""
    folded = unicodedata.normalize("NFKC", text).casefold()
    return _NON_ALNUM.sub(" ", folded).strip()
