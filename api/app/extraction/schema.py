"""Versioned schema for AI document extraction (caredirect.extraction.v1).

AI output is untrusted. It is validated here before anything is stored:
- unknown keys are rejected at every level;
- money and quantity must be decimal strings, never floats; confidence is a decimal string;
- every non-null value carries a confidence and a source (document, page, snippet or box);
- a missing value is null, never a guess;
- only minimised identifiers exist: no patient name, phone or address field.

Validation errors are reduced to a location and an error type. Input values are never copied
into them, so document text cannot leak into logs or audit events.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, Generic, Literal, Self, TypeVar
from uuid import UUID

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictInt,
    StringConstraints,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)

from app.money import MoneyError, money, quantity, to_str
from app.schemas import MoneyIn, QuantityIn
from app.states import DocumentType, PaymentMethod

SCHEMA_VERSION = "caredirect.extraction.v1"
# Same value as reconciliation.advance.MIN_AI_CONFIDENCE: below this a person must look.
LOW_CONFIDENCE_THRESHOLD = Decimal("0.900")

_MILLI = Decimal("0.001")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MONEY_TEXT_RE = re.compile(r"^-?\d{1,12}(\.\d+)?$")
_QUANTITY_TEXT_RE = re.compile(r"^\d{1,9}(\.\d+)?$")


class ExtractionRejected(Exception):
    """The AI output failed schema validation. `errors` holds locations and types only."""

    def __init__(self, errors: list[dict[str, Any]]) -> None:
        super().__init__("extraction output failed schema validation")
        self.errors = errors


# ---------------------------------------------------------------- scalar validators


def _unit_decimal(v: object, what: str) -> Decimal:
    if not isinstance(v, str | Decimal):
        raise ValueError(f"{what} must be a decimal string between 0 and 1")
    try:
        d = Decimal(v)
    except InvalidOperation:
        raise ValueError(f"{what} must be a decimal string between 0 and 1") from None
    if not d.is_finite() or not 0 <= d <= 1:
        raise ValueError(f"{what} must be between 0 and 1")
    q = d.quantize(_MILLI)
    if q != d:
        raise ValueError(f"{what} may have at most 3 decimal places")
    return q


def _confidence(v: object) -> Decimal:
    return _unit_decimal(v, "confidence")


def _coordinate(v: object) -> Decimal:
    return _unit_decimal(v, "coordinate")


def _date_in(v: object) -> date:
    if not isinstance(v, str) or not _DATE_RE.fullmatch(v):
        raise ValueError("date must be a string like 2026-11-02")
    try:
        return date.fromisoformat(v)
    except ValueError:
        raise ValueError("date is not a real calendar date") from None


def _no_nul(v: object) -> object:
    # PostgreSQL cannot store NUL in text or JSONB, so refuse it at the boundary.
    if isinstance(v, str) and "\x00" in v:
        raise ValueError("text must not contain NUL characters")
    return v


def _text(max_len: int):
    return Annotated[
        str,
        BeforeValidator(_no_nul),
        StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=max_len),
    ]


Confidence = Annotated[Decimal, BeforeValidator(_confidence)]
Coordinate = Annotated[Decimal, BeforeValidator(_coordinate)]
IsoDate = Annotated[date, BeforeValidator(_date_in)]
CurrencyCode = Annotated[str, StringConstraints(strict=True, pattern=r"^[A-Z]{3}$")]
Snippet = Annotated[
    str, BeforeValidator(_no_nul), StringConstraints(strict=True, min_length=1, max_length=500)
]
PageNumber = Annotated[StrictInt, Field(ge=1)]

# Text limits match the database columns that promotion writes into.
Text40 = _text(40)
Text80 = _text(80)
Text120 = _text(120)
Text200 = _text(200)
Text500 = _text(500)


# ---------------------------------------------------------------- building blocks


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class BoundingBox(_Strict):
    """Normalised page coordinates (0 to 1), origin at the top left."""

    x0: Coordinate
    y0: Coordinate
    x1: Coordinate
    y1: Coordinate

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if not (self.x0 < self.x1 and self.y0 < self.y1):
            raise ValueError("bounding box must have x0 < x1 and y0 < y1")
        return self


class SourceRef(_Strict):
    document_id: UUID
    page: PageNumber
    snippet: Snippet | None = None
    bbox: BoundingBox | None = None

    @field_validator("document_id")
    @classmethod
    def _same_document(cls, v: UUID, info: ValidationInfo) -> UUID:
        expected = (info.context or {}).get("document_id")
        if expected is not None and v != expected:
            raise ValueError("source points at a different document")
        return v

    @field_validator("page")
    @classmethod
    def _page_exists(cls, v: int, info: ValidationInfo) -> int:
        pages = (info.context or {}).get("page_count")
        if pages is not None and v > pages:
            raise ValueError("source page is beyond the end of the document")
        return v

    @model_validator(mode="after")
    def _locatable(self) -> Self:
        if self.snippet is None and self.bbox is None:
            raise ValueError("a source needs a snippet or a bounding box")
        return self


T = TypeVar("T")


class Extracted(_Strict, Generic[T]):
    """One extracted value with its evidence. A null value may have no confidence or source."""

    value: T | None
    confidence: Confidence | None = None
    source: SourceRef | None = None

    @model_validator(mode="after")
    def _evidence_for_values(self) -> Self:
        if self.value is not None and (self.confidence is None or self.source is None):
            raise ValueError("a value needs both a confidence and a source")
        return self


class LineItemV1(_Strict):
    line_number: Annotated[StrictInt, Field(ge=1, le=500)]
    description: Extracted[Text500]
    code: Extracted[Text40]
    service_date: Extracted[IsoDate]
    quantity: Extracted[QuantityIn]
    unit_price: Extracted[MoneyIn]
    line_total: Extracted[MoneyIn]

    @field_validator("code")
    @classmethod
    def _reserved_code(cls, field):
        if field.value is not None and field.value.upper() == "CAREDIRECT_TAX":
            raise ValueError("reserved internal accounting code")
        return field


class ReceiptV1(_Strict):
    amount: Extracted[MoneyIn]
    paid_on: Extracted[IsoDate]
    transaction_reference: Extracted[Text120]
    payee_name: Extracted[Text200]
    payment_method: Extracted[PaymentMethod]


class InsuranceV1(_Strict):
    """Stated insurance facts only. Approval is not proof of payment or eligibility."""

    insurer_name: Extracted[Text200] = Field(default_factory=lambda: Extracted(value=None))
    claim_reference: Extracted[Text80] = Field(default_factory=lambda: Extracted(value=None))
    bill_reference: Extracted[Text80] = Field(default_factory=lambda: Extracted(value=None))
    claimed_total: Extracted[MoneyIn] = Field(default_factory=lambda: Extracted(value=None))
    approved_amount: Extracted[MoneyIn] = Field(default_factory=lambda: Extracted(value=None))
    copay: Extracted[MoneyIn] = Field(default_factory=lambda: Extracted(value=None))
    deductible: Extracted[MoneyIn] = Field(default_factory=lambda: Extracted(value=None))
    noncovered: Extracted[MoneyIn] = Field(default_factory=lambda: Extracted(value=None))
    pending: Extracted[MoneyIn] = Field(default_factory=lambda: Extracted(value=None))
    rejected: Extracted[MoneyIn] = Field(default_factory=lambda: Extracted(value=None))
    insurer_paid: Extracted[MoneyIn] = Field(default_factory=lambda: Extracted(value=None))
    family_paid: Extracted[MoneyIn] = Field(default_factory=lambda: Extracted(value=None))
    payment_reference: Extracted[Text120] = Field(default_factory=lambda: Extracted(value=None))
    payment_recipient: Extracted[Text200] = Field(default_factory=lambda: Extracted(value=None))
    paid_on: Extracted[IsoDate] = Field(default_factory=lambda: Extracted(value=None))
    stated_reason: Extracted[Text500] = Field(default_factory=lambda: Extracted(value=None))


class ExtractionV1(_Strict):
    schema_version: Literal["caredirect.extraction.v1"]
    document_id: UUID
    document_type: DocumentType
    provider_name: Extracted[Text200]
    provider_identifier: Extracted[Text40]
    patient_reference: Extracted[Text40]
    invoice_number: Extracted[Text80]
    invoice_date: Extracted[IsoDate]
    currency: Extracted[CurrencyCode]
    line_items: Annotated[list[LineItemV1], Field(max_length=500)]
    subtotal: Extracted[MoneyIn]
    tax_total: Extracted[MoneyIn]
    total: Extracted[MoneyIn]
    advance_paid: Extracted[MoneyIn]
    receipt: ReceiptV1 | None
    insurance: InsuranceV1 | None = None

    @field_validator("document_id")
    @classmethod
    def _same_document(cls, v: UUID, info: ValidationInfo) -> UUID:
        expected = (info.context or {}).get("document_id")
        if expected is not None and v != expected:
            raise ValueError("output is for a different document")
        return v

    @model_validator(mode="after")
    def _unique_line_numbers(self) -> Self:
        numbers = [ln.line_number for ln in self.line_items]
        if len(set(numbers)) != len(numbers):
            raise ValueError("line numbers must be unique")
        return self


def parse_extraction(raw: object, *, document_id: UUID, page_count: int) -> ExtractionV1:
    """Validate untrusted output for one document. Raises ExtractionRejected."""
    if not isinstance(raw, dict):
        raise ExtractionRejected([{"loc": [], "type": "not_an_object"}])
    try:
        return ExtractionV1.model_validate(
            raw, context={"document_id": document_id, "page_count": page_count}
        )
    except ValidationError as exc:
        errors = exc.errors(include_url=False, include_context=False, include_input=False)
        raise ExtractionRejected(
            [{"loc": list(e["loc"]), "type": e["type"]} for e in errors]
        ) from None


def build_source(raw: dict[str, Any], *, document_id: UUID, page_count: int) -> SourceRef:
    """Validate a source supplied with a human correction (same rules as AI sources)."""
    try:
        return SourceRef.model_validate(
            {**raw, "document_id": document_id},
            context={"document_id": document_id, "page_count": page_count},
        )
    except ValidationError:
        raise ValueError("the page or snippet given is not valid for this document") from None


# ---------------------------------------------------------------- field walking


@dataclass(frozen=True)
class FieldInfo:
    path: str
    field: Extracted[Any]
    kind: str  # text | money | quantity | date | currency | payment_method
    group: str  # document | line_item | totals | receipt
    line_index: int | None
    line_number: int | None
    name: str
    label: str
    max_len: int | None


# (name, kind, max_len, label)
_DOCUMENT_FIELDS = (
    ("provider_name", "text", 200, "Provider name"),
    ("provider_identifier", "text", 40, "Provider identifier"),
    ("patient_reference", "text", 40, "Patient reference"),
    ("invoice_number", "text", 80, "Invoice number"),
    ("invoice_date", "date", None, "Invoice date"),
    ("currency", "currency", None, "Currency"),
)
_LINE_FIELDS = (
    ("description", "text", 500, "description"),
    ("code", "text", 40, "code"),
    ("service_date", "date", None, "service date"),
    ("quantity", "quantity", None, "quantity"),
    ("unit_price", "money", None, "unit price"),
    ("line_total", "money", None, "line total"),
)
_TOTAL_FIELDS = (
    ("subtotal", "money", None, "Stated subtotal"),
    ("tax_total", "money", None, "Stated tax"),
    ("total", "money", None, "Stated total"),
    ("advance_paid", "money", None, "Advance paid (as printed)"),
)
_RECEIPT_FIELDS = (
    ("amount", "money", None, "Receipt amount"),
    ("paid_on", "date", None, "Paid on"),
    ("transaction_reference", "text", 120, "Transaction reference"),
    ("payee_name", "text", 200, "Payee name"),
    ("payment_method", "payment_method", None, "Payment method"),
)
_INSURANCE_FIELDS = (
    ("insurer_name", "text", 200, "Insurer / TPA name"),
    ("claim_reference", "text", 80, "Claim reference"),
    ("bill_reference", "text", 80, "Hospital bill reference"),
    ("claimed_total", "money", None, "Claimed bill amount"),
    ("approved_amount", "money", None, "Insurer approved (not payment)"),
    ("copay", "money", None, "Patient co-payment"),
    ("deductible", "money", None, "Patient deductible"),
    ("noncovered", "money", None, "Stated non-covered expenses"),
    ("pending", "money", None, "Pending claim amount"),
    ("rejected", "money", None, "Rejected claim amount (responsibility unresolved)"),
    ("insurer_paid", "money", None, "Stated insurer payment"),
    ("family_paid", "money", None, "Stated family payment (not reconciled evidence)"),
    ("payment_reference", "text", 120, "Insurer payment reference"),
    ("payment_recipient", "text", 200, "Insurer payment recipient"),
    ("paid_on", "date", None, "Insurer payment date"),
    ("stated_reason", "text", 500, "Reason stated in document"),
)


def iter_fields(ex: ExtractionV1) -> Iterator[FieldInfo]:
    """Every field in a stable order: document, each line, totals, then receipt."""
    for name, kind, max_len, label in _DOCUMENT_FIELDS:
        yield FieldInfo(name, getattr(ex, name), kind, "document", None, None, name, label, max_len)
    for index, line in enumerate(ex.line_items):
        for name, kind, max_len, label in _LINE_FIELDS:
            yield FieldInfo(
                f"line_items.{index}.{name}",
                getattr(line, name),
                kind,
                "line_item",
                index,
                line.line_number,
                name,
                f"Line {line.line_number} {label}",
                max_len,
            )
    for name, kind, max_len, label in _TOTAL_FIELDS:
        yield FieldInfo(name, getattr(ex, name), kind, "totals", None, None, name, label, max_len)
    if ex.receipt is not None:
        for name, kind, max_len, label in _RECEIPT_FIELDS:
            yield FieldInfo(
                f"receipt.{name}",
                getattr(ex.receipt, name),
                kind,
                "receipt",
                None,
                None,
                name,
                label,
                max_len,
            )
    if ex.insurance is not None:
        for name, kind, max_len, label in _INSURANCE_FIELDS:
            yield FieldInfo(
                f"insurance.{name}",
                getattr(ex.insurance, name),
                kind,
                "insurance",
                None,
                None,
                name,
                label,
                max_len,
            )


def value_to_str(kind: str, value: Any) -> str | None:
    """The normalised string form of a value (money '1500.00', quantity '1.000')."""
    if value is None:
        return None
    if kind == "money":
        return to_str(value)
    if kind == "quantity":
        return format(value, "f")
    if kind == "date":
        return value.isoformat()
    if kind == "payment_method":
        return str(value)
    return str(value)


def parse_field_value(kind: str, max_len: int | None, raw: str | None) -> str | None:
    """Normalise a human-supplied value. Blank means null. Raises ValueError."""
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ValueError("value must be text")
    text = raw.strip()
    if not text:
        return None
    if "\x00" in text:
        raise ValueError("value must not contain NUL characters")
    try:
        if kind == "money":
            if not _MONEY_TEXT_RE.fullmatch(text):
                raise ValueError("enter an amount such as 1200 or 1200.50")
            return to_str(money(text))
        if kind == "quantity":
            if not _QUANTITY_TEXT_RE.fullmatch(text):
                raise ValueError("enter a quantity such as 1 or 2.5")
            return format(quantity(text), "f")
        if kind == "date":
            return _date_in(text).isoformat()
        if kind == "currency":
            code = text.upper()
            if not re.fullmatch(r"[A-Z]{3}", code):
                raise ValueError("enter a three-letter currency code such as INR")
            return code
        if kind == "payment_method":
            try:
                return str(PaymentMethod(text.upper()))
            except ValueError:
                options = ", ".join(m.value for m in PaymentMethod)
                raise ValueError(f"choose one of: {options}") from None
    except MoneyError as exc:
        raise ValueError(str(exc)) from None
    if max_len is not None and len(text) > max_len:
        raise ValueError(f"value is longer than {max_len} characters")
    return text


def review_required(ex: ExtractionV1, reviewed: set[str]) -> list[str]:
    """Paths whose value is non-null, below the confidence threshold and not yet confirmed or
    corrected by a person. A null cannot be flagged by confidence."""
    return [
        info.path
        for info in iter_fields(ex)
        if info.field.value is not None
        and info.field.confidence is not None
        and info.field.confidence < LOW_CONFIDENCE_THRESHOLD
        and info.path not in reviewed
    ]
