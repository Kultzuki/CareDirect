"use server";

import { revalidatePath } from "next/cache";
import { apiPostJson } from "@/lib/api";
import { getDemoPayer } from "@/lib/demo-identity";
import { isUuid } from "@/lib/validation";

export interface DemoRunState { caseId?: string; caseReference?: string; error?: string }

export async function createDemoRun(mode: string, requestId: string): Promise<DemoRunState> {
  if (!["EMPTY", "PREPARED"].includes(mode) || !isUuid(requestId)) return { error: "Choose a valid demo run and try again." };
  try {
    const payer = await getDemoPayer();
    if (!payer) return { error: "The demo payer is unavailable. Reload the case list." };
    const result = await apiPostJson<{case_id: string; case_reference: string}>("/api/demo/runs", { mode, request_id: requestId }, { actorId: payer.id, timeoutMs: 60_000 });
    revalidatePath("/cases");
    return { caseId: result.case_id, caseReference: result.case_reference };
  } catch {
    return { error: "The result needs checking. Retry this same run to recover it; earlier cases and financial history are preserved." };
  }
}
