import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { connection } from "next/server";
import { Suspense } from "react";
import { ApiProblem, DemoIdentityNote, NoDemoPayer } from "@/components/PageProblems";
import { FinancialStrip } from "@/components/case/FinancialStrip";
import { EmptyState, PageHeader, Section } from "@/components/ui";
import { apiGet, seg } from "@/lib/api";
import { activityLabel, type EvidenceOut } from "@/lib/dashboard-types";
import { getDemoPayer } from "@/lib/demo-identity";
import { formatDateTime } from "@/lib/format";
import { attempt } from "@/lib/load";
import { isUuid } from "@/lib/validation";
import styles from "./evidence.module.css";

export const metadata: Metadata = { title: "Activity & evidence", robots: { index: false, follow: false } };
export default function EvidencePage({ params }: { params: Promise<{caseId: string}> }) {
  return <Suspense fallback={<p role="status">Loading the case record…</p>}><CaseEvidence params={params} /></Suspense>;
}

const LABELS: Record<string,string> = { id: "Record reference", document_id: "Source document reference", created_at: "Recorded at", actor_label: "Recorded by", raw_output: "Original recorded extraction", corrected_values: "Human corrected values", approved_amount: "Exact amount approved to collect", amount_to_collect: "Amount to collect", invoice_total: "Invoice total", external_paid: "Linked prior payment", source_page: "Source page", source_text: "Source excerpt", is_demo: "Sample record", extraction_confidence: "AI confidence estimate (not a guarantee)" };
function label(value: string) { return LABELS[value] ?? value.charAt(0).toUpperCase() + value.slice(1).replaceAll("_", " "); }
function RecordValue({ value, depth = 0 }: { value: unknown; depth?: number }) {
  if (value === null || value === undefined) return <span className={styles.muted}>Not recorded</span>;
  if (typeof value === "boolean") return <>{value ? "Yes" : "No"}</>;
  if (typeof value !== "object") return <>{String(value)}</>;
  if (depth > 8) return <span>See the JSON evidence download for the full source structure.</span>;
  if (Array.isArray(value)) return value.length ? <ol className={styles.values}>{value.map((entry, index) => <li key={index}><RecordValue value={entry} depth={depth+1} /></li>)}</ol> : <span className={styles.muted}>None recorded</span>;
  return <dl className={styles.record}>{Object.entries(value).map(([key, entry]) => <div key={key}><dt>{label(key)}</dt><dd><RecordValue value={entry} depth={depth+1} /></dd></div>)}</dl>;
}

async function CaseEvidence({ params }: { params: Promise<{caseId: string}> }) {
  await connection();
  const {caseId} = await params;
  if (!isUuid(caseId)) notFound();
  const loaded = await attempt(async () => { const payer = await getDemoPayer(); if (!payer) return null; return {payer, evidence: await apiGet<EvidenceOut>(`/api/cases/${seg(caseId)}/evidence?format=json`, {actorId:payer.id})}; });
  if (!loaded.ok) { if (loaded.error.status===404) notFound(); return <ApiProblem error={loaded.error} />; }
  if (!loaded.value) return <NoDemoPayer />;
  const {payer,evidence} = loaded.value;
  const groups: [string,string,Record<string,unknown>[]][] = [
    ["sources","Original source references",evidence.documents], ["extractions","Recorded model extraction",evidence.extractions],
    ["reviews","Human corrections & confirmations",evidence.revisions], ["bills","Original bills",evidence.bills],
    ["charges","Original & recognized charges",evidence.lines], ["findings","Billing findings",evidence.flags],
    ["questions","Provider questions",evidence.questions], ["proposals","Provider proposals",evidence.provider_responses],
    ["decisions","Payer decisions",evidence.payer_decisions], ["approvals","Immutable payment approvals",evidence.approvals],
    ["external","Prior external payment evidence",evidence.external_payments], ["invoices","PayPal invoice observations",evidence.paypal_invoices],
    ["payments","PayPal transaction evidence",evidence.paypal_payments], ["ledger","Saved financial history",evidence.ledger],
  ];
  return <div className={styles.page}>
    <div className={styles.heading}><PageHeader title="History" back={{href:`/cases/${caseId}`,label:evidence.case.case_reference}} meta={<p>{evidence.case.patient_alias} — the original evidence and the decisions made from it.</p>} /><DemoIdentityNote name={payer.display_name} />
    <nav className={styles.nav} aria-label="Case"><Link href={`/cases/${caseId}`}>Overview</Link><Link href={`/cases/${caseId}?tab=documents`}>Bill &amp; evidence</Link><Link href={`/cases/${caseId}#questions`}>Questions</Link><Link href={`/cases/${caseId}?tab=payments`}>Payments</Link><Link href={`/cases/${caseId}?tab=history`} aria-current="page">Activity &amp; evidence</Link></nav></div>
    <FinancialStrip buckets={evidence.buckets} />
    <div className={styles.columns}>
      <Section id="chronology" title="What happened" description="Each person’s review stays distinct from model output and PayPal verification.">
        {evidence.activity.length ? <ol className={styles.timeline}>{evidence.activity.map((event) => <li key={event.id}><h3>{activityLabel(event.event_type)}</h3><p>{event.actor_label}</p><time dateTime={event.created_at}>{formatDateTime(event.created_at)}</time>{event.ledger_entry_id ? <p className={styles.effect}>Money record saved — see the financial history below.</p> : null}</li>)}</ol> : <EmptyState title="No activity recorded yet"><p>Upload a source document to begin the record.</p></EmptyState>}
      </Section>
      <Section id="export" title="Keep a private copy" description="Preview the contents before downloading."><div className={styles.export}><p>The evidence pack preserves the original extraction, human corrections, provider proposals, payer decisions, exact approval snapshots and verified transaction observations.</p><ul><li>Source references and evidence excerpts</li><li>Amounts, currencies, actors and timestamps</li><li>Original charges, adjustments and financial history</li></ul><p>Private access links, upload/provider tokens, storage locations, credentials and raw webhook payloads are excluded.</p><div className={styles.downloads}><a href={`/cases/${caseId}/evidence/download?format=html`} download>Download readable HTML</a><a href={`/cases/${caseId}/evidence/download?format=json`} download>Download structured JSON</a></div><p className={styles.muted}>These downloads contain case evidence. Share them deliberately. Recorded extraction is a mock replay; an export does not establish OCR accuracy or verify a receipt’s authenticity.</p></div></Section>
    </div>
    <Section id="record" title="Inside the evidence pack" description="Open a section to inspect its provenance. Decimal amounts retain their recorded currency and precision."><div className={styles.groups}>{groups.map(([id,title,records]) => <details key={id} id={id} className={styles.group}><summary>{title}<span>{records.length} {records.length===1?"record":"records"}</span></summary>{records.length ? records.map((record,index) => <div className={styles.recordSheet} key={String(record.id ?? index)}><RecordValue value={record} /></div>) : <p className={styles.none}>None recorded. No outcome has been inferred.</p>}</details>)}</div></Section>
  </div>;
}
