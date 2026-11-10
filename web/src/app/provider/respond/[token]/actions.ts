"use server";

import { ApiError, apiPostJson, seg } from "@/lib/api";
import { isMoneyInput } from "@/lib/money";
import type { ProviderResponseOut, ProviderResponseType } from "@/lib/provider-types";
import { isUploadToken } from "@/lib/validation";

import type { ProviderFormState } from "./provider-state";

export async function respondToQuestion(token: string, _previous: ProviderFormState, data: FormData): Promise<ProviderFormState> {
  if (!isUploadToken(token)) return { status: "error", message: "This link cannot be used. Ask for a new provider link." };
  const responseType = data.get("response_type") as ProviderResponseType;
  const reason = String(data.get("response_text") ?? "").trim();
  const label = String(data.get("responder_label") ?? "").trim();
  const amount = String(data.get("corrected_amount") ?? "").trim();
  if (!["ACCEPT", "CORRECT", "EXPLAIN"].includes(responseType)) return { status: "error", message: "Choose a response to the question." };
  if (!reason || reason.length > 2000) return { status: "error", message: "Explain your response in up to 2,000 characters." };
  if (!label || label.length > 120) return { status: "error", message: "Add your name or billing-team reference, up to 120 characters." };
  if (responseType === "CORRECT" && !isMoneyInput(amount)) return { status: "error", message: "Enter the proposed charge as a positive amount or zero, with up to two decimal places." };
  try {
    const response = await apiPostJson<ProviderResponseOut>(`/api/provider/respond/${seg(token)}`, { response_type: responseType, response_text: reason, responder_label: label, ...(responseType === "CORRECT" ? { corrected_amount: amount } : {}) });
    return { status: "success", response, message: "Your response has been recorded. The family payer will review it before any financial change." };
  } catch (error) {
    return { status: "error", message: error instanceof ApiError ? error.status === 403 ? "This link is expired, revoked or unavailable. Ask for a new link. Your text remains here." : error.message : "The response service is unavailable. Your text remains here; try again in a moment." };
  }
}
