"""Pydantic request/response schemas. Money crosses the API only as decimal strings."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, PlainSerializer, field_validator

from app.money import MoneyError, money, quantity, to_str
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
    ProviderDecisionType,
    ProviderResponseType,
    UserRole,
)


def _money_in(v: object) -> Decimal:
    if isinstance(v, Decimal):
        return money(v)
    if not isinstance(v, str):
        raise ValueError('money must be a decimal string such as "2000.00"')
    try:
        return money(v)
    except MoneyError as exc:
        raise ValueError(str(exc)) from exc


def _qty_in(v: object) -> Decimal:
    if isinstance(v, Decimal):
        return quantity(v)
    if not isinstance(v, str):
        raise ValueError('quantity must be a decimal string such as "1"')
    try:
        return quantity(v)
    except MoneyError as exc:
        raise ValueError(str(exc)) from exc


def _confidence_in(v: object) -> Decimal | None:
    if v is None:
        return None
    if not isinstance(v, str | Decimal):
        raise ValueError("confidence must be a decimal string between 0 and 1")
    d = Decimal(v)
    if not (0 <= d <= 1) or d.as_tuple().exponent < -3:
        raise ValueError("confidence must be between 0 and 1 with at most 3 decimal places")
    return d


MoneyIn = Annotated[Decimal, BeforeValidator(_money_in)]
QuantityIn = Annotated[Decimal, BeforeValidator(_qty_in)]
ConfidenceIn = Annotated[Decimal | None, BeforeValidator(_confidence_in)]
MoneyOut = Annotated[Decimal, PlainSerializer(to_str, return_type=str)]
DecimalOut = Annotated[Decimal, PlainSerializer(lambda d: format(d, "f"), return_type=str)]
Currency = Annotated[str, Field(pattern=r"^[A-Za-z]{3}$")]
Note = Annotated[str, Field(min_length=1, max_length=2000)]


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------- requests


class CaseCreate(BaseModel):
    patient_alias: Annotated[str, Field(min_length=1, max_length=120)]
    currency: Currency
    case_reference: Annotated[str | None, Field(max_length=40)] = None
    episode_title: Annotated[str | None, Field(max_length=200)] = None
    clinical_context: Annotated[str | None, Field(max_length=2000)] = None


class LineCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    line_number: Annotated[int, Field(ge=1)]
    description_raw: Annotated[str, Field(min_length=1, max_length=2000)]
    code: Annotated[str | None, Field(max_length=40)] = None
    line_total: MoneyIn
    service_date: date | None = None
    quantity: QuantityIn | None = None
    unit_price: MoneyIn | None = None
    extraction_confidence: ConfidenceIn = None
    source_page: Annotated[int | None, Field(ge=1)] = None
    source_text: Annotated[str | None, Field(max_length=4000)] = None

    @field_validator("code")
    @classmethod
    def _reserved_code(cls, value):
        if value is not None and value.strip().upper() == "CAREDIRECT_TAX":
            raise ValueError("reserved internal accounting code")
        return value


class BillCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_name: Annotated[str, Field(min_length=1, max_length=200)]
    currency: Currency
    lines: Annotated[list[LineCreate], Field(min_length=1, max_length=500)]
    bill_number: Annotated[str | None, Field(max_length=80)] = None
    bill_date: date | None = None
    printed_total: MoneyIn | None = None
    printed_advance_paid: MoneyIn | None = None
    printed_balance_due: MoneyIn | None = None
    source_document_ref: Annotated[str | None, Field(max_length=200)] = None


class ExternalPaymentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: PaymentMethod
    amount: MoneyIn
    currency: Currency
    paid_on: date | None = None
    reference: Annotated[str | None, Field(max_length=120)] = None
    payee_name: Annotated[str | None, Field(max_length=200)] = None
    bill_id: uuid.UUID | None = None
    source_document_ref: Annotated[str | None, Field(max_length=200)] = None


class QueryLine(BaseModel):
    reason: Note
    flag_id: uuid.UUID | None = None


class AcceptLine(BaseModel):
    note: Annotated[str | None, Field(max_length=2000)] = None


class NoteBody(BaseModel):
    note: Note


class FlagStatusChange(BaseModel):
    status: FlagStatus
    note: Note


class CaseTransition(BaseModel):
    status: CaseStatus


class UploadLinkCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_types: Annotated[list[DocumentType], Field(min_length=1, max_length=6)]
    max_uploads: Annotated[int, Field(ge=1, le=50)] = 5
    ttl_minutes: Annotated[int | None, Field(ge=1)] = None


FieldPath = Annotated[str, Field(min_length=1, max_length=80)]


class BoundingBoxIn(BaseModel):
    """Normalised page coordinates as decimal strings, e.g. "0.100"."""

    model_config = ConfigDict(extra="forbid")

    x0: Annotated[str, Field(max_length=10)]
    y0: Annotated[str, Field(max_length=10)]
    x1: Annotated[str, Field(max_length=10)]
    y1: Annotated[str, Field(max_length=10)]


class CorrectionSourceIn(BaseModel):
    """Where a corrected value appears. The document is always the extraction's own."""

    model_config = ConfigDict(extra="forbid")

    page: Annotated[int, Field(ge=1, le=1000)]
    snippet: Annotated[str | None, Field(max_length=500)] = None
    bbox: BoundingBoxIn | None = None


class CorrectionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: FieldPath
    # A string, never a JSON number: "1200.00". Null (or blank) clears the value.
    value: Annotated[str | None, Field(max_length=600)]
    source: CorrectionSourceIn | None = None


class RevisionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    corrections: Annotated[list[CorrectionIn], Field(max_length=600)] = []
    confirmed_paths: Annotated[list[FieldPath], Field(max_length=600)] = []
    reason: Annotated[str, Field(min_length=1, max_length=2000)]


# ---------------------------------------------------------------- responses


class UserOut(_Out):
    id: uuid.UUID
    display_name: str
    role: UserRole
    is_demo: bool


class BucketsOut(_Out):
    insurance_present: bool = False
    currency: str
    bill_total: MoneyOut
    payable_now: MoneyOut
    queried: MoneyOut
    already_paid: MoneyOut
    pending_review: MoneyOut
    invariant_holds: bool
    consistent: bool
    issues: list[str]
    original_bill_total: MoneyOut
    adjustments: MoneyOut
    net_bill_total: MoneyOut


class LineItemOut(_Out):
    id: uuid.UUID
    bill_id: uuid.UUID
    line_number: int
    description_raw: str
    code: str | None
    service_date: date | None
    quantity: DecimalOut | None
    unit_price: MoneyOut | None
    line_total: MoneyOut
    recognized_amount: MoneyOut
    currency: str
    source_type: DataSource
    extraction_confidence: DecimalOut | None
    source_page: int | None
    source_text: str | None
    status: LineItemStatus
    status_note: str | None


class BillOut(_Out):
    id: uuid.UUID
    provider_name: str
    bill_number: str | None
    bill_date: date | None
    currency: str
    printed_total: MoneyOut | None
    printed_advance_paid: MoneyOut | None
    printed_balance_due: MoneyOut | None
    source_type: DataSource
    source_document_ref: str | None
    line_items: list[LineItemOut]


class ExternalPaymentOut(_Out):
    id: uuid.UUID
    bill_id: uuid.UUID | None
    method: PaymentMethod
    amount: MoneyOut
    currency: str
    paid_on: date | None
    reference: str | None
    payee_name: str | None
    source_type: DataSource
    status: ExternalPaymentStatus
    match_basis: dict[str, Any] | None
    status_note: str | None


class FlagOut(_Out):
    id: uuid.UUID
    bill_id: uuid.UUID | None
    external_payment_id: uuid.UUID | None
    flag_type: FlagType
    line_item_ids: list[str]
    amount_involved: MoneyOut | None
    explanation: str
    evidence: dict[str, Any]
    rule_id: str
    rule_version: str
    status: FlagStatus
    resolution_note: str | None
    resolved_at: datetime | None


class LedgerEntryOut(_Out):
    id: uuid.UUID
    seq: int
    entry_type: LedgerEntryType
    amount: MoneyOut
    currency: str
    bill_id: uuid.UUID | None
    line_item_id: uuid.UUID | None
    external_payment_id: uuid.UUID | None
    flag_id: uuid.UUID | None
    reason: str
    actor_label: str
    created_at: datetime


class AuditEventOut(_Out):
    id: uuid.UUID
    seq: int
    actor_label: str
    event_type: str
    entity_type: str
    entity_id: uuid.UUID | None
    ledger_entry_id: uuid.UUID | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    details: dict[str, Any]
    created_at: datetime


class CaseSummaryOut(BaseModel):
    id: uuid.UUID
    case_reference: str
    patient_alias: str
    currency: str
    status: CaseStatus
    is_demo: bool
    created_at: datetime
    buckets: BucketsOut
    episode_title: str | None = None
    clinical_context: str | None = None


class ApprovalReadinessOut(BaseModel):
    """Informational only. There is no payment endpoint in this slice."""

    ready: bool
    blockers: list[str]


