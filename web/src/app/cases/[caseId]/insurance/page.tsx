import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { connection } from "next/server";
import { Suspense } from "react";
import { ApiProblem, NoDemoPayer } from "@/components/PageProblems";
import { Button, ButtonLink, MoneyText, PageHeader, Section } from "@/components/ui";
import { apiGet, seg } from "@/lib/api";
import { getDemoPayer } from "@/lib/demo-identity";
import { documentTypeLabel } from "@/lib/format";
import type { InsuranceReconciliation } from "@/lib/insurance-types";
import { attempt } from "@/lib/load";
import { isUuid } from "@/lib/validation";
import { InsuranceControls } from "./InsuranceControls";
import { InsuranceFacts } from "./InsuranceFacts";
import styles from "../comparison/comparison.module.css";
import { ClaimFundingOverview } from "@/components/workspace/FinancialOverviews";

export const metadata: Metadata = { title: "Insurance and family share", robots: { index: false, follow: false } };
type Props = { params: Promise<{ caseId: string }>; searchParams: Promise<Record<string, string | string[] | undefined>> };

export default function InsurancePage(props: Props) {
  return <Suspense fallback={<p>Checking insurance documentsâ€¦</p>}><Insurance {...props} /></Suspense>;
}

function Amount({ value, currency }: { value: string | null; currency: string }) {
  return value === null ? <>Unknown / not supplied</> : <MoneyText value={value} currency={currency} />;
}

