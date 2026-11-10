"""Status enums and the only permitted state transitions."""

from __future__ import annotations

from enum import StrEnum

from app.errors import InvalidTransition


class UserRole(StrEnum):
    PAYER = "PAYER"
    RELATIVE = "RELATIVE"
    PROVIDER_STAFF = "PROVIDER_STAFF"
    ADMIN = "ADMIN"


class DataSource(StrEnum):
    MANUAL_ENTRY = "MANUAL_ENTRY"
    SEEDED_SYNTHETIC = "SEEDED_SYNTHETIC"
    AI_EXTRACTED = "AI_EXTRACTED"


class CaseStatus(StrEnum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    AWAITING_PROVIDER = "AWAITING_PROVIDER"
    READY_FOR_APPROVAL = "READY_FOR_APPROVAL"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
    CLOSED = "CLOSED"


class LineItemStatus(StrEnum):
    PENDING_REVIEW = "PENDING_REVIEW"
    ACCEPTED = "ACCEPTED"
    QUERIED = "QUERIED"


class PaymentMethod(StrEnum):
    UPI = "UPI"
    CASH = "CASH"
    CARD = "CARD"
    BANK_TRANSFER = "BANK_TRANSFER"
    OTHER = "OTHER"


class ExternalPaymentStatus(StrEnum):
    SUBMITTED = "SUBMITTED"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    MATCHED = "MATCHED"
    REJECTED = "REJECTED"


class FlagType(StrEnum):
    POSSIBLE_EXACT_DUPLICATE = "POSSIBLE_EXACT_DUPLICATE"
    POSSIBLE_NEAR_DUPLICATE = "POSSIBLE_NEAR_DUPLICATE"
    ARITHMETIC_MISMATCH = "ARITHMETIC_MISMATCH"
    ADVANCE_PAYMENT_MISMATCH = "ADVANCE_PAYMENT_MISMATCH"
    ESTIMATE_DRIFT = "ESTIMATE_DRIFT"
    CROSS_DOCUMENT_OVERLAP = "CROSS_DOCUMENT_OVERLAP"


class FlagStatus(StrEnum):
    OPEN = "OPEN"
    SUBMITTED_TO_PROVIDER = "SUBMITTED_TO_PROVIDER"
    PROVIDER_RESPONDED = "PROVIDER_RESPONDED"
    RESOLVED = "RESOLVED"
    DISMISSED = "DISMISSED"


class LedgerEntryType(StrEnum):
    BILL_CHARGE = "BILL_CHARGE"
    QUERY_HOLD = "QUERY_HOLD"
    QUERY_RELEASE = "QUERY_RELEASE"
    EXTERNAL_PAYMENT = "EXTERNAL_PAYMENT"
    PAYPAL_PAYMENT = "PAYPAL_PAYMENT"
    ADJUSTMENT_CREDIT = "ADJUSTMENT_CREDIT"
    ADJUSTMENT_DEBIT = "ADJUSTMENT_DEBIT"


class DocumentType(StrEnum):
    BILL = "BILL"
    ESTIMATE = "ESTIMATE"
    RECEIPT = "RECEIPT"
    PROVIDER_SUPPORTING = "PROVIDER_SUPPORTING"
    OTHER = "OTHER"
    INSURANCE_PREAUTH = "INSURANCE_PREAUTH"
    INSURANCE_SETTLEMENT = "INSURANCE_SETTLEMENT"
    INSURER_PAYMENT = "INSURER_PAYMENT"


class EpisodeDocumentCategory(StrEnum):
    ESTIMATE = "ESTIMATE"
    CONSULTATION = "CONSULTATION"
    DIAGNOSTICS = "DIAGNOSTICS"
    SURGERY = "SURGERY"
    PHARMACY = "PHARMACY"
    INPATIENT_BILL = "INPATIENT_BILL"
    RECEIPT = "RECEIPT"
    OTHER = "OTHER"


class ExtractionStatus(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    EXTRACTED = "EXTRACTED"
    FAILED = "FAILED"


class ProviderResponseType(StrEnum):
    ACCEPT = "ACCEPT"
    CORRECT = "CORRECT"
    EXPLAIN = "EXPLAIN"


class ProviderDecisionType(StrEnum):
    ACCEPT = "ACCEPT"
    KEEP_OPEN = "KEEP_OPEN"
    REJECT = "REJECT"


class PayPalInvoiceStatus(StrEnum):
    """Invoice status as last fetched from PayPal. PayPal is authoritative; no local
    transition map exists because CareDirect never sets this value on its own."""

    DRAFT = "DRAFT"
    SENT = "SENT"
    SCHEDULED = "SCHEDULED"
    UNPAID = "UNPAID"
    PAYMENT_PENDING = "PAYMENT_PENDING"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    MARKED_AS_PAID = "MARKED_AS_PAID"
    CANCELLED = "CANCELLED"
    REFUNDED = "REFUNDED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    MARKED_AS_REFUNDED = "MARKED_AS_REFUNDED"


class PayPalPaymentSource(StrEnum):
    PAYPAL = "PAYPAL"
    EXTERNAL = "EXTERNAL"


CASE_TRANSITIONS: dict[CaseStatus, frozenset[CaseStatus]] = {
    CaseStatus.DRAFT: frozenset({CaseStatus.UNDER_REVIEW}),
    CaseStatus.UNDER_REVIEW: frozenset(
        {
            CaseStatus.AWAITING_PROVIDER,
            CaseStatus.READY_FOR_APPROVAL,
            CaseStatus.RECONCILIATION_REQUIRED,
        }
    ),
    CaseStatus.AWAITING_PROVIDER: frozenset(
        {CaseStatus.UNDER_REVIEW, CaseStatus.RECONCILIATION_REQUIRED}
    ),
    CaseStatus.READY_FOR_APPROVAL: frozenset(
        {CaseStatus.UNDER_REVIEW, CaseStatus.RECONCILIATION_REQUIRED, CaseStatus.CLOSED}
    ),
    CaseStatus.RECONCILIATION_REQUIRED: frozenset({CaseStatus.UNDER_REVIEW}),
    CaseStatus.CLOSED: frozenset(),
}

LINE_ITEM_TRANSITIONS: dict[LineItemStatus, frozenset[LineItemStatus]] = {
    LineItemStatus.PENDING_REVIEW: frozenset({LineItemStatus.ACCEPTED, LineItemStatus.QUERIED}),
    LineItemStatus.ACCEPTED: frozenset({LineItemStatus.QUERIED}),
    LineItemStatus.QUERIED: frozenset({LineItemStatus.ACCEPTED}),
}

EXTERNAL_PAYMENT_TRANSITIONS: dict[ExternalPaymentStatus, frozenset[ExternalPaymentStatus]] = {
    ExternalPaymentStatus.SUBMITTED: frozenset(
        {
            ExternalPaymentStatus.MATCHED,
            ExternalPaymentStatus.NEEDS_CLARIFICATION,
            ExternalPaymentStatus.REJECTED,
        }
    ),
    ExternalPaymentStatus.NEEDS_CLARIFICATION: frozenset(
        {ExternalPaymentStatus.MATCHED, ExternalPaymentStatus.REJECTED}
    ),
    # A matched payment is in the ledger; undoing it needs a reversal flow (not in this slice).
    ExternalPaymentStatus.MATCHED: frozenset(),
    ExternalPaymentStatus.REJECTED: frozenset(),
}

FLAG_TRANSITIONS: dict[FlagStatus, frozenset[FlagStatus]] = {
    FlagStatus.OPEN: frozenset(
        {
            FlagStatus.SUBMITTED_TO_PROVIDER,
            FlagStatus.PROVIDER_RESPONDED,
            FlagStatus.RESOLVED,
            FlagStatus.DISMISSED,
        }
    ),
    FlagStatus.SUBMITTED_TO_PROVIDER: frozenset(
        {FlagStatus.PROVIDER_RESPONDED, FlagStatus.OPEN, FlagStatus.RESOLVED}
    ),
    FlagStatus.PROVIDER_RESPONDED: frozenset(
        {FlagStatus.RESOLVED, FlagStatus.SUBMITTED_TO_PROVIDER, FlagStatus.OPEN}
    ),
    FlagStatus.RESOLVED: frozenset({FlagStatus.OPEN}),
    FlagStatus.DISMISSED: frozenset({FlagStatus.OPEN}),
}


def ensure_transition(kind: str, table: dict, current: StrEnum, target: StrEnum) -> None:
    if target not in table.get(current, frozenset()):
        raise InvalidTransition(kind, str(current), str(target))
