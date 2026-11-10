"use client";

import Link from "next/link";
import { useActionState, useState } from "react";
import { reviewReceipt } from "@/app/cases/[caseId]/actions";
import { INITIAL_WORKSPACE_STATE } from "@/app/cases/[caseId]/workspace-state";
import { Button, MoneyText, Notice } from "@/components/ui";
import type { ExternalPaymentOut } from "@/lib/types";
import { formatMoney } from "@/lib/money";
import { isUuid } from "@/lib/validation";
import styles from "./forms.module.css";

export function ReceiptReview({ caseId, payment, canReview = true }: {caseId:string; payment:ExternalPaymentOut; canReview?:boolean}) {
  const [state,invoke,pending] = useActionState(reviewReceipt.bind(null,caseId,payment.id), INITIAL_WORKSPACE_STATE);
  const [reviewing,setReviewing] = useState(false);
  const [note,setNote] = useState("");
  const sources = payment.match_basis?.sources?.flatMap(source=>source.source_document_ref && isUuid(source.source_document_ref) ? [source.source_document_ref] : []) ?? [];
  return <div className={styles.inline}><p><MoneyText value={payment.amount} currency={payment.currency} /> · {payment.method} · {payment.status === "MATCHED" ? "Evidence matched" : "Review needed"}</p>
    <p>Source date {payment.paid_on ?? "not recorded"}; reference {payment.reference ?? "not recorded"}; payee {payment.payee_name ?? "not recorded"}.</p>
    <p><Link href={`/cases/${caseId}?tab=documents`}>Review the original receipt and bill</Link>{[...new Set(sources)].map((documentId,index)=><span key={documentId}> · <Link href={`/cases/${caseId}/review/${documentId}`}>Source {index+1}</Link></span>)}</p>
    {payment.match_basis?.problems?.length ? <ul>{payment.match_basis.problems.map(problem=><li key={problem}>{problem}</li>)}</ul> : null}
    {canReview && payment.status !== "MATCHED" ? <form action={invoke} className={styles.inline}>{payment.status === "SUBMITTED" ? <Button name="receipt_action" value="reconcile" type="submit" variant="secondary" pending={pending}>Review prior payment evidence</Button> : null}
      {payment.status === "NEEDS_CLARIFICATION" ? <><Button variant="quiet" disabled={pending} onClick={() => setReviewing(!reviewing)} aria-expanded={reviewing}>Review source manually</Button>{reviewing ? <><label htmlFor={`receipt-note-${payment.id}`}>Evidence review reason</label><textarea id={`receipt-note-${payment.id}`} name="note" value={note} onChange={(event) => setNote(event.target.value)} maxLength={2000} required /><label><input type="checkbox" name="confirmed" value="yes" required /> I reviewed the receipt amount, currency, date, reference and payee against this bill.</label><Button name="receipt_action" value="confirm" type="submit" pending={pending}>Confirm prior {formatMoney(payment.amount,payment.currency)} after review</Button></> : null}</> : null}
    </form> : <p>{payment.status === "MATCHED" ? "Matched to supplied evidence, not independently verified by a bank." : "An authorized reviewer must reconcile this evidence."}</p>}
    {state.message ? <Notice tone={state.status === "error" ? "error" : "info"}><p>{state.message}</p></Notice> : null}
  </div>;
}
