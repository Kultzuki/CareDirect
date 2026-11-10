// TypeScript mirror of the FastAPI response shapes this app reads (api/app/schemas.py).
// Money, quantity and confidence are decimal STRINGS. Never convert them to numbers.

export type UserRole = "PAYER" | "RELATIVE" | "PROVIDER_STAFF" | "ADMIN";
export type InsuranceDocumentType = "INSURANCE_PREAUTH" | "INSURANCE_SETTLEMENT" | "INSURER_PAYMENT";
export type DocumentType = "BILL" | "ESTIMATE" | "RECEIPT" | "PROVIDER_SUPPORTING" | "OTHER" | InsuranceDocumentType;
export type UploadableDocumentType = "BILL" | "ESTIMATE" | "RECEIPT" | InsuranceDocumentType;
export type ExtractionStatus = "NOT_STARTED" | "EXTRACTED" | "FAILED";
export type PaymentMethod = "UPI" | "CASH" | "CARD" | "BANK_TRANSFER" | "OTHER";
export type CaseStatus =
  | "DRAFT"
  | "UNDER_REVIEW"
  | "AWAITING_PROVIDER"
  | "READY_FOR_APPROVAL"
  | "RECONCILIATION_REQUIRED"
  | "CLOSED";
export type LineItemStatus = "PENDING_REVIEW" | "ACCEPTED" | "QUERIED";
export type DataSource = "MANUAL_ENTRY" | "SEEDED_SYNTHETIC" | "AI_EXTRACTED";

export interface UserOut {
  id: string;
  display_name: string;
  role: UserRole;
  is_demo: boolean;
}

export interface BucketsOut {
  insurance_present: boolean;
  currency: string;
  bill_total: string;
  original_bill_total: string;
  adjustments: string;
  net_bill_total: string;
  payable_now: string;
  queried: string;
  already_paid: string;
  pending_review: string;
  invariant_holds: boolean;
  consistent: boolean;
  issues: string[];
}

export interface CaseSummaryOut {
  id: string;
  case_reference: string;
  patient_alias: string;
  currency: string;
  status: CaseStatus;
  is_demo: boolean;
  created_at: string;
  buckets: BucketsOut;
  episode_title?: string | null;
  clinical_context?: string | null;
}

export interface LineItemOut {
  id: string;
  bill_id: string;
  line_number: number;
  description_raw: string;
  code: string | null;
  service_date: string | null;
  quantity: string | null;
  unit_price: string | null;
  line_total: string;
  recognized_amount: string;
  currency: string;
  source_type: DataSource;
  extraction_confidence: string | null;
  source_page: number | null;
  source_text: string | null;
  status: LineItemStatus;
  status_note: string | null;
}

export interface BillOut {
  id: string;
  provider_name: string;
  bill_number: string | null;
  bill_date: string | null;
  currency: string;
  printed_total: string | null;
  printed_advance_paid: string | null;
  printed_balance_due: string | null;
  source_type: DataSource;
  source_document_ref: string | null;
  line_items: LineItemOut[];
}

export interface ExternalPaymentOut {
  id: string;
  bill_id: string | null;
  method: PaymentMethod;
  amount: string;
  currency: string;
  paid_on: string | null;
  reference: string | null;
  payee_name: string | null;
  source_type: DataSource;
  status: string;
  match_basis?: { problems?: string[]; limitations?: string[]; sources?: {source_document_ref?: string | null}[] } | null;
  status_note?: string | null;
}

export interface CaseDetailOut extends CaseSummaryOut {
  family_permissions: { can_view: boolean; can_review: boolean; can_approve: boolean; can_manage: boolean; can_contribute: boolean; role: string | null };
  payer: UserOut;
  bills: BillOut[];
  external_payments: ExternalPaymentOut[];
  flags: FlagOut[];
  approval_readiness: { ready: boolean; blockers: string[] };
}

export interface FlagOut {
  id: string;
  bill_id: string | null;
  flag_type: string;
  line_item_ids: string[];
  amount_involved: string | null;
  explanation: string;
  evidence: Record<string, unknown>;
  status: "OPEN" | "SUBMITTED_TO_PROVIDER" | "PROVIDER_RESPONDED" | "RESOLVED" | "DISMISSED";
  resolution_note: string | null;
  resolved_at: string | null;
}

export interface AuditEventOut {
  id: string;
  seq: number;
  actor_label: string;
  event_type: string;
  entity_type: string;
  created_at: string;
  details: Record<string, unknown>;
}

export interface UploadLinkOut {
  id: string;
  case_id: string;
  token: string;
  document_types: UploadableDocumentType[];
  max_uploads: number;
  expires_at: string;
}

export interface UploadLinkInfoOut {
  document_types: UploadableDocumentType[];
  uploads_remaining: number;
  expires_at: string;
  max_upload_bytes: number;
  max_pages: number;
  allowed_mime_types: string[];
}

export interface UploadReceiptOut {
  document_id: string;
  document_type: DocumentType;
  mime_type: string;
  file_size: number;
  page_count: number | null;
  sha256: string;
  uploads_remaining: number;
}

export interface DocumentOut {
  id: string;
  case_id: string;
  document_type: DocumentType;
  mime_type: string;
  file_size: number;
  page_count: number | null;
  sha256: string;
  source_type: DataSource;
  extraction_status: ExtractionStatus;
  uploaded_by_role: UserRole | null;
  created_at: string;
}