class CaseDetailOut(CaseSummaryOut):
    family_permissions: dict[str, Any] = Field(default_factory=dict)
    payer: UserOut
    bills: list[BillOut]
    external_payments: list[ExternalPaymentOut]
    flags: list[FlagOut]
    approval_readiness: ApprovalReadinessOut


class RunChecksOut(BaseModel):
    flags_created: list[FlagOut]


class UploadLinkOut(BaseModel):
    """Returned once, at creation. The token is not stored and cannot be shown again."""

    id: uuid.UUID
    case_id: uuid.UUID
    token: str
    document_types: list[DocumentType]
    max_uploads: int
    expires_at: datetime


class UploadLinkInfoOut(BaseModel):
    """What the uploader may see. No case, patient or provider data."""

    document_types: list[DocumentType]
    uploads_remaining: int
    expires_at: datetime
    max_upload_bytes: int
    max_pages: int
    allowed_mime_types: list[str]


class UploadReceiptOut(BaseModel):
    """What the uploader sees after an upload. No case id and no storage key."""

    document_id: uuid.UUID
    document_type: DocumentType
    mime_type: str
    file_size: int
    page_count: int | None
    sha256: str
    uploads_remaining: int


class SourceOut(BaseModel):
    document_id: uuid.UUID
    page: int
    snippet: str | None
    bbox: dict[str, str] | None


class FieldOut(BaseModel):
    """One extracted field with its current value. Money, quantity and confidence are decimal
    strings. `needs_review` is decided by the API; clients only display it."""

    path: str
    label: str
    group: Literal["document", "line_item", "totals", "receipt", "insurance"]
    line_index: int | None
    line_number: int | None
    name: str
    kind: Literal["text", "money", "quantity", "date", "currency", "payment_method"]
    value: str | None
    original_value: str | None
    model_confidence: str | None
    source: SourceOut | None
    state: Literal["extracted", "confirmed", "corrected"]
    needs_review: bool


class RevisionCorrectionOut(BaseModel):
    path: str
    value: str | None
    source: SourceOut | None


class RevisionOut(BaseModel):
    revision_number: int
    corrections: list[RevisionCorrectionOut]
    confirmed_paths: list[str]
    reason: str
    actor_label: str
    created_at: datetime


class PromotedToOut(BaseModel):
    bill_id: uuid.UUID | None
    external_payment_id: uuid.UUID | None


