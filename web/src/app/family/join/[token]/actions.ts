"use server";

import { redirect } from "next/navigation";
import { ApiError, apiPostJson, seg } from "@/lib/api";
import { getDemoPayer } from "@/lib/demo-identity";
import { isUploadToken, isUuid } from "@/lib/validation";

export async function acceptFamilyInvitation(token: string, _state: { error?: string }, data: FormData): Promise<{ error?: string }> {
  void _state;
  if (!isUploadToken(token) || !data.has("confirmed")) return { error: "Confirm that you want to join this shared episode." };
  let caseId: string;
  try {
    const actor = await getDemoPayer();
    if (!actor) return { error: "Select the invited local identity first." };
    const result = await apiPostJson<{ case_id: string }>(`/api/family/invitations/${seg(token)}/accept`, {}, { actorId: actor.id });
    if (!isUuid(result.case_id)) return { error: "The episode could not be opened." };
    caseId = result.case_id;
  } catch (error) { return { error: error instanceof ApiError ? error.message : "The invitation could not be accepted." }; }
  redirect(`/cases/${caseId}/family`);
}
