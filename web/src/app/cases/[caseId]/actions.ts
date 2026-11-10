"use server";

import { refresh } from "next/cache";

import { ApiError, apiGet, apiPostJson, seg } from "@/lib/api";
import { getDemoPayer } from "@/lib/demo-identity";
import type { PayerDecision, ProviderLinkOut, ProviderPreviewOut } from "@/lib/provider-types";
import type { CaseDetailOut, ExternalPaymentOut, FlagOut, LineItemOut } from "@/lib/types";
import { isUuid } from "@/lib/validation";

import type { WorkspaceState } from "./workspace-state";

function fail(error: unknown): WorkspaceState {
  return { status: "error", message: error instanceof ApiError ? error.message : "This action could not be completed. Your text is still here; retry when the service is available." };
}

async function payerId() {
  const payer = await getDemoPayer();
  if (!payer) throw new ApiError(403, "no_payer", "A demo payer is not available. Ask the demo owner to restart the sample.");
  return payer.id;
}

export async function createProviderLink(caseId: string, flagId: string, _previous: WorkspaceState, data: FormData): Promise<WorkspaceState> {
  const lineId = data.get("line_item_id");
  const question = String(data.get("question") ?? "").trim();
  if (!isUuid(caseId) || !isUuid(flagId) || !isUuid(lineId)) return { status: "error", message: "Choose a charge from this question." };
  if (!question || question.length > 2000) return { status: "error", message: "Write a specific question, up to 2,000 characters." };
  let held = false;
  try {
    const actorId = await payerId();
    const lines = await apiGet<LineItemOut[]>(`/api/cases/${seg(caseId)}/line-items`, { actorId });
    const line = lines.find((item) => item.id === lineId);
    if (!line) return { status: "error", message: "That charge is no longer available in this case." };
    if (line.status !== "QUERIED") {
      await apiPostJson(`/api/line-items/${seg(lineId)}/query`, { reason: question, flag_id: flagId }, { actorId });
      held = true;
    }
    const link = await apiPostJson<ProviderLinkOut>(`/api/flags/${seg(flagId)}/provider-links`, { line_item_id: lineId, question, ttl_minutes: 1440 }, { actorId });
    refresh();
    return { status: "success", message: "Provider link created. Share it with the billing representative; no message has been sent.", path: `/provider/respond/${link.token}`, expiresAt: link.expires_at };
  } catch (error) {
    refresh();
    const state = fail(error);
    return held ? { ...state, message: `The charge is now held for clarification. The link was not created: ${state.message}` } : state;
  }
}

export async function previewProviderResponse(caseId: string, responseId: string): Promise<WorkspaceState> {
  if (!isUuid(caseId) || !isUuid(responseId)) return { status: "error", message: "That response was not found." };
  try {
    const actorId = await payerId();
    const preview = await apiGet<ProviderPreviewOut>(`/api/provider-responses/${seg(responseId)}/preview`, { actorId });
    if (preview.case_id !== caseId) return { status: "error", message: "That response belongs to another case." };
    return { status: "success", preview };
  } catch (error) { return fail(error); }
}

export async function decideProviderResponse(caseId: string, responseId: string, _previous: WorkspaceState, data: FormData): Promise<WorkspaceState> {
  const decision = data.get("decision") as PayerDecision;
  const note = String(data.get("note") ?? "").trim();
  const fingerprint = String(data.get("state_fingerprint") ?? "");
  if (!isUuid(caseId) || !isUuid(responseId) || !["ACCEPT", "KEEP_OPEN", "REJECT"].includes(decision)) return { status: "error", message: "Choose how to resolve this response." };
  if (!note || note.length > 2000) return { status: "error", message: "Record why you made this decision, up to 2,000 characters." };
  if (!/^[a-f0-9]{64}$/.test(fingerprint)) return { status: "error", message: "Refresh the financial preview before deciding." };
  try {
    const actorId = await payerId();
    const preview = await apiGet<ProviderPreviewOut>(`/api/provider-responses/${seg(responseId)}/preview`, { actorId });
    if (preview.case_id !== caseId) return { status: "error", message: "That response belongs to another case." };
    await apiPostJson(`/api/provider-responses/${seg(responseId)}/decision`, { decision, note, state_fingerprint: fingerprint }, { actorId });
    refresh();
    return { status: "success", message: decision === "ACCEPT" ? "Resolution accepted. The ledger records the adjustment and keeps the original charge." : decision === "KEEP_OPEN" ? "Question kept open. The amount stays held for clarification." : "Response rejected. The amount stays held; create a new link to ask a follow-up." };
  } catch (error) { return fail(error); }
}