class ExtractionViewOut(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    case_id: uuid.UUID
    document_type: DocumentType
    extracted_document_type: DocumentType
    schema_version: str
    provider: str
    model: str
    prompt_version: str
    is_mock: bool
    low_confidence_threshold: str
    created_at: datetime
    actor_label: str
    fields: list[FieldOut]
    review_required: list[str]
    promotion_blockers: list[str]
    can_promote: bool
    promoted_to: PromotedToOut | None
    revisions: list[RevisionOut]
    original_payload: dict[str, Any]


class PromoteOut(BaseModel):
    bill: BillOut | None
    external_payment: ExternalPaymentOut | None


class DocumentOut(_Out):
    """A stored document. The private storage key is never exposed."""

    id: uuid.UUID
    case_id: uuid.UUID
    document_type: DocumentType
    mime_type: str
    file_size: int
    page_count: int | None
    sha256: str
    source_type: DataSource
    extraction_status: ExtractionStatus
    uploaded_by_role: UserRole | None
    created_at: datetime


class ProviderLinkCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    line_item_id: uuid.UUID
    question: Note
    ttl_minutes: Annotated[int, Field(ge=1, le=1440)] = 1440


class ProviderLinkOut(_Out):
    id: uuid.UUID
    case_id: uuid.UUID
    flag_id: uuid.UUID
    line_item_id: uuid.UUID
    token: str
    expires_at: datetime


class ProviderLinkHistoryOut(_Out):
    id: uuid.UUID
    flag_id: uuid.UUID
    line_item_id: uuid.UUID
    question: str
    expires_at: datetime
    consumed_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime
    state: Literal["ACTIVE", "RESPONDED", "REVOKED", "EXPIRED"]


class ProviderResponseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    response_type: ProviderResponseType
    response_text: Note
    corrected_amount: MoneyIn | None = None
    responder_label: Annotated[str, Field(min_length=1, max_length=120)]


class ProviderResponseOut(_Out):
    id: uuid.UUID
    case_id: uuid.UUID
    flag_id: uuid.UUID
    line_item_id: uuid.UUID | None
    provider_link_id: uuid.UUID | None
    response_type: ProviderResponseType
    response_text: str
    corrected_amount: MoneyOut | None
    currency: str
    responder_label: str
    actor_verification_method: str
    responded_at: datetime


class ProviderDecisionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: ProviderDecisionType
    note: Note
    state_fingerprint: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class ProviderPortalResponseOut(_Out):
    """The response receipt omits the case and provider-link identifiers."""

    id: uuid.UUID
    response_type: ProviderResponseType
    response_text: str
    corrected_amount: MoneyOut | None
    currency: str
    responder_label: str
    actor_verification_method: str
    responded_at: datetime


class ProviderDecisionOut(_Out):
    id: uuid.UUID
    case_id: uuid.UUID
    response_id: uuid.UUID
    line_item_id: uuid.UUID
    decision: ProviderDecisionType
    note: str
    original_amount: MoneyOut
    previous_amount: MoneyOut
    recognized_amount: MoneyOut
    adjustment: MoneyOut
    currency: str
    state_fingerprint: str
    decided_by: uuid.UUID
    actor_label: str
    created_at: datetime


class ProviderWorkflowOut(BaseModel):
    links: list[ProviderLinkHistoryOut]
    responses: list[ProviderResponseOut]
    decisions: list[ProviderDecisionOut]


class ProviderLineOut(BaseModel):
    id: uuid.UUID
    description_raw: str
    line_total: MoneyOut
    recognized_amount: MoneyOut
    source_page: int | None
    source_text: str | None


class ProviderFlagOut(BaseModel):
    id: uuid.UUID
    explanation: str


class ProviderPortalOut(BaseModel):
    provider_name: str
    currency: str
    question: str
    line: ProviderLineOut
    flag: ProviderFlagOut
    expires_at: datetime
    state: Literal["AWAITING_RESPONSE", "RESPONDED"]
    response: ProviderPortalResponseOut | None


class ProviderPreviewOut(BaseModel):
    response_id: uuid.UUID
    case_id: uuid.UUID
    line_item_id: uuid.UUID
    currency: str
    original_amount: MoneyOut
    current_amount: MoneyOut
    proposed_amount: MoneyOut
    adjustment: MoneyOut
    before: BucketsOut
    after: BucketsOut
    state_fingerprint: str
    can_accept: bool


# ---------------------------------------------------------------- Care Episode Intelligence


class EpisodeDetails(BaseModel):
    model_config = ConfigDict(extra="forbid")
    episode_title: Annotated[str, Field(min_length=1, max_length=200)]
    clinical_context: Annotated[str | None, Field(max_length=2000)] = None


class EpisodeAnalyze(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input_fingerprint: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class EpisodeDocumentOut(BaseModel):
    id: uuid.UUID
    name: str
    category: str
    document_type: str
    amount: str | None
    date: str | None
    is_overlapping: bool = False
    overlap_note: str | None = None
    source_ref: str | None = None
    source_available: bool = False
    provider: str | None = None
    currency: str | None = None
    patient_reference: str | None = None
    extraction_status: str = "MANUAL"
    review_state: str = "recorded"
    payment_status: str | None = None
    is_recorded: bool = False
    is_synthetic: bool = False
    uploaded_at: str | None = None
    date_basis: str = "unknown"
    affinity_status: str = "unknown"
    affinity_reason: str = "Membership is not verified."
    lines: list[dict[str, Any]] = Field(default_factory=list)
    sources: list[dict[str, Any]] = Field(default_factory=list)


class EpisodeTimelineEventOut(BaseModel):
    id: str
    event_date: str | None
    event_type: str
    title: str
    detail: str
    amount: str | None = None
    currency: str | None = None
    document_id: str | None = None
    flag_id: str | None = None
    status_tone: str = "neutral"
    date_basis: str = "recorded_at"
    sources: list[dict[str, Any]] = Field(default_factory=list)


class EpisodeOverlapOut(BaseModel):
    overlap_type: str
    title: str
    description: str
    amount: str
    currency: str
    involved_document_ids: list[str] = []
    line_item_ids: list[str] = []
    sources: list[dict[str, Any]] = Field(default_factory=list)


class CareEpisodeOut(BaseModel):
    case_id: uuid.UUID
    case_reference: str
    patient_alias: str
    episode_title: str
    clinical_context: str | None
    currency: str
    total_billed: str
    overlap_deductions: str
    net_episode_total: str
    payable_now: str
    queried: str
    already_paid: str
    documents: list[EpisodeDocumentOut]
    timeline: list[EpisodeTimelineEventOut]
    overlaps: list[EpisodeOverlapOut]
    ai_insights: dict[str, Any]
    blockers: list[str] = []
    potential_overlap_amount: str = "0.00"
    recorded_bill_total: str = "0.00"
    confirmed_adjustments: str = "0.00"
    warnings: list[str] = Field(default_factory=list)
    input_fingerprint: str = ""
    ai_configured: bool = False
