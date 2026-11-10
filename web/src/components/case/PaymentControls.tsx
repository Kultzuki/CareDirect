"use client";

import { useActionState, useEffect, useRef, useState, type ReactNode } from "react";

import { paymentAction } from "@/app/cases/[caseId]/payments/actions";
import { Button, FormField, Notice } from "@/components/ui";
import { formatMoney } from "@/lib/money";
import { INITIAL_PAYMENT_STATE, type PaymentWorkspace } from "@/lib/payment-types";

import styles from "./payments.module.css";

type Action = "account-binding" | "invoice" | "verify" | "recover";

export function PaymentCommand({ caseId, command, label, approvalId, children }: { caseId: string; command: Action; label: string; approvalId?: string; children?: ReactNode }) {
  const [state, action, pending] = useActionState(paymentAction.bind(null, caseId, command), INITIAL_PAYMENT_STATE);
  const [invoiceId, setInvoiceId] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const feedback = useRef<HTMLDivElement>(null);
  useEffect(() => { if (state.status !== "idle") feedback.current?.focus(); }, [state]);
  return <form action={action} className={styles.form} onSubmit={() => setSubmitted(true)}>
    {children}
    {approvalId ? <input name="approval_id" type="hidden" value={approvalId} /> : null}
    {command === "recover" ? <FormField id="recover-invoice-id" label="Existing test invoice number" hint="Find this invoice in the PayPal test account. CareDirect checks that same invoice instead of creating another.">
      {(control) => <input {...control} name="invoice_id" value={invoiceId} onChange={(event) => setInvoiceId(event.target.value)} autoComplete="off" placeholder="INV2-…" required maxLength={90} disabled={pending} />}
    </FormField> : null}
    <div className={styles.actions}><Button type="submit" variant={command === "invoice" ? "primary" : "secondary"} pending={pending} disabled={command === "invoice" && submitted}>{label}</Button></div>
    <div ref={feedback} tabIndex={-1} className={styles.feedback}>{state.status !== "idle" ? <Notice tone={state.status === "error" ? "warning" : "info"} title={state.status === "error" ? "Review the current payment record" : "Payment record updated"}><p>{state.message}</p>{state.status === "error" ? <p><a href={`/cases/${caseId}?tab=payments`}>Refresh payment record</a></p> : null}</Notice> : null}</div>
  </form>;
}

export function PaymentApproval({ caseId, workspace }: { caseId: string; workspace: PaymentWorkspace }) {
  const [state, action, pending] = useActionState(paymentAction.bind(null, caseId, "approvals"), INITIAL_PAYMENT_STATE);
  const [purpose, setPurpose] = useState("");
  const [reviewing, setReviewing] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const heading = useRef<HTMLHeadingElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const feedback = useRef<HTMLDivElement>(null);
  const { preview } = workspace;
  useEffect(() => { if (reviewing) heading.current?.focus(); }, [reviewing]);
  useEffect(() => { if (state.status !== "idle") feedback.current?.focus(); }, [state]);
  const close = () => { setReviewing(false); setConfirmed(false); setTimeout(() => trigger.current?.focus(), 0); };
  const available = workspace.blockers.length === 0 && preview.account_binding.status === "VERIFIED" && !workspace.operation;
  return <div className={styles.form} onKeyDown={(event) => { if (event.key === "Escape" && reviewing && !pending) close(); }}>
    {!reviewing ? <Button ref={trigger} variant="primary" disabled={!available} aria-describedby={!available ? "approval-blockers" : undefined} onClick={() => setReviewing(true)}>Review approval for {formatMoney(preview.collect_amount, preview.currency)}</Button> : <form action={action} className={`${styles.form} ${styles.preview}`}>
      <h3 ref={heading} tabIndex={-1}>Approve {formatMoney(preview.collect_amount, preview.currency)} to collect now</h3>
      <p>This records your exact approval for the invoice composition and receiving account shown above. It does not create an invoice or complete checkout.</p>
      <input type="hidden" name="state_fingerprint" value={preview.state_fingerprint} />
      <input type="hidden" name="amount" value={preview.collect_amount} />
      <input type="hidden" name="currency" value={preview.currency} />
      <FormField id="payment-purpose" label="Payment purpose" hint="Saved with your approval. Use sample details only.">
        {(control) => <textarea {...control} name="purpose" value={purpose} onChange={(event) => setPurpose(event.target.value)} required maxLength={1000} rows={3} disabled={pending} />}
      </FormField>
      <label className={styles.confirm}><input name="confirmed" value="yes" type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} required disabled={pending} /><span>I approve collection of {formatMoney(preview.collect_amount, preview.currency)} for {preview.provider_label}, with invoice total {formatMoney(preview.invoice_total, preview.currency)} and linked prior payments {formatMoney(preview.external_total, preview.currency)}.</span></label>
      <div className={styles.actions}><Button type="submit" pending={pending} disabled={!confirmed || !available}>Approve {formatMoney(preview.collect_amount, preview.currency)} collection</Button><Button variant="quiet" onClick={close} disabled={pending}>Back to payment record</Button></div>
    </form>}
    <div ref={feedback} tabIndex={-1} className={styles.feedback}>{state.status !== "idle" ? <Notice tone={state.status === "error" ? "warning" : "info"} title={state.status === "error" ? "Approval result needs review" : "Approval recorded"}><p>{state.message}</p>{state.status === "error" ? <p><a href={`/cases/${caseId}?tab=payments`}>Refresh amounts before approving again</a></p> : null}</Notice> : null}</div>
  </div>;
}
