import { StatusBadge, type StatusTone } from "@/components/ui";
import { CASE_STATUS_LABEL } from "@/lib/format";
import type { CaseStatus } from "@/lib/types";

const TONE: Record<CaseStatus, StatusTone> = {
  DRAFT: "neutral",
  UNDER_REVIEW: "info",
  AWAITING_PROVIDER: "info",
  READY_FOR_APPROVAL: "success",
  RECONCILIATION_REQUIRED: "warning",
  CLOSED: "neutral",
};

export function CaseStatusBadge({ status }: { status: CaseStatus }) {
  return <StatusBadge tone={TONE[status]}>{CASE_STATUS_LABEL[status]}</StatusBadge>;
}
