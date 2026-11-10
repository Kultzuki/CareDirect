"use server";

import { refresh } from "next/cache";

import { ApiError, apiPostJson, seg } from "@/lib/api";
import { getDemoPayer } from "@/lib/demo-identity";
import { isMoneyString } from "@/lib/money";
import type { PaymentActionState, PaymentWorkspace } from "@/lib/payment-types";
import { isUuid } from "@/lib/validation";

export async function paymentAction(caseId: string, action: "account-binding" | "approvals" | "invoice" | "verify" | "recover", _previous: PaymentActionState, data: FormData): Promise<PaymentActionState> {
  if (!["account-binding", "approvals", "invoice", "verify", "recover"].includes(action)) return { status: "error", message: "Choose an available payment action." };
  if (!isUuid(caseId)) return { status: "error", message: "This case was not found." };
  const body: Record<string, unknown> = {};
  if (action === "approvals") {
    const amount = String(data.get("amount") ?? "");
    const currency = String(data.get("currency") ?? "");
    const fingerprint = String(data.get("state_fingerprint") ?? "");
    const purpose = String(data.get("purpose") ?? "").trim();
    if (!isMoneyString(amount) || !/^[A-Z]{3}$/.test(currency) || !/^[a-f0-9]{64}$/.test(fingerprint)) return { status: "error", message: "Refresh the payment record and review the current amount before approving." };
    if (!purpose || purpose.length > 1000 || data.get("confirmed") !== "yes") return { status: "error", message: "Record the payment purpose and explicitly confirm the exact amount." };
    Object.assign(body, { amount, currency, state_fingerprint: fingerprint, purpose, confirmed: true });
  } else if (action === "invoice") {
    const approvalId = data.get("approval_id");
    if (!isUuid(approvalId)) return { status: "error", message: "Review and approve the current amount before creating an invoice." };
    body.approval_id = approvalId;
  } else if (action === "recover") {
    const invoiceId = String(data.get("invoice_id") ?? "").trim();
    if (!/^INV2-[A-Z0-9-]{8,80}$/.test(invoiceId)) return { status: "error", message: "Enter the existing Sandbox invoice ID beginning INV2-." };
    body.invoice_id = invoiceId;
  }
  try {
    const payer = await getDemoPayer();
    if (!payer) return { status: "error", message: "A demo payer is unavailable. Ask the demo owner to restart the sample." };
    const workspace = await apiPostJson<PaymentWorkspace>(`/api/cases/${seg(caseId)}/payments/${action}`, body, { actorId: payer.id, timeoutMs: 90_000 });
    refresh();
    return { status: "success", message: action === "approvals" ? "Exact payment approval recorded. Invoice creation is a separate action." : action === "account-binding" ? "Receiving-account check completed. Review its basis below." : action === "invoice" ? "Invoice preparation returned. Review its current state below." : action === "recover" ? "Existing invoice recovery checked. Review the current state below." : "Authoritative payment record refreshed.", workspace };
  } catch (error) {
    refresh();
    return { status: "error", message: error instanceof ApiError && error.code !== "api_unavailable" ? error.message : "The result could not be retrieved. Refresh the payment record before taking another action; an invoice request may already have reached PayPal." };
  }
}
