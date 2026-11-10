import type { SourceOut } from "./types";

export interface InsuranceSelection {
  bill_id: string | null;
  preauth_id: string | null;
  settlement_id: string | null;
  insurer_payment_ids: string[];
}
export interface InsuranceFact {
  id: string; label: string; value: string;
  document_id: string | null;
  source: SourceOut | null;
}
export interface InsuranceComponent { key: string; label: string; amount: string | null }
export interface InsuranceReconciliation {
  can_review: boolean;
  case_id: string; currency: string; selection: InsuranceSelection; input_fingerprint: string;
  documents: { id: string; document_type: string; extraction_status: string }[];
  bills: { id: string; provider: string; number: string | null }[];
  hospital_total: string | null; itemized_total: string | null; hospital_stated_total: string | null;
  preauthorized: string | null; components: InsuranceComponent[];
  insurer_paid: string | null; approved_unpaid: string | null;
  family_paid: string; patient_share: string | null; patient_balance: string | null;
  known_patient_subtotal: string | null;
  family_overpayment: string | null; unexplained: string | null;
  facts: InsuranceFact[]; issues: string[]; warnings: string[];
  reviewed: boolean; review_stale: boolean; review_note: string | null;
}
export interface InsuranceExplanation {
  status: string; summary: string; coverage_gap: string | null;
  components: InsuranceComponent[]; evidence: InsuranceFact[]; limitations: string[];
  issues: string[]; input_fingerprint: string; reason_missing: boolean;
}
