import type { BucketsOut, CaseStatus, CaseSummaryOut } from "./types";

export interface DashboardCase extends CaseSummaryOut {
  provider_name: string;
  provider_names: string[];
  open_questions: number;
  pending_responses: number;
  attention_count: number;
  documents_to_review: number;
  payment_state: string;
  latest_activity_at: string | null;
  latest_activity: { event_type: string; actor_label: string; created_at: string } | null;
}

export interface DashboardOut {
  cases: DashboardCase[];
  totals: { currency: string; payable_now: string; queried: string; already_paid: string; pending_review: string; net_bill_total: string }[];
  generated_at: string;
  provenance: string;
}

export interface EvidenceActivity {
  id: string; event_type: string; actor_label: string; created_at: string;
  entity_type: string | null; entity_id: string | null; ledger_entry_id: string | null;
}

export interface EvidenceOut {
  schema_version: string;
  provenance: string;
  case: { id: string; case_reference: string; patient_alias: string; currency: string; status: CaseStatus; is_demo: boolean };
  buckets: BucketsOut;
  documents: Record<string, unknown>[];
  extractions: Record<string, unknown>[];
  revisions: Record<string, unknown>[];
  bills: Record<string, unknown>[];
  lines: Record<string, unknown>[];
  flags: Record<string, unknown>[];
  questions: Record<string, unknown>[];
  provider_responses: Record<string, unknown>[];
  payer_decisions: Record<string, unknown>[];
  approvals: Record<string, unknown>[];
  external_payments: Record<string, unknown>[];
  paypal_invoices: Record<string, unknown>[];
  paypal_payments: Record<string, unknown>[];
  ledger: Record<string, unknown>[];
  activity: EvidenceActivity[];
}

export function paymentStateLabel(state: string): string {
  const labels: Record<string, string> = {
    NOT_STARTED: "No invoice attempt", APPROVAL_REQUIRED: "Approval required",
    APPROVED: "Approved; no invoice yet", READY: "Invoice ready", AWAITING_BUYER: "Awaiting buyer",
    VERIFIED_PAID: "Verified paid", PAID: "Verified paid", UNCERTAIN: "Amounts need checking",
    RECONCILIATION_REQUIRED: "Amounts need checking", FAILED: "Attempt needs review",
    CANCELLED: "Cancelled", PREPARING: "Invoice preparation", RESERVED: "Invoice preparation",
  };
  return labels[state] ?? state.toLowerCase().replaceAll("_", " ");
}

export function activityLabel(event: string): string {
  const labels: Record<string, string> = {
    CASE_CREATED: "Care record created", DOCUMENT_UPLOADED: "Document uploaded",
    DOCUMENT_EXTRACTED: "Document details read", EXTRACTION_COMPLETED: "Document details read",
    EXTRACTION_REVISED: "Human review saved", EXTRACTION_PROMOTED: "Checked details added to the bill",
    LINE_ITEM_ACCEPTED: "Charge accepted by payer", LINE_ITEM_QUERIED: "Charge held for clarification",
    PROVIDER_LINK_CREATED: "Provider question link created", PROVIDER_RESPONSE_RECORDED: "Provider proposal recorded",
    PROVIDER_RESPONSE_DECIDED: "Payer reviewed provider proposal", PAYMENT_APPROVED: "Exact payment approved",
    PAYPAL_PAYMENT_VERIFIED: "Payment verified against PayPal", PAYPAL_CREDIT_RECORDED: "Verified PayPal credit recorded",
  };
  return labels[event] ?? event.charAt(0) + event.slice(1).toLowerCase().replaceAll("_", " ");
}
