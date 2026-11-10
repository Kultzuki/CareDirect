"use client";

import { useActionState } from "react";
import { Button, FormField, MoneyText } from "@/components/ui";
import type { InsuranceReconciliation } from "@/lib/insurance-types";
import { insuranceAction } from "./actions";
import { InsuranceFacts } from "./InsuranceFacts";
import styles from "../comparison/comparison.module.css";

export function InsuranceControls({ result }: { result: InsuranceReconciliation }) {
  const [review, confirm, confirming] = useActionState(insuranceAction.bind(null, result.case_id, result.selection, result.input_fingerprint, "review"), {});
  const [analysis, explain, explaining] = useActionState(insuranceAction.bind(null, result.case_id, result.selection, result.input_fingerprint, "explain"), {});
  return <>
    <form action={confirm}>
      <p>Check that these documents are for the same hospital bill and claim, and that no amount is counted twice. Saving this check does not approve payment or decide what the policy covers.</p>
      <FormField id="insurance-review-note" label="Review note">{(props) => <textarea {...props} name="note" required maxLength={2000} rows={3} />}</FormField>
      <Button type="submit" pending={confirming} disabled={result.issues.length > 0 || result.reviewed}>Confirm I checked these amounts</Button>
      <p role={review.error ? "alert" : "status"}>{review.error ?? review.message}</p>
    </form>
    <form action={explain}>
      <h3>Why is insurance covering less than the hospital bill?</h3>
      <p>Get an explanation using the insurer’s written decision and the amounts you checked. If AI is enabled, an outside service may keep a copy of the short document extracts sent to it. If AI is off, CareDirect shows the available document facts.</p>
      <Button type="submit" pending={explaining} disabled={!result.selection.settlement_id}>Explain coverage with AI</Button>
      {analysis.error && <p role="alert">{analysis.error}</p>}
    </form>
    {analysis.explanation && <div className={styles.evidence} aria-live="polite">
      <h3>Explanation with document references</h3>
      <p>{analysis.explanation.status === "model_evidence_selection" ? "AI selected source evidence; amounts were calculated by CareDirect." : analysis.explanation.status === "provider_unavailable" ? "AI was unavailable or returned unsupported evidence. Local source evidence is shown." : "Local evidence explanation; no model request was made."}</p>
      <p>{analysis.explanation.summary}</p>
      <ul>{analysis.explanation.components.filter((c) => c.key !== "approved_amount").map((c) => <li key={c.key}>{c.label}: {c.amount === null ? "Unknown" : <MoneyText value={c.amount} currency={result.currency} />}</li>)}</ul>
      {analysis.explanation.reason_missing && <p>These documents do not clearly say why. Ask the insurer or its claims administrator for a breakdown. CareDirect will not guess.</p>}
      <InsuranceFacts facts={analysis.explanation.evidence} caseId={result.case_id} />
      {!!analysis.explanation.issues.length && <ul>{analysis.explanation.issues.map((text) => <li key={text}>{text}</li>)}</ul>}
      <ul>{analysis.explanation.limitations.map((text) => <li key={text}>{text}</li>)}</ul>
    </div>}
  </>;
}
