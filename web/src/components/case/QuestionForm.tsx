"use client";

import Link from "next/link";
import { useActionState, useEffect, useRef, useState } from "react";

import { createProviderLink } from "@/app/cases/[caseId]/actions";
import { INITIAL_WORKSPACE_STATE } from "@/app/cases/[caseId]/workspace-state";
import { Button, FormField, MoneyText, Notice } from "@/components/ui";
import { formatDateTime } from "@/lib/format";
import type { LineItemOut } from "@/lib/types";

import styles from "./forms.module.css";
import { useUnsavedChanges } from "./useUnsavedChanges";

export function QuestionForm({ caseId, flagId, lines }: { caseId: string; flagId: string; lines: (LineItemOut & { recognized_amount: string })[] }) {
  const [lineId, setLineId] = useState(lines[lines.length - 1]?.id ?? "");
  const [question, setQuestion] = useState("");
  const [reviewing, setReviewing] = useState(false);
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState(false);
  const [state, action, pending] = useActionState(createProviderLink.bind(null, caseId, flagId), INITIAL_WORKSPACE_STATE);
  const feedback = useRef<HTMLDivElement>(null);
  const previewHeading = useRef<HTMLHeadingElement>(null);
  const questionInput = useRef<HTMLTextAreaElement>(null);
  const selected = lines.find((line) => line.id === lineId);
  useUnsavedChanges(question.trim().length > 0 && state.status !== "success");
  useEffect(() => { if (state.status !== "idle") feedback.current?.focus(); }, [state]);
  useEffect(() => { if (reviewing) previewHeading.current?.focus(); }, [reviewing]);
  if (state.status === "success" && state.path) return (
    <div className={styles.form} ref={feedback} tabIndex={-1}>
      <Notice tone="success" title="Provider link created"><p>{state.message}</p></Notice>
      <div className={styles.link}>
        <FormField id={`link-${flagId}`} label="Private provider link" hint="Anyone with this link can answer this question once. Copy it now; the token is not stored.">
          {(control) => <input {...control} readOnly value={state.path} onFocus={(event) => event.target.select()} />}
        </FormField>
        <div className={styles.actions}>
          <Button variant="secondary" onClick={async () => { try { await navigator.clipboard.writeText(`${window.location.origin}${state.path}`); setCopied(true); setCopyError(false); } catch { setCopyError(true); } }}>Copy link</Button>
          <Link href={state.path} target="_blank" rel="noreferrer noopener" prefetch={false}>Open provider view <span className="cd-visually-hidden">in a new tab</span></Link>
        </div>
        {copied ? <p role="status">Link copied.</p> : null}
        {copyError ? <p role="alert">Copy was unavailable. Select the link above and copy it manually.</p> : null}
        {state.expiresAt ? <p className={styles.note}>Expires {formatDateTime(state.expiresAt)}. You can revoke it from the link history below.</p> : null}
      </div>
    </div>
  );
  if (lines.length === 0) return null;
  return (
    <form action={action} className={styles.form} onSubmit={(event) => { if (!reviewing) { event.preventDefault(); setReviewing(true); } }} onKeyDown={(event) => { if (event.key === "Escape" && reviewing && !pending) { setReviewing(false); setTimeout(() => questionInput.current?.focus(), 0); } }}>
      <div hidden={reviewing} className={styles.form}>
        <FormField id={`charge-${flagId}`} label="Charge to question">
          {(control) => <select {...control} name="line_item_id" value={lineId} onChange={(event) => setLineId(event.target.value)} required>{lines.map((line) => <option value={line.id} key={line.id}>Line {line.line_number}: {line.description_raw}</option>)}</select>}
        </FormField>
        <FormField id={`provider-question-${flagId}`} label="Your question to the provider" hint="Ask about the supplied bill. Include only the information needed to clarify this charge.">
          {(control) => <textarea {...control} ref={questionInput} name="question" required maxLength={2000} value={question} onChange={(event) => setQuestion(event.target.value)} rows={3} />}
        </FormField>
      </div>
      {reviewing && selected ? <div className={styles.preview}>
        <h4 ref={previewHeading} tabIndex={-1}>What the provider will see</h4>
        <p>{selected.description_raw}</p>
        <p>Original charge <MoneyText value={selected.line_total} currency={selected.currency} /> · Current charge <MoneyText value={selected.recognized_amount} currency={selected.currency} /></p>
        <blockquote>{question}</blockquote>
        <p className={styles.note}>The link shows this charge, the rule explanation and its source excerpt. It does not show patient details or unrelated charges.</p>
        <p>{selected.status === "QUERIED" ? "This amount stays held for clarification." : "Creating this link also holds this charge for clarification, outside the payable amount."} The provider’s reply needs your review before it changes the bill.</p>
        <div className={styles.actions}>
          <Button type="submit" pending={pending}>Hold charge and create provider link</Button>
          <Button variant="quiet" disabled={pending} onClick={() => { setReviewing(false); setTimeout(() => questionInput.current?.focus(), 0); }}>Edit question</Button>
        </div>
      </div> : <Button type="submit">Preview provider question</Button>}
      <div className={styles.feedback} ref={feedback} tabIndex={-1}>{state.status === "error" ? <Notice tone="error" title="Provider link was not created"><p>{state.message}</p></Notice> : null}</div>
    </form>
  );
}