export type FieldGroup = "document" | "line_item" | "totals" | "receipt" | "insurance";
export type FieldKind = "text" | "money" | "quantity" | "date" | "currency" | "payment_method";
export type FieldState = "extracted" | "confirmed" | "corrected";

export interface SourceOut {
  document_id: string;
  page: number;
  snippet: string | null;
  bbox: Record<string, string> | null;
}

export interface FieldOut {
  path: string;
  label: string;
  group: FieldGroup;
  line_index: number | null;
  line_number: number | null;
  name: string;
  kind: FieldKind;
  value: string | null;
  original_value: string | null;
  model_confidence: string | null;
  source: SourceOut | null;
  state: FieldState;
  needs_review: boolean;
}

export interface RevisionCorrectionOut {
  path: string;
  value: string | null;
  source: SourceOut | null;
}

export interface RevisionOut {
  revision_number: number;
  corrections: RevisionCorrectionOut[];
  confirmed_paths: string[];
  reason: string;
  actor_label: string;
  created_at: string;
}

export interface PromotedToOut {
  bill_id: string | null;
  external_payment_id: string | null;
}

/** The API's extraction view without `original_payload`, which this app never renders. */
export interface ExtractionViewOut {
  id: string;
  document_id: string;
  case_id: string;
  document_type: DocumentType;
  extracted_document_type: DocumentType;
  schema_version: string;
  provider: string;
  model: string;
  prompt_version: string;
  is_mock: boolean;
  low_confidence_threshold: string;
  created_at: string;
  actor_label: string;
  fields: FieldOut[];
  review_required: string[];
  promotion_blockers: string[];
  can_promote: boolean;
  promoted_to: PromotedToOut | null;
  revisions: RevisionOut[];
}

export interface PromoteOut {
  bill: BillOut | null;
  external_payment: ExternalPaymentOut | null;
}

/** The part of an extraction view the client-side review form needs and nothing more. */
export interface ReviewViewData {
  document_type: DocumentType;
  id: string;
  fields: FieldOut[];
  review_required: string[];
  promotion_blockers: string[];
  can_promote: boolean;
}

// ---- Request bodies ----

export interface CorrectionSourceIn {
  page: number;
  snippet: string | null;
}

export interface CorrectionIn {
  path: string;
  value: string | null;
  source: CorrectionSourceIn | null;
}

export interface RevisionCreate {
  corrections: CorrectionIn[];
  confirmed_paths: string[];
  reason: string;
}

// ---- Care Episode Intelligence ----

export interface EpisodeFieldSource {
  path: string;
  state: string;
  needs_review?: boolean;
  source: { document_id?: string; page: number | null; snippet?: string | null } | null;
}

export interface EpisodeLine {
  id: string;
  ledger_line_id: string | null;
  line_number: number;
  description: string | null;
  service_date: string | null;
  quantity: string | null;
  code: string | null;
  unit_price: string | null;
  line_total: string | null;
  sources: EpisodeFieldSource[];
}

export interface EpisodeDocumentOut {
  id: string;
  name: string;
  category: string;
  document_type: string;
  amount: string | null;
  date: string | null;
  is_overlapping: boolean;
  overlap_note: string | null;
  source_ref: string | null;
  source_available: boolean;
  provider: string | null;
  currency: string | null;
  extraction_status: string;
  review_state: string;
  is_recorded: boolean;
  is_synthetic: boolean;
  date_basis: string;
  affinity_status: string;
  affinity_reason: string;
  lines: EpisodeLine[];
  sources: EpisodeFieldSource[];
}

export interface EpisodeTimelineEventOut {
  id: string;
  event_date: string | null;
  event_type: string;
  title: string;
  detail: string;
  amount: string | null;
  currency: string | null;
  document_id: string | null;
  flag_id: string | null;
  status_tone: "neutral" | "warning" | "success" | "info";
  date_basis: string;
  sources: EpisodeFieldSource[];
}

export interface EpisodeOverlapOut {
  overlap_type: string;
  title: string;
  description: string;
  amount: string;
  currency: string;
  involved_document_ids: string[];
  line_item_ids: string[];
  sources: (EpisodeLine & { document_id: string; source_available: boolean })[];
}

export interface CareEpisodeOut {
  case_id: string;
  case_reference: string;
  patient_alias: string;
  episode_title: string;
  clinical_context: string | null;
  currency: string;
  total_billed: string;
  overlap_deductions: string;
  net_episode_total: string;
  payable_now: string;
  queried: string;
  already_paid: string;
  potential_overlap_amount: string;
  recorded_bill_total: string;
  confirmed_adjustments: string;
  warnings: string[];
  input_fingerprint: string;
  ai_configured: boolean;
  documents: EpisodeDocumentOut[];
  timeline: EpisodeTimelineEventOut[];
  overlaps: EpisodeOverlapOut[];
  ai_insights: {
    provider: string;
    model?: string;
    episode_title?: string;
    clinical_summary?: string;
    belongs_together?: boolean | null;
    analysis_status?: string;
    document_assessments?: { document_id: string; status: string; reason: string }[];
    affinity_explanation?: string;
    key_findings?: string[];
    payer_recommendations?: string[];
  };
  blockers?: string[];
}