async function Insurance({ params, searchParams }: Props) {
  await connection();
  const { caseId } = await params;
  if (!isUuid(caseId)) notFound();
  const query = await searchParams;
  const selected = new URLSearchParams();
  if (query.select_documents === "true") {
    selected.set("select_documents", "true");
    for (const key of ["bill_id", "preauth_id", "settlement_id"]) {
      const value = query[key];
      if (typeof value === "string" && isUuid(value)) selected.set(key, value);
    }
    const payments = query.insurer_payment_ids;
    for (const id of Array.isArray(payments) ? payments : payments ? [payments] : []) if (isUuid(id)) selected.append("insurer_payment_ids", id);
  }
  const loaded = await attempt(async () => {
    const payer = await getDemoPayer();
    return payer ? apiGet<InsuranceReconciliation>(`/api/cases/${seg(caseId)}/insurance?${selected}`, { actorId: payer.id }) : null;
  });
  if (!loaded.ok) return <ApiProblem error={loaded.error} />;
  if (!loaded.value) return <NoDemoPayer />;
  const result = loaded.value;
  const rows: [string, string | null][] = [
    ["Hospital stated bill total", result.hospital_stated_total],
    ["Hospital itemized total", result.itemized_total],
    ["Hospital bill after agreed adjustments", result.hospital_total],
    ["Pre-authorised (not final approval)", result.preauthorized],
    ...result.components.map((c): [string, string | null] => [c.label, c.amount]),
    ["Actual insurer payment evidence", result.insurer_paid],
    ["Approved amount not evidenced as paid", result.approved_unpaid],
    ["Stated patient share: co-pay + deductible + non-covered", result.patient_share],
    ["Known patient components subtotal (may be incomplete)", result.known_patient_subtotal],
    ["Family paid â€” matched direct / verified PayPal payments", result.family_paid],
    ["Patient balance from reconciled stated components (review required)", result.patient_balance],
    ["Family overpayment to review", result.family_overpayment],
    ["Unexplained allocation difference", result.unexplained],
  ];
  return <div className={styles.page}>
    <PageHeader title="Insurance and family share" back={{ href: `/cases/${caseId}`, label: "Episode overview" }} />
    <ClaimFundingOverview result={result} />
    <details><summary>What do these insurance terms mean?</summary><dl><dt>Approved amount</dt><dd>What the insurer has agreed to cover. It may not have paid yet.</dd><dt>Co-payment</dt><dd>The part of a covered cost the patient must pay.</dd><dt>Deductible</dt><dd>An amount the patient pays before insurance starts covering costs, as stated in the policy.</dd><dt>Non-covered expenses</dt><dd>Costs the insurance documents say the policy does not cover.</dd><dt>Pending claim</dt><dd>An amount still waiting for an insurance decision.</dd><dt>Rejected claim</dt><dd>An amount the insurer has declined. This does not by itself decide who must pay it.</dd><dt>TPA</dt><dd>A company that helps the insurer handle claims.</dd></dl></details>
    <p className={styles.summary}>The hospital bill, insurer funding and family responsibility are separate. An approval is not payment; a pending or rejected claim is not automatically a patient debt.</p>
    <ButtonLink href={`/cases/${caseId}?tab=documents`} variant="secondary">Upload or review insurance documents</ButtonLink>
    <Section id="insurance-documents" title="Choose evidence for this claim" description="Choose the hospital bill, the insurer’s final decision, any initial approval and records of actual insurance payments for this claim.">
      <form method="get" className={styles.form}>
        <input type="hidden" name="tab" value="insurance" /><input type="hidden" name="select_documents" value="true" />
        <label>Hospital bill<select name="bill_id" defaultValue={result.selection.bill_id ?? ""}><option value="">Choose hospital bill</option>{result.bills.map((b) => <option key={b.id} value={b.id}>{b.provider} Â· {b.number ?? b.id.slice(0, 8)}</option>)}</select></label>
        {([ ["preauth_id", "INSURANCE_PREAUTH"], ["settlement_id", "INSURANCE_SETTLEMENT"] ] as const).map(([name, kind]) => <label key={name}>{documentTypeLabel(kind)}<select name={name} defaultValue={result.selection[name] ?? ""}><option value="">Not selected</option>{result.documents.filter((d) => d.document_type === kind).map((d) => <option key={d.id} value={d.id}>{d.id.slice(0, 8)} Â· {d.extraction_status}</option>)}</select></label>)}
        <fieldset><legend>Insurance payment records (choose each payment once)</legend>{result.documents.filter((d) => d.document_type === "INSURER_PAYMENT").map((d) => <label key={d.id}><input type="checkbox" name="insurer_payment_ids" value={d.id} defaultChecked={result.selection.insurer_payment_ids.includes(d.id)} />{d.id.slice(0, 8)} Â· {d.extraction_status}</label>)}{!result.documents.some((d) => d.document_type === "INSURER_PAYMENT") && <p>No insurer payment evidence uploaded. Approval will not be counted as cash paid.</p>}</fieldset>
        <Button type="submit">Compare selected documents</Button>
      </form>
      {result.documents.map((d) => <p key={d.id}>{documentTypeLabel(d.document_type)} Â· {d.id.slice(0, 8)} Â· <a href={d.extraction_status === "EXTRACTED" ? `/cases/${caseId}/review/${d.id}` : `/cases/${caseId}?tab=documents#documents`}>Read or check document details</a></p>)}
    </Section>
    <Section id="insurance-components" title="Bill and insurance breakdown" description="These amounts come from the documents and checked payment records. Checking them here does not approve a payment or decide whether an insurance decision is legally correct.">
      {result.reviewed ? <p>These documents and amounts have been checked. {result.review_note}</p> : <p>{result.review_stale ? "Documents or payments changed since the last check. Please check again." : "A reviewer still needs to check these documents and amounts."}</p>}
      {!!result.issues.length && <ul className={styles.warnings}>{result.issues.map((text) => <li key={text}>{text}</li>)}</ul>}
      {!!result.warnings.length && <ul>{result.warnings.map((text) => <li key={text}>{text}</li>)}</ul>}
      <div className={styles.scroll} role="region" aria-label="Scrollable insurance components" tabIndex={0}><table className={styles.table}><caption>Claim comparison in {result.currency}; missing amounts remain unknown</caption><thead><tr><th scope="col">Component</th><th scope="col">Amount</th></tr></thead><tbody>{rows.map(([label, value]) => <tr key={label}><th scope="row">{label}</th><td><Amount value={value} currency={result.currency} /></td></tr>)}</tbody></table></div>
      <p>Checking insurance does not change the original hospital bill. CareDirect blocks payment of the whole bill when insurance is involved, so the family is not asked to pay amounts that insurance may cover or that still need checking.</p>
    </Section>
    <Section id="insurance-review" title="Review and explain">{result.can_review ? <InsuranceControls key={result.input_fingerprint} result={result} /> : <p>Your role can inspect the shared source facts. A family member with review permission can check these amounts or ask AI for an explanation.</p>}</Section>
    <Section id="insurance-evidence" title="Evidence behind the comparison"><details><summary>Amounts, stated reasons, itemized bill and payment evidence ({result.facts.length})</summary><InsuranceFacts facts={result.facts} caseId={caseId} /></details></Section>
  </div>;
}
