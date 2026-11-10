export interface FamilyAccess { can_view: boolean; can_review: boolean; can_approve: boolean; can_manage: boolean; can_contribute: boolean; role: string | null }
export interface FamilyMember {
  user_id: string; display_name: string; is_owner: boolean; role: string;
  active: boolean; can_review: boolean; can_approve: boolean;
  contributions: string; allocated_expenses: string; contribution_minus_allocation: string;
}
export interface FamilyWorkspace {
  case_id: string; currency: string; actor_id: string; access: FamilyAccess; total_contributions: string;
  members: FamilyMember[];
  invitations: { id: string; recipient_email: string; role: string; can_review: boolean; can_approve: boolean; expires_at: string; accepted_at: string | null; revoked_at: string | null; expired: boolean }[];
  ledger: { id: string; user_id: string; entry_type: string; amount: string; currency: string; contributed_on: string; reference: string | null; reverses_id: string | null; note: string; created_by: string; created_at: string }[];
  expenses: { id: string; description: string; status: string; amount: string; source_fingerprint: string; shares: { user_id: string; amount: string }[]; allocation_stale: boolean; allocation_version: number | null; unallocated: string }[];
  allocation_history: { id: string; line_item_id: string; version: number; shares: { user_id: string; amount: string }[]; note: string; created_by: string; created_at: string; source_amount: string }[];
  notifications: { id: string; event_type: string; actor_label: string; created_at: string; read_at: string | null }[];
  history: { id: string; event_type: string; actor_label: string; created_at: string; entity_type: string }[];
}
