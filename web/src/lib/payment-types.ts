export interface PaymentWorkspace {
  can_approve: boolean;
  state: string;
  blockers: string[];
  preview: {
    state_fingerprint: string;
    currency: string;
    invoice_total: string;
    external_total: string;
    collect_amount: string;
    queried: string;
    provider_label: string;
    external_payments: { id: string; amount: string; currency: string; paid_on: string; reference_suffix: string }[];
    account_binding: { status: "VERIFIED" | "REQUIRED"; basis: string; merchant_ref_suffix: string | null; client_fingerprint: string | null };
  };
  approval: null | { id: string; approved_amount: string; currency: string; purpose: string; approved_at: string; approved_by: string; state_fingerprint: string; current: boolean; snapshot: PaymentWorkspace["preview"] };
  operation: null | { id: string; state: string; stage: string; error_code: string | null; paypal_invoice_id: string | null };
  invoice: null | { id: string; paypal_invoice_id: string; status: string; invoice_total: string; amount_due: string; currency: string; last_verified_at: string | null; checkout_url: string | null };
  transactions: { id: string; source: string; amount: string; currency: string; status: string; verified_at: string | null; reference_suffix: string }[];
}

export interface PaymentActionState {
  status: "idle" | "success" | "error";
  message?: string;
  workspace?: PaymentWorkspace;
}

export const INITIAL_PAYMENT_STATE: PaymentActionState = { status: "idle" };

export const PAYMENT_STATES: Record<string, { title: string; explanation: string }> = {
  APPROVAL_REQUIRED: { title: "Approval required", explanation: "Check the bill amount, earlier payments and receiving account before you approve." },
  BLOCKED: { title: "Resolve these items before payment", explanation: "The case is available for review. Payment preparation is blocked by the items below." },
  APPROVED: { title: "Exact amount approved", explanation: "Your approval is recorded. Creating the test invoice is a separate action." },
  CREATING: { title: "Invoice preparation in progress", explanation: "Do not create another invoice. Refresh the record to check the reserved operation." },
  UNCERTAIN: { title: "Invoice result needs checking", explanation: "PayPal may have received the request. Do not create another invoice. Recover the existing invoice using its ID." },
  READY: { title: "test invoice ready", explanation: "Open the existing invoice to pay with the test buyer account, then verify the result here." },
  AWAITING_BUYER: { title: "Awaiting test buyer", explanation: "The invoice is awaiting payment. Returning here does not confirm payment." },
  VERIFICATION_PENDING: { title: "Payment verification pending", explanation: "Payment is not confirmed. Fetch the current PayPal record again to check its status." },
  PAID: { title: "Payment verified by PayPal", explanation: "CareDirect checked the payment with PayPal and saved it once." },
  CANCELLED: { title: "Invoice cancelled", explanation: "This attempt remains in the record. Review the case before preparing a fresh demo run." },
  RECONCILIATION_REQUIRED: { title: "Payment needs checking", explanation: "The PayPal record could not be matched safely to this care record. No new invoice should be created." },
};

export function sandboxCheckoutUrl(value: string | null | undefined): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" && url.hostname === "www.sandbox.paypal.com" && !url.port && !url.username && !url.password && (url.pathname.startsWith("/invoice/p/") || url.pathname.startsWith("/invoice/s/pay/")) ? url.href : null;
  } catch { return null; }
}
