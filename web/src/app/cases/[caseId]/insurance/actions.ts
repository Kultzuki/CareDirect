"use server";

import { refresh } from "next/cache";
import { ApiError, apiPostJson, seg } from "@/lib/api";
import { getDemoPayer } from "@/lib/demo-identity";
import type { InsuranceExplanation, InsuranceSelection } from "@/lib/insurance-types";
import { isUuid } from "@/lib/validation";

export interface InsuranceActionState { error?: string; message?: string; explanation?: InsuranceExplanation }

export async function insuranceAction(caseId: string, selection: InsuranceSelection, fingerprint: string, kind: "review" | "explain", _state: InsuranceActionState, data: FormData): Promise<InsuranceActionState> {
  void _state;
  if (!isUuid(caseId) || !/^[a-f0-9]{64}$/.test(fingerprint)) return { error: "Refresh the reconciliation before continuing." };
  try {
    const payer = await getDemoPayer();
    if (!payer) return { error: "Payer identity is unavailable." };
    const body = { selection, input_fingerprint: fingerprint, ...(kind === "review" ? { note: String(data.get("note") ?? "").trim() } : {}) };
    if (kind === "explain") {
      const explanation = await apiPostJson<InsuranceExplanation>(`/api/cases/${seg(caseId)}/insurance/explain`, body, { actorId: payer.id, timeoutMs: 45_000 });
      return { explanation };
    }
    await apiPostJson(`/api/cases/${seg(caseId)}/insurance/review`, body, { actorId: payer.id });
    refresh();
    return { message: "Document links and reconciliation reviewed. No payment or adjustment was recorded." };
  } catch (error) { return { error: error instanceof ApiError ? error.message : "Insurance review could not be completed." }; }
}