export async function caseAction(caseId: string, action: "accept" | "checks", entityId: string, _previous: WorkspaceState): Promise<WorkspaceState> {
  void _previous;
  if (!isUuid(caseId) || (action === "accept" && !isUuid(entityId))) return { status: "error", message: "That case or charge was not found." };
  try {
    const actorId = await payerId();
    if (action === "accept") {
      const lines = await apiGet<LineItemOut[]>(`/api/cases/${seg(caseId)}/line-items`, { actorId });
      if (!lines.some((line) => line.id === entityId)) return { status: "error", message: "That charge belongs to another case." };
      await apiPostJson(`/api/line-items/${seg(entityId)}/accept`, { note: "Payer reviewed the charge and its source evidence." }, { actorId });
    } else {
      await apiPostJson(`/api/cases/${seg(caseId)}/run-checks`, {}, { actorId });
    }
    refresh();
    return { status: "success", message: action === "accept" ? "Charge accepted after your review." : "Checks refreshed. Review the questions below." };
  } catch (error) { return fail(error); }
}

export async function revokeProviderLink(caseId: string, flagId: string, linkId: string, _previous: WorkspaceState): Promise<WorkspaceState> {
  void _previous;
  if (![caseId, flagId, linkId].every(isUuid)) return { status: "error", message: "That link was not found." };
  try {
    const actorId = await payerId();
    await apiPostJson(`/api/provider-links/${seg(linkId)}/revoke`, { note: "Payer revoked the provider link." }, { actorId });
    refresh();
    return { status: "success", message: "Provider link revoked. It can no longer be used." };
  } catch (error) { return fail(error); }
}

export async function dismissFinding(caseId: string, flagId: string, _previous: WorkspaceState, data: FormData): Promise<WorkspaceState> {
  const note = String(data.get("note") ?? "").trim();
  if (!isUuid(caseId) || !isUuid(flagId)) return { status: "error", message: "That finding was not found." };
  if (!note || note.length > 2000) return { status: "error", message: "Explain the evidence you reviewed, in up to 2,000 characters." };
  try {
    const actorId = await payerId();
    const flags = await apiGet<FlagOut[]>(`/api/cases/${seg(caseId)}/flags`, { actorId });
    if (!flags.some((flag) => flag.id === flagId)) return { status: "error", message: "That finding belongs to another case." };
    await apiPostJson(`/api/flags/${seg(flagId)}/status`, { status: "DISMISSED", note }, { actorId });
    refresh();
    return { status: "success", message: "Finding dismissed after review. Existing financial holds are unchanged." };
  } catch (error) { return fail(error); }
}

export async function reviewReceipt(caseId: string, paymentId: string, _previous: WorkspaceState, data: FormData): Promise<WorkspaceState> {
  const action = data.get("receipt_action");
  const note = String(data.get("note") ?? "").trim();
  if (!isUuid(caseId) || !isUuid(paymentId) || !["reconcile", "confirm"].includes(String(action))) return { status: "error", message: "Choose a receipt in this case." };
  if (action === "confirm" && (!note || note.length > 2000 || data.get("confirmed") !== "yes")) return { status: "error", message: "Confirm the source amount, date, reference and payee, and record your review reason." };
  try {
    const actorId = await payerId();
    const detail = await apiGet<CaseDetailOut>(`/api/cases/${seg(caseId)}`, { actorId });
    if (!detail.external_payments.some((payment) => payment.id === paymentId)) return { status: "error", message: "That receipt belongs to another case." };
    const result = await apiPostJson<ExternalPaymentOut>(`/api/external-payments/${seg(paymentId)}/${action}`, action === "confirm" ? {note} : {}, {actorId});
    refresh();
    return {status:"success",message: result.status === "MATCHED" ? "Prior payment evidence matched. The ledger counts it once; no funds were moved." : "The evidence needs clarification. Review the source and the billing findings before confirming."};
  } catch (error) { return fail(error); }
}
