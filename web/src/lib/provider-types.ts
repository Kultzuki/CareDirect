import type { BucketsOut } from "./types";

export type ProviderResponseType = "ACCEPT" | "CORRECT" | "EXPLAIN";
export type PayerDecision = "ACCEPT" | "KEEP_OPEN" | "REJECT";

export interface ProviderLinkOut {
  id: string;
  token: string;
  expires_at: string;
  case_id: string;
  flag_id: string;
  line_item_id: string;
}

export interface ProviderLinkHistory {
  id: string;
  flag_id: string;
  line_item_id: string;
  question: string;
  expires_at: string;
  consumed_at: string | null;
  revoked_at: string | null;
  created_at: string;
  state: "ACTIVE" | "RESPONDED" | "REVOKED" | "EXPIRED";
}

export interface ProviderResponseOut {
  id: string;
  case_id: string;
  flag_id: string;
  line_item_id: string;
  provider_link_id: string;
  response_type: ProviderResponseType;
  response_text: string;
  corrected_amount: string | null;
  currency: string;
  responder_label: string;
  actor_verification_method: string;
  responded_at: string;
}

export interface ProviderDecisionOut {
  id: string;
  case_id: string;
  response_id: string;
  line_item_id: string;
  decision: PayerDecision;
  note: string;
  original_amount: string;
  previous_amount: string;
  recognized_amount: string;
  adjustment: string;
  currency: string;
  actor_label: string;
  created_at: string;
}

export interface ProviderWorkflowOut {
  links: ProviderLinkHistory[];
  responses: ProviderResponseOut[];
  decisions: ProviderDecisionOut[];
}

export interface ProviderPortalOut {
  provider_name: string;
  currency: string;
  question: string;
  line: {
    id: string;
    description_raw: string;
    line_total: string;
    recognized_amount: string;
    source_page: number | null;
    source_text: string | null;
  };
  flag: { id: string; explanation: string };
  expires_at: string;
  state: "AWAITING_RESPONSE" | "RESPONDED";
  response: Pick<ProviderResponseOut, "id" | "response_type" | "response_text" | "corrected_amount" | "currency" | "responder_label" | "actor_verification_method" | "responded_at"> | null;
}

export interface ProviderPreviewOut {
  response_id: string;
  case_id: string;
  line_item_id: string;
  currency: string;
  original_amount: string;
  current_amount: string;
  proposed_amount: string;
  adjustment: string;
  before: BucketsOut;
  after: BucketsOut;
  state_fingerprint: string;
  can_accept: boolean;
  blockers: string[];
}

export const RESPONSE_LABELS: Record<ProviderResponseType, string> = {
  ACCEPT: "Credit the charge",
  CORRECT: "Propose a corrected amount",
  EXPLAIN: "Explain the existing charge",
};
