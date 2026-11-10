"""SQLAlchemy models. Money columns are NUMERIC(14,2); Python side is Decimal."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Identity,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    event,
    func,
    inspect,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    object_session,
    relationship,
)

from app.errors import ImmutableRecordError
from app.states import (
    CaseStatus,
    DataSource,
    DocumentType,
    ExternalPaymentStatus,
    ExtractionStatus,
    FlagStatus,
    FlagType,
    LedgerEntryType,
    LineItemStatus,
    PaymentMethod,
    PayPalInvoiceStatus,
    PayPalPaymentSource,
    ProviderDecisionType,
    ProviderResponseType,
    UserRole,
)

Money = Numeric(14, 2, asdecimal=True)

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


def _enum(e: type[StrEnum]) -> Enum:
    return Enum(
        e,
        name=e.__name__.lower(),
        native_enum=False,
        create_constraint=True,
        length=40,
        validate_strings=True,
        values_callable=lambda members: [m.value for m in members],
    )


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def _updated() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _pk()
    display_name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str | None] = mapped_column(String(254), unique=True)
    role: Mapped[UserRole] = mapped_column(_enum(UserRole))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _created()


class CareCase(Base):
    __tablename__ = "care_cases"
    __table_args__ = (CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_iso"),)

    id: Mapped[uuid.UUID] = _pk()
    case_reference: Mapped[str] = mapped_column(String(40), unique=True)
    patient_alias: Mapped[str] = mapped_column(String(120))
    episode_title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    clinical_context: Mapped[str | None] = mapped_column(Text, nullable=True)
    payer_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[CaseStatus] = mapped_column(_enum(CaseStatus), default=CaseStatus.DRAFT)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    payer: Mapped[User] = relationship()
    bills: Mapped[list[Bill]] = relationship(back_populates="case", order_by="Bill.created_at")


class Bill(Base):
    """A bill as supplied. Every column is immutable after insert."""

    __tablename__ = "bills"

    id: Mapped[uuid.UUID] = _pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("care_cases.id"), index=True)
    provider_name: Mapped[str] = mapped_column(String(200))
    bill_number: Mapped[str | None] = mapped_column(String(80))
    bill_date: Mapped[date | None] = mapped_column(Date)
    currency: Mapped[str] = mapped_column(String(3))
    printed_total: Mapped[Decimal | None] = mapped_column(Money)
    printed_advance_paid: Mapped[Decimal | None] = mapped_column(Money)
    printed_balance_due: Mapped[Decimal | None] = mapped_column(Money)
    source_type: Mapped[DataSource] = mapped_column(_enum(DataSource))
    source_document_ref: Mapped[str | None] = mapped_column(String(200))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _created()

    case: Mapped[CareCase] = relationship(back_populates="bills")
    line_items: Mapped[list[BillLineItem]] = relationship(
        back_populates="bill", order_by="BillLineItem.line_number"
    )


class BillLineItem(Base):
    """One billed line. Source/extracted columns are immutable; only review status changes."""

    __tablename__ = "bill_line_items"
    __table_args__ = (
        UniqueConstraint("bill_id", "line_number", name="uq_bill_line_items_bill_line"),
        CheckConstraint(
            "extraction_confidence IS NULL OR "
            "(extraction_confidence >= 0 AND extraction_confidence <= 1)",
            name="confidence_range",
        ),
        CheckConstraint("quantity IS NULL OR quantity > 0", name="quantity_positive"),
    )

    MUTABLE_COLUMNS = frozenset({"status", "status_note", "updated_at"})

    id: Mapped[uuid.UUID] = _pk()
    bill_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bills.id"), index=True)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("care_cases.id"), index=True)
    line_number: Mapped[int] = mapped_column(Integer)
    code: Mapped[str | None] = mapped_column(String(40))
    description_raw: Mapped[str] = mapped_column(Text)
    description_normalized: Mapped[str | None] = mapped_column(Text)
    service_date: Mapped[date | None] = mapped_column(Date)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(12, 3, asdecimal=True))
    unit_price: Mapped[Decimal | None] = mapped_column(Money)
    line_total: Mapped[Decimal] = mapped_column(Money)
    currency: Mapped[str] = mapped_column(String(3))
    source_type: Mapped[DataSource] = mapped_column(_enum(DataSource))
    extraction_confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3, asdecimal=True))
    source_page: Mapped[int | None] = mapped_column(Integer)
    source_text: Mapped[str | None] = mapped_column(Text)
    status: Mapped[LineItemStatus] = mapped_column(
        _enum(LineItemStatus), default=LineItemStatus.PENDING_REVIEW
    )
    status_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    bill: Mapped[Bill] = relationship(back_populates="line_items")

    @property
    def recognized_amount(self) -> Decimal:
        """Read-only API value; the original line_total remains immutable."""
        from app.providers import recognized_amount

        session = object_session(self)
        return recognized_amount(session, self) if session is not None else self.line_total


class ExternalPayment(Base):
    """Evidence of a payment made outside PayPal (e.g. UPI). Evidence columns are immutable."""

    __tablename__ = "external_payments"
    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint(
            "extraction_confidence IS NULL OR "
            "(extraction_confidence >= 0 AND extraction_confidence <= 1)",
            name="confidence_range",
        ),
    )

    MUTABLE_COLUMNS = frozenset({"status", "match_basis", "status_note", "updated_at"})

    id: Mapped[uuid.UUID] = _pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("care_cases.id"), index=True)
    bill_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("bills.id"))
    method: Mapped[PaymentMethod] = mapped_column(_enum(PaymentMethod))
    amount: Mapped[Decimal] = mapped_column(Money)
    currency: Mapped[str] = mapped_column(String(3))
    paid_on: Mapped[date | None] = mapped_column(Date)
    reference: Mapped[str | None] = mapped_column(String(120))
    payee_name: Mapped[str | None] = mapped_column(String(200))
    source_type: Mapped[DataSource] = mapped_column(_enum(DataSource))
    extraction_confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3, asdecimal=True))
    source_document_ref: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[ExternalPaymentStatus] = mapped_column(
        _enum(ExternalPaymentStatus), default=ExternalPaymentStatus.SUBMITTED
    )
    match_basis: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    status_note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class BillingFlag(Base):
    """A deterministic check result for human review. Never changes charges by itself."""

    __tablename__ = "billing_flags"
    __table_args__ = (
        UniqueConstraint("case_id", "dedupe_key", name="uq_billing_flags_case_dedupe"),
    )

    id: Mapped[uuid.UUID] = _pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("care_cases.id"), index=True)
    bill_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("bills.id"))
    external_payment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("external_payments.id")
    )
    flag_type: Mapped[FlagType] = mapped_column(_enum(FlagType))
    line_item_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    amount_involved: Mapped[Decimal | None] = mapped_column(Money)
    explanation: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    rule_id: Mapped[str] = mapped_column(String(80))
    rule_version: Mapped[str] = mapped_column(String(20))
    dedupe_key: Mapped[str] = mapped_column(String(200))
    status: Mapped[FlagStatus] = mapped_column(_enum(FlagStatus), default=FlagStatus.OPEN)
    resolution_note: Mapped[str | None] = mapped_column(Text)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()


class LedgerEntry(Base):
    """Append-only financial ledger. Buckets are derived from these rows."""

    __tablename__ = "ledger_entries"
    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        Index(
            "uq_ledger_external_payment_credit",
            "external_payment_id",
            unique=True,
            postgresql_where=text("entry_type = 'EXTERNAL_PAYMENT'"),
        ),
        UniqueConstraint(
            "provider_decision_id", "entry_type", name="uq_ledger_provider_decision_type"
        ),
    )

    id: Mapped[uuid.UUID] = _pk()
    seq: Mapped[int] = mapped_column(BigInteger, Identity(), unique=True)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("care_cases.id"), index=True)
    entry_type: Mapped[LedgerEntryType] = mapped_column(_enum(LedgerEntryType))
    amount: Mapped[Decimal] = mapped_column(Money)
    currency: Mapped[str] = mapped_column(String(3))
    bill_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("bills.id"))
    line_item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("bill_line_items.id"))
    external_payment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("external_payments.id")
    )
    flag_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("billing_flags.id"))
    provider_decision_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("provider_decisions.id")
    )
    paypal_payment_ref_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("paypal_payment_refs.id"), unique=True
    )
    reason: Mapped[str] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    actor_label: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = _created()


class AuditEvent(Base):
    """Append-only audit trail of every business action."""

    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = _pk()
    seq: Mapped[int] = mapped_column(BigInteger, Identity(), unique=True)
    case_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("care_cases.id"), index=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    actor_label: Mapped[str] = mapped_column(String(120))
    event_type: Mapped[str] = mapped_column(String(60))
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    ledger_entry_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ledger_entries.id"))
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = _created()


class EvidenceDocument(Base):
    """An uploaded source document (bill, estimate, receipt). Stored privately; only the
    extraction status may change after insert."""

    __tablename__ = "evidence_documents"
    __table_args__ = (
        UniqueConstraint("case_id", "sha256", name="uq_evidence_documents_case_sha256"),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="sha256_hex"),
        CheckConstraint(
            "mime_type IN ('application/pdf', 'image/jpeg', 'image/png')", name="mime_allowed"
        ),
        CheckConstraint("file_size > 0", name="file_size_positive"),
        CheckConstraint("page_count IS NULL OR page_count > 0", name="page_count_positive"),
    )

    MUTABLE_COLUMNS = frozenset({"extraction_status", "category", "updated_at"})

    id: Mapped[uuid.UUID] = _pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("care_cases.id"), index=True)
    document_type: Mapped[DocumentType] = mapped_column(_enum(DocumentType))
    category: Mapped[str | None] = mapped_column(String(60), nullable=True)
    # Private storage key; never a public URL.
    storage_key: Mapped[str] = mapped_column(String(200), unique=True)
    sha256: Mapped[str] = mapped_column(String(64))
    mime_type: Mapped[str] = mapped_column(String(100))
    file_size: Mapped[int] = mapped_column(BigInteger)
    page_count: Mapped[int | None] = mapped_column(Integer)
    source_type: Mapped[DataSource] = mapped_column(_enum(DataSource))
    extraction_status: Mapped[ExtractionStatus] = mapped_column(
        _enum(ExtractionStatus), default=ExtractionStatus.NOT_STARTED
    )
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    uploaded_by_role: Mapped[UserRole | None] = mapped_column(_enum(UserRole))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class UploadToken(Base):
    """A scoped, expiring upload link. Only the SHA-256 of the random token is stored, so a
    database leak does not yield working links. Only the usage counters change."""

    __tablename__ = "upload_tokens"
    __table_args__ = (
        CheckConstraint("token_sha256 ~ '^[0-9a-f]{64}$'", name="token_sha256_hex"),
        CheckConstraint("jsonb_typeof(document_types) = 'array'", name="document_types_array"),
        CheckConstraint("max_uploads >= 1 AND max_uploads <= 50", name="max_uploads_range"),
        CheckConstraint("use_count >= 0 AND use_count <= max_uploads", name="use_count_range"),
    )

    MUTABLE_COLUMNS = frozenset({"use_count", "last_used_at", "updated_at"})

    id: Mapped[uuid.UUID] = _pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("care_cases.id"), index=True)
    token_sha256: Mapped[str] = mapped_column(String(64), unique=True)
    document_types: Mapped[list[str]] = mapped_column(JSONB)
    max_uploads: Mapped[int] = mapped_column(Integer)
    use_count: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class DocumentExtraction(Base):
    """The validated AI output for one document, stored once and never changed. Human
    corrections are separate ExtractionRevision rows."""

    __tablename__ = "document_extractions"
    __table_args__ = (
        CheckConstraint("raw_output_sha256 ~ '^[0-9a-f]{64}$'", name="raw_output_sha256_hex"),
    )

    id: Mapped[uuid.UUID] = _pk()
    # One extraction per document; a failed attempt leaves no row and can be retried.
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evidence_documents.id"), unique=True)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("care_cases.id"), index=True)
    schema_version: Mapped[str] = mapped_column(String(40))
    provider: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(80))
    prompt_version: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    raw_output_sha256: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    actor_label: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = _created()


class ExtractionRevision(Base):
    """A human correction or confirmation layered over an extraction. Append-only: each
    revision holds only its own delta; current values are the original with revisions folded
    over it."""

    __tablename__ = "extraction_revisions"
    __table_args__ = (
        UniqueConstraint(
            "extraction_id",
            "revision_number",
            name="uq_extraction_revisions_extraction_number",
        ),
        CheckConstraint("revision_number > 0", name="revision_number_positive"),
        CheckConstraint("length(btrim(reason)) > 0", name="reason_required"),
    )

    id: Mapped[uuid.UUID] = _pk()
    extraction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_extractions.id"), index=True
    )
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("care_cases.id"))
    revision_number: Mapped[int] = mapped_column(Integer)
    corrections: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    confirmed_paths: Mapped[list[str]] = mapped_column(JSONB)
    reason: Mapped[str] = mapped_column(Text)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    actor_label: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = _created()


class ProviderResponse(Base):
    """A provider's answer to a queried flag. Append-only; the payer reviews it before
    any bucket changes (a response never moves money by itself)."""

    __tablename__ = "provider_responses"
    __table_args__ = (
        CheckConstraint("length(btrim(response_text)) > 0", name="text_required"),
        CheckConstraint(
            "corrected_amount IS NULL OR corrected_amount >= 0", name="corrected_non_negative"
        ),
        CheckConstraint(
            "(response_type = 'CORRECT') = (corrected_amount IS NOT NULL)",
            name="corrected_amount_iff_correct",
        ),
    )

    id: Mapped[uuid.UUID] = _pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("care_cases.id"), index=True)
    flag_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("billing_flags.id"), index=True)
    line_item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("bill_line_items.id"))
    provider_link_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("provider_links.id"), unique=True
    )
    response_type: Mapped[ProviderResponseType] = mapped_column(_enum(ProviderResponseType))
    response_text: Mapped[str] = mapped_column(Text)
    corrected_amount: Mapped[Decimal | None] = mapped_column(Money)
    currency: Mapped[str] = mapped_column(String(3))
    supporting_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("evidence_documents.id")
    )
    responder_label: Mapped[str] = mapped_column(String(120))
    actor_verification_method: Mapped[str] = mapped_column(String(60))
    responded_at: Mapped[datetime] = _created()


class ProviderLink(Base):
    """One question and one line, with only a hash of the bearer capability stored."""

    __tablename__ = "provider_links"
    __table_args__ = (
        CheckConstraint("token_sha256 ~ '^[0-9a-f]{64}$'", name="token_sha256_hex"),
        CheckConstraint("length(btrim(question)) > 0", name="question_required"),
        CheckConstraint("issued_amount > 0", name="issued_amount_positive"),
    )
    MUTABLE_COLUMNS = frozenset({"consumed_at", "revoked_at", "updated_at"})

    id: Mapped[uuid.UUID] = _pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("care_cases.id"), index=True)
    flag_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("billing_flags.id"), index=True)
    line_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bill_line_items.id"))
    token_sha256: Mapped[str] = mapped_column(String(64), unique=True)
    question: Mapped[str] = mapped_column(Text)
    issued_amount: Mapped[Decimal] = mapped_column(Money)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    @property
    def state(self) -> str:
        if self.revoked_at is not None:
            return "REVOKED"
        if self.expires_at <= datetime.now(UTC):
            return "EXPIRED"
        return "RESPONDED" if self.consumed_at is not None else "ACTIVE"


class ProviderDecision(Base):
    """Immutable payer decision. A proposal alone never changes financial state."""

    __tablename__ = "provider_decisions"
    __table_args__ = (
        CheckConstraint("length(btrim(note)) > 0", name="note_required"),
        CheckConstraint(
            "original_amount > 0 AND previous_amount >= 0 AND recognized_amount >= 0",
            name="amounts_non_negative",
        ),
        CheckConstraint(
            "recognized_amount = previous_amount + adjustment", name="adjustment_balance"
        ),
        CheckConstraint("decision = 'ACCEPT' OR adjustment = 0", name="non_accept_no_adjustment"),
    )

    id: Mapped[uuid.UUID] = _pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("care_cases.id"), index=True)
    response_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("provider_responses.id"), unique=True)
    line_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bill_line_items.id"))
    decision: Mapped[ProviderDecisionType] = mapped_column(_enum(ProviderDecisionType))
    note: Mapped[str] = mapped_column(Text)
    original_amount: Mapped[Decimal] = mapped_column(Money)
    previous_amount: Mapped[Decimal] = mapped_column(Money)
    recognized_amount: Mapped[Decimal] = mapped_column(Money)
    adjustment: Mapped[Decimal] = mapped_column(Money)
    currency: Mapped[str] = mapped_column(String(3))
    state_fingerprint: Mapped[str] = mapped_column(String(64))
    decided_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    actor_label: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = _created()


class ApprovalRecord(Base):
    """A human approval of an exact payable amount, with the bucket snapshot shown at
    approval time. Append-only. No payment may be created without one."""

    __tablename__ = "approval_records"
    __table_args__ = (
        Index(
            "uq_approval_records_case_fingerprint",
            "case_id",
            "state_fingerprint",
            unique=True,
            postgresql_where=text("state_fingerprint IS NOT NULL"),
        ),
        CheckConstraint("approved_amount > 0", name="amount_positive"),
        CheckConstraint("approved_amount <= payable_now", name="not_above_payable"),
        CheckConstraint(
            "bill_total = payable_now + queried + already_paid", name="buckets_balance"
        ),
        CheckConstraint("queried >= 0 AND already_paid >= 0", name="buckets_non_negative"),
    )

    id: Mapped[uuid.UUID] = _pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("care_cases.id"), index=True)
    approved_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    actor_label: Mapped[str] = mapped_column(String(120))
    currency: Mapped[str] = mapped_column(String(3))
    approved_amount: Mapped[Decimal] = mapped_column(Money)
    bill_total: Mapped[Decimal] = mapped_column(Money)
    payable_now: Mapped[Decimal] = mapped_column(Money)
    queried: Mapped[Decimal] = mapped_column(Money)
    already_paid: Mapped[Decimal] = mapped_column(Money)
    payee_label: Mapped[str] = mapped_column(String(200))
    provider_merchant_ref: Mapped[str | None] = mapped_column(String(64))
    state_fingerprint: Mapped[str | None] = mapped_column(String(64))
    account_binding: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    composition: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    purpose: Mapped[str | None] = mapped_column(String(1000))
    # Highest ledger seq included in the snapshot.
    ledger_seq: Mapped[int] = mapped_column(BigInteger)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()


class PayPalInvoiceRef(Base):
    """Reference to a PayPal invoice created for an approval. Status and amount due are
    copied from a PayPal GET (authoritative); the other columns never change."""

    __tablename__ = "paypal_invoice_refs"
    __table_args__ = (
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_iso"),
        CheckConstraint("invoice_total > 0", name="total_positive"),
        CheckConstraint("amount_due >= 0 AND amount_due <= invoice_total", name="due_in_range"),
    )

    MUTABLE_COLUMNS = frozenset({"invoice_status", "amount_due", "last_verified_at", "updated_at"})

    id: Mapped[uuid.UUID] = _pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("care_cases.id"), index=True)
    # One invoice per approval (PayPal-Request-Id does not deduplicate invoice creation).
    approval_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("approval_records.id"), unique=True)
    paypal_invoice_id: Mapped[str] = mapped_column(String(64), unique=True)
    merchant_account_ref: Mapped[str] = mapped_column(String(64))
    currency: Mapped[str] = mapped_column(String(3))
    invoice_total: Mapped[Decimal] = mapped_column(Money)
    amount_due: Mapped[Decimal] = mapped_column(Money)
    invoice_status: Mapped[PayPalInvoiceStatus] = mapped_column(_enum(PayPalInvoiceStatus))
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class PayPalPaymentRef(Base):
    """A transaction on a PayPal invoice, recorded only after a PayPal GET. Append-only."""

    __tablename__ = "paypal_payment_refs"
    __table_args__ = (
        Index(
            "uq_paypal_payment_capture_global",
            "paypal_transaction_id",
            unique=True,
            postgresql_where=text("payment_source = 'PAYPAL'"),
        ),
        UniqueConstraint(
            "invoice_ref_id", "paypal_transaction_id", name="uq_paypal_payment_refs_invoice_txn"
        ),
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint(
            "(payment_source = 'EXTERNAL') = (external_payment_id IS NOT NULL)",
            name="external_link",
        ),
    )

    id: Mapped[uuid.UUID] = _pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("care_cases.id"), index=True)
    invoice_ref_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("paypal_invoice_refs.id"), index=True
    )
    paypal_transaction_id: Mapped[str] = mapped_column(String(64))
    payment_source: Mapped[PayPalPaymentSource] = mapped_column(_enum(PayPalPaymentSource))
    external_payment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("external_payments.id")
    )
    amount: Mapped[Decimal] = mapped_column(Money)
    currency: Mapped[str] = mapped_column(String(3))
    paypal_status: Mapped[str] = mapped_column(String(40))
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()


class PayPalAccountBinding(Base):
    __tablename__ = "paypal_account_bindings"
    id: Mapped[uuid.UUID] = _pk()
    client_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    merchant_ref: Mapped[str] = mapped_column(String(64))
    capture_ref: Mapped[str] = mapped_column(String(64))
    verified_at: Mapped[datetime] = _created()


class PaymentOperation(Base):
    MUTABLE_COLUMNS = frozenset(
        {"state", "stage", "paypal_invoice_id", "error_code", "stages", "updated_at"}
    )
    __tablename__ = "payment_operations"
    id: Mapped[uuid.UUID] = _pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("care_cases.id"), unique=True)
    approval_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("approval_records.id"), unique=True)
    state: Mapped[str] = mapped_column(String(40))
    stage: Mapped[str] = mapped_column(String(80))
    paypal_invoice_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    error_code: Mapped[str | None] = mapped_column(String(60))
    stages: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class PayPalWebhookEvent(Base):
    """Verified notification receipt, never the raw sensitive webhook payload."""

    __tablename__ = "paypal_webhook_events"
    MUTABLE_COLUMNS = frozenset({"outcome", "attempts", "error_code", "processed_at", "updated_at"})
    id: Mapped[uuid.UUID] = _pk()
    event_id: Mapped[str] = mapped_column(String(100), unique=True)
    event_type: Mapped[str] = mapped_column(String(80))
    invoice_id: Mapped[str | None] = mapped_column(String(64))
    payload_sha256: Mapped[str] = mapped_column(String(64))
    outcome: Mapped[str] = mapped_column(String(40))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(60))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class FamilyMembership(Base):
    __tablename__ = "family_memberships"
    __table_args__ = (
        UniqueConstraint("case_id", "user_id", name="uq_family_membership_case_user"),
        CheckConstraint("role IN ('PAYER', 'VIEWER', 'PATIENT')", name="role_valid"),
        CheckConstraint(
            "role = 'PAYER' OR (NOT can_review AND NOT can_approve)", name="role_permissions"
        ),
    )
    MUTABLE_COLUMNS = frozenset({"role", "can_review", "can_approve", "active", "updated_at"})
    id: Mapped[uuid.UUID] = _pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("care_cases.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(20))
    can_review: Mapped[bool] = mapped_column(Boolean, default=False)
    can_approve: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class FamilyInvitation(Base):
    __tablename__ = "family_invitations"
    __table_args__ = (
        CheckConstraint("role IN ('PAYER', 'VIEWER', 'PATIENT')", name="role_valid"),
        CheckConstraint(
            "role = 'PAYER' OR (NOT can_review AND NOT can_approve)", name="role_permissions"
        ),
    )
    MUTABLE_COLUMNS = frozenset({"accepted_by", "accepted_at", "revoked_at"})
    id: Mapped[uuid.UUID] = _pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("care_cases.id"), index=True)
    recipient_email: Mapped[str] = mapped_column(String(254))
    token_sha256: Mapped[str] = mapped_column(String(64), unique=True)
    role: Mapped[str] = mapped_column(String(20))
    can_review: Mapped[bool] = mapped_column(Boolean, default=False)
    can_approve: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    accepted_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()


class FamilyLedgerEntry(Base):
    """Internal contribution records. Never a hospital payment or PayPal credit."""

    __tablename__ = "family_ledger_entries"
    __table_args__ = (
        UniqueConstraint("case_id", "request_id", name="uq_family_ledger_request"),
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("entry_type IN ('CONTRIBUTION', 'REVERSAL')", name="type_valid"),
        CheckConstraint(
            "(entry_type = 'REVERSAL') = (reverses_id IS NOT NULL)", name="reversal_reference"
        ),
    )
    id: Mapped[uuid.UUID] = _pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("care_cases.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    entry_type: Mapped[str] = mapped_column(String(20))
    amount: Mapped[Decimal] = mapped_column(Money)
    currency: Mapped[str] = mapped_column(String(3))
    contributed_on: Mapped[date] = mapped_column(Date)
    reference: Mapped[str | None] = mapped_column(String(120))
    reverses_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("family_ledger_entries.id"), unique=True
    )
    request_id: Mapped[str] = mapped_column(String(80))
    note: Mapped[str] = mapped_column(Text)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _created()


class FamilyAllocationPlan(Base):
    __tablename__ = "family_allocation_plans"
    __table_args__ = (
        UniqueConstraint("case_id", "request_id", name="uq_family_allocation_request"),
        UniqueConstraint("line_item_id", "version", name="uq_family_allocation_line_version"),
        CheckConstraint("version > 0", name="version_positive"),
    )
    id: Mapped[uuid.UUID] = _pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("care_cases.id"), index=True)
    line_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bill_line_items.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3))
    source_amount: Mapped[Decimal] = mapped_column(Money)
    source_fingerprint: Mapped[str] = mapped_column(String(64))
    shares: Mapped[list[dict]] = mapped_column(JSONB)
    request_id: Mapped[str] = mapped_column(String(80))
    note: Mapped[str] = mapped_column(Text)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _created()


class FamilyNotification(Base):
    __tablename__ = "family_notifications"
    __table_args__ = (
        UniqueConstraint("user_id", "audit_event_id", name="uq_family_notification_event"),
    )
    MUTABLE_COLUMNS = frozenset({"read_at"})
    id: Mapped[uuid.UUID] = _pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("care_cases.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    audit_event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("audit_events.id"))
    event_type: Mapped[str] = mapped_column(String(80))
    actor_label: Mapped[str] = mapped_column(String(120))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()


APPEND_ONLY = (
    FamilyLedgerEntry,
    FamilyAllocationPlan,
    PayPalAccountBinding,
    LedgerEntry,
    AuditEvent,
    ProviderResponse,
    ProviderDecision,
    ApprovalRecord,
    PayPalPaymentRef,
    DocumentExtraction,
    ExtractionRevision,
)
FULLY_IMMUTABLE = (Bill,)
PARTLY_IMMUTABLE = (
    FamilyMembership,
    FamilyInvitation,
    FamilyNotification,
    PayPalWebhookEvent,
    PaymentOperation,
    BillLineItem,
    ExternalPayment,
    EvidenceDocument,
    PayPalInvoiceRef,
    UploadToken,
    ProviderLink,
)
NO_DELETE = (Bill, *PARTLY_IMMUTABLE, *APPEND_ONLY)


@event.listens_for(Session, "before_flush")
def _guard_immutable(session: Session, _ctx: object, _instances: object) -> None:
    """ORM-level guard. Postgres triggers (see migration) enforce the same rules."""
    for obj in session.deleted:
        if isinstance(obj, NO_DELETE):
            raise ImmutableRecordError(f"{type(obj).__name__} rows cannot be deleted")
    for obj in session.dirty:
        if isinstance(obj, APPEND_ONLY + FULLY_IMMUTABLE):
            if session.is_modified(obj, include_collections=False):
                raise ImmutableRecordError(f"{type(obj).__name__} rows are immutable")
        elif isinstance(obj, PARTLY_IMMUTABLE):
            state = inspect(obj)
            for attr in state.mapper.column_attrs:
                if attr.key in obj.MUTABLE_COLUMNS:
                    continue
                if state.attrs[attr.key].history.has_changes():
                    raise ImmutableRecordError(
                        f"{type(obj).__name__}.{attr.key} is an original value and cannot change"
                    )
