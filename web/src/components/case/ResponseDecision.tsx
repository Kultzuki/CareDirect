"use client";

import { useActionState, useEffect, useRef, useState, useTransition } from "react";

import { decideProviderResponse, previewProviderResponse } from "@/app/cases/[caseId]/actions";
import { INITIAL_WORKSPACE_STATE, type WorkspaceState } from "@/app/cases/[caseId]/workspace-state";
import { Button, FormField, MoneyText, Notice } from "@/components/ui";
import { formatMoney } from "@/lib/money";
import type { PayerDecision } from "@/lib/provider-types";

import styles from "./forms.module.css";
import { useUnsavedChanges } from "./useUnsavedChanges";

export function ResponseDecision({ caseId, responseId, recorded = false }: { caseId: string; responseId: string; recorded?: boolean }) {
  const [previewState, setPreview] = useState<WorkspaceState>(INITIAL_WORKSPACE_STATE);
  const [loading, startPreview] = useTransition();
  const [state, action, pending] = useActionState(decideProviderResponse.bind(null, caseId, responseId), INITIAL_WORKSPACE_STATE);
  const [decision, setDecision] = useState<PayerDecision>("ACCEPT");
  const [note, setNote] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const feedback = useRef<HTMLDivElement>(null);
  const preview = previewState.preview;
  useUnsavedChanges(note.trim().length > 0 && state.status !== "success");
  useEffect(() => { if (preview) heading.current?.focus(); }, [preview]);
  useEffect(() => { if (state.status !== "idle") feedback.current?.focus(); }, [state]);
  const close = () => { setPreview(INITIAL_WORKSPACE_STATE); setConfirmed(false); setTimeout(() => trigger.current?.focus(), 0); };
  if (state.status === "success") return <div tabIndex={-1} ref={feedback} className={styles.form}><Notice tone="success" title="Decision recorded"><p>{state.message}</p></Notice></div>;
  if (recorded) return null;
  return <div className={styles.form} onKeyDown={(event) => { if (event.key === "Escape" && preview && !pending) close(); }}>
    {!preview ? <Button ref={trigger} variant="secondary" pending={loading} onClick={() => startPreview(async () => { const result = await previewProviderResponse(caseId, responseId); setPreview(result); setConfirmed(false); })}>Review financial effect</Button> : null}
    {previewState.status === "error" ? <Notice tone="error" title="Preview unavailable"><p>{previewState.message}</p></Notice> : null}
    {preview ? <form action={action} className={styles.preview}>
      <h4 ref={heading} tabIndex={-1}>Review the exact financial effect</h4>
      <input type="hidden" name="state_fingerprint" value={preview.state_fingerprint} />
      <table className={styles.table}>
        <caption>Proposed resolution in {preview.currency}</caption>
        <thead><tr><th scope="col">Amount</th><th scope="col">Before</th><th scope="col">If accepted</th></tr></thead>
        <tbody>
          <tr><th scope="row">This charge</th><td><MoneyText value={preview.current_amount} currency={preview.currency} /></td><td><MoneyText value={preview.proposed_amount} currency={preview.currency} /></td></tr>
          <tr><th scope="row">Payable now</th><td><MoneyText value={preview.before.payable_now} currency={preview.currency} /></td><td><MoneyText value={preview.after.payable_now} currency={preview.currency} /></td></tr>
          <tr><th scope="row">Queried</th><td><MoneyText value={preview.before.queried} currency={preview.currency} /></td><td><MoneyText value={preview.after.queried} currency={preview.currency} /></td></tr>
          <tr><th scope="row">Net total</th><td><MoneyText value={preview.before.net_bill_total} currency={preview.currency} /></td><td><MoneyText value={preview.after.net_bill_total} currency={preview.currency} /></td></tr>
        </tbody>
      </table>
      <p className={styles.note}>Original charge <MoneyText value={preview.original_amount} currency={preview.currency} /> remains in the record. This proposal adds a signed adjustment of <MoneyText value={preview.adjustment} currency={preview.currency} /> only when you accept.</p>
      {preview.blockers.length ? <Notice tone="warning" title="Acceptance is blocked"><ul>{preview.blockers.map((blocker) => <li key={blocker}>{blocker}</li>)}</ul></Notice> : null}
      <fieldset disabled={pending}>
        <legend>Your decision</legend>
        {([ ["ACCEPT", "Accept resolution", "Apply the amounts shown above and release this question’s hold."], ["KEEP_OPEN", "Keep question open", "Record the response and keep the full current amount held."], ["REJECT", "Reject response", "Record your reason, keep the charge held and ask a follow-up."] ] as const).map(([value, title, hint]) => <label className={styles.choice} key={value}><input name="decision" type="radio" value={value} checked={decision === value} disabled={value === "ACCEPT" && !preview.can_accept} onChange={() => { setDecision(value); setConfirmed(false); }} /><span><strong>{title}</strong><small>{hint}</small></span></label>)}
      </fieldset>
      <FormField id={`decision-note-${responseId}`} label="Reason for your decision" hint="Kept with the provider’s original response in the case history.">
        {(control) => <textarea {...control} name="note" value={note} onChange={(event) => setNote(event.target.value)} required maxLength={2000} rows={3} />}
      </FormField>
      <label className={styles.confirm}><input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} required /> <span>{decision === "ACCEPT" ? `I reviewed the effect and accept ${formatMoney(preview.proposed_amount, preview.currency)} for this charge.` : "I understand this charge stays held for clarification."}</span></label>
      <div className={styles.actions}>
        <Button type="submit" pending={pending} disabled={!confirmed || (decision === "ACCEPT" && !preview.can_accept)}>{decision === "ACCEPT" ? `Accept resolution: ${formatMoney(preview.proposed_amount, preview.currency)}` : decision === "KEEP_OPEN" ? "Record and keep question open" : "Reject response and keep hold"}</Button>
        <Button variant="quiet" disabled={pending} onClick={close}>Close preview</Button>
      </div>
      {state.status === "error" ? <Button variant="secondary" pending={loading} onClick={() => startPreview(async () => { setPreview(await previewProviderResponse(caseId, responseId)); setConfirmed(false); })}>Refresh financial preview</Button> : null}
    </form> : null}
    <div className={styles.feedback} tabIndex={-1} ref={feedback}>{state.status === "error" ? <Notice tone="error" title="Decision was not recorded"><p>{state.message}</p></Notice> : null}</div>
  </div>;
}
