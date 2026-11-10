"use client";

import { useActionState, useEffect, useRef, useState } from "react";

import { useUnsavedChanges } from "@/components/case/useUnsavedChanges";
import { Button, FormField, MoneyText, Notice } from "@/components/ui";
import { isMoneyInput } from "@/lib/money";
import { RESPONSE_LABELS, type ProviderResponseType } from "@/lib/provider-types";

import styles from "@/components/case/forms.module.css";
import { respondToQuestion } from "./actions";
import { INITIAL_PROVIDER_STATE } from "./provider-state";

const CHOICES: { type: ProviderResponseType; help: string }[] = [
  { type: "ACCEPT", help: "Acknowledge the question and propose removing this charge in full." },
  { type: "CORRECT", help: "Give the amount this charge should be. The original stays in the record." },
  { type: "EXPLAIN", help: "Keep the current amount and explain what the charge covers." },
];

export function ProviderForm({ token, currentAmount, currency }: { token: string; currentAmount: string; currency: string }) {
  const [type, setType] = useState<ProviderResponseType>("EXPLAIN");
  const [reason, setReason] = useState("");
  const [amount, setAmount] = useState("");
  const [name, setName] = useState("");
  const [reviewing, setReviewing] = useState(false);
  const [state, action, pending] = useActionState(respondToQuestion.bind(null, token), INITIAL_PROVIDER_STATE);
  const heading = useRef<HTMLHeadingElement>(null);
  const first = useRef<HTMLInputElement>(null);
  const feedback = useRef<HTMLDivElement>(null);
  useUnsavedChanges((reason.length > 0 || name.length > 0 || amount.length > 0) && state.status !== "success");
  useEffect(() => { if (reviewing) heading.current?.focus(); }, [reviewing]);
  useEffect(() => { if (state.status !== "idle") feedback.current?.focus(); }, [state]);
  const close = () => { setReviewing(false); setTimeout(() => first.current?.focus(), 0); };
  if (state.status === "success") return <div ref={feedback} tabIndex={-1} className={styles.form}><Notice tone="success" title="Response recorded"><p>{state.message}</p></Notice><p>You can close this window. This link cannot submit another response.</p><blockquote className={styles.quote}>{state.response?.response_text}</blockquote></div>;
  const proposed = type === "ACCEPT" ? "0.00" : type === "EXPLAIN" ? currentAmount : isMoneyInput(amount) ? amount.includes(".") ? `${amount.split(".")[0]}.${amount.split(".")[1].padEnd(2, "0")}` : `${amount}.00` : null;
  return <form className={styles.form} action={action} onSubmit={(event) => { if (!reviewing) { event.preventDefault(); setReviewing(true); } }} onKeyDown={(event) => { if (event.key === "Escape" && reviewing && !pending) close(); }}>
    <div hidden={reviewing} className={styles.form}>
      <fieldset disabled={pending}>
        <legend>How would you resolve this question?</legend>
        {CHOICES.map((choice, index) => <label className={styles.choice} key={choice.type}><input ref={index === 0 ? first : undefined} type="radio" name="response_type" value={choice.type} checked={type === choice.type} onChange={() => setType(choice.type)} /><span><strong>{RESPONSE_LABELS[choice.type]}</strong><small>{choice.help}</small></span></label>)}
      </fieldset>
      {type === "CORRECT" ? <FormField id="corrected-amount" label={`Proposed charge (${currency})`} hint="Enter the new amount for this charge, not the amount of the credit. Zero proposes a full credit.">
        {(control) => <input {...control} name="corrected_amount" inputMode="decimal" type="text" pattern="[0-9]{1,12}(\.[0-9]{1,2})?" required value={amount} onChange={(event) => setAmount(event.target.value)} />}
      </FormField> : null}
      <FormField id="provider-reason" label="Reason and supporting explanation" hint="Explain this charge or proposed change. Do not include unrelated patient information.">
        {(control) => <textarea {...control} name="response_text" required maxLength={2000} value={reason} onChange={(event) => setReason(event.target.value)} rows={5} />}
      </FormField>
      <FormField id="responder-label" label="Your name or billing-team reference" hint="This is self-reported and will appear in the case history.">
        {(control) => <input {...control} name="responder_label" required maxLength={120} value={name} onChange={(event) => setName(event.target.value)} autoComplete="off" />}
      </FormField>
    </div>
    {reviewing ? <div className={styles.preview}>
      <h3 ref={heading} tabIndex={-1}>Review your response</h3>
      <p><strong>{RESPONSE_LABELS[type]}</strong></p>
      <p>Current charge <MoneyText value={currentAmount} currency={currency} />{proposed ? <>. Proposed charge <MoneyText value={proposed} currency={currency} />.</> : null}</p>
      <blockquote>{reason}</blockquote>
      <p className={styles.note}>Recorded as {name}. This is a proposal for the payer to review. Submitting does not change the payable amount or approve a payment.</p>
      <div className={styles.actions}><Button type="submit" pending={pending}>Record response for payer review</Button><Button variant="quiet" disabled={pending} onClick={close}>Edit response</Button></div>
    </div> : <Button type="submit">Review response</Button>}
    <div tabIndex={-1} ref={feedback} className={styles.feedback}>{state.status === "error" ? <Notice tone="error" title="Response was not recorded"><p>{state.message}</p></Notice> : null}</div>
  </form>;
}
