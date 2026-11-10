"use server";

import { refresh, revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { ApiError, apiPostJson, seg } from "@/lib/api";
import { getDemoPayer } from "@/lib/demo-identity";
import { isUuid } from "@/lib/validation";

export interface EpisodeActionState { error?: string; message?: string }

async function payer() {
  const actor = await getDemoPayer();
  if (!actor) throw new Error("Payer unavailable. Reload the page.");
  return actor.id;
}

export async function saveEpisode(caseId: string, _state: EpisodeActionState, data: FormData): Promise<EpisodeActionState> {
  const title = String(data.get("episode_title") ?? "").trim();
  const context = String(data.get("clinical_context") ?? "").trim();
  if (!isUuid(caseId) || !title || title.length > 200 || context.length > 2000) return { error: "Enter an episode title (up to 200 characters) and context (up to 2,000 characters)." };
  try {
    await apiPostJson(`/api/cases/${seg(caseId)}/episode/details`, { episode_title: title, clinical_context: context || null }, { actorId: await payer() });
    revalidatePath("/cases"); refresh();
    return { message: "Episode details saved. Previous AI analysis becomes stale when evidence changes." };
  } catch (error) { return { error: error instanceof ApiError ? error.message : "Episode details could not be saved." }; }
}

export async function analyzeEpisode(caseId: string, fingerprint: string, _state: EpisodeActionState): Promise<EpisodeActionState> {
  void _state;
  if (!isUuid(caseId) || !/^[a-f0-9]{64}$/.test(fingerprint)) return { error: "Refresh this episode before requesting analysis." };
  try {
    const result = await apiPostJson<{ ai_insights: { provider: string; analysis_status: string } }>(`/api/cases/${seg(caseId)}/episode/analyze`, { input_fingerprint: fingerprint }, { actorId: await payer(), timeoutMs: 45_000 });
    refresh();
    return { message: result.ai_insights.provider === "deepseek" ? "Model advice recorded for the current evidence. Review its suggestions against the source documents." : "Model analysis is unavailable. The local evidence review remains available; no model match was confirmed." };
  } catch (error) { return { error: error instanceof ApiError ? error.message : "Analysis could not be completed. Refresh the episode to check its recorded status." }; }
}

export async function createEpisode(_state: EpisodeActionState, data: FormData): Promise<EpisodeActionState> {
  const title = String(data.get("episode_title") ?? "").trim();
  const alias = String(data.get("patient_alias") ?? "").trim();
  const context = String(data.get("clinical_context") ?? "").trim();
  const currency = String(data.get("currency") ?? "INR");
  if (!title || title.length > 200 || !alias || alias.length > 120 || context.length > 2000 || !["INR", "USD"].includes(currency)) return { error: "Provide a title, patient alias and supported currency within the field limits." };
  let caseId: string;
  try {
    const result = await apiPostJson<{ id: string }>("/api/cases", { episode_title: title, patient_alias: alias, clinical_context: context || null, currency }, { actorId: await payer() });
    caseId = result.id;
  } catch (error) { return { error: error instanceof ApiError ? error.message : "Episode could not be created." }; }
  revalidatePath("/cases");
  redirect(`/cases/${seg(caseId)}/review`);
}
