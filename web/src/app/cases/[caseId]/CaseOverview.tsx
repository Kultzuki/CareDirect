import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { connection } from "next/server";
import { Suspense } from "react";

import { CaseStatusBadge } from "@/components/CaseStatusBadge";
import { ApiProblem, DemoIdentityNote, NoDemoPayer } from "@/components/PageProblems";
import { FinancialStrip } from "@/components/case/FinancialStrip";
import { DismissFinding } from "@/components/case/DismissFinding";
import { QuestionForm } from "@/components/case/QuestionForm";
import { ResponseDecision } from "@/components/case/ResponseDecision";
import { RevokeLink, WorkspaceAction } from "@/components/case/WorkspaceAction";
import { ReceiptReview } from "@/components/case/ReceiptReview";
import { ButtonLink, EmptyState, EvidenceRef, MoneyText, Notice, PageHeader, Section, StatusBadge } from "@/components/ui";
import { apiGet, seg } from "@/lib/api";
import { getDemoPayer } from "@/lib/demo-identity";
import { formatDateTime } from "@/lib/format";
import { attempt } from "@/lib/load";
import { RESPONSE_LABELS, type ProviderWorkflowOut } from "@/lib/provider-types";
import type { AuditEventOut, CareEpisodeOut, CaseDetailOut, FlagOut } from "@/lib/types";
import { isUuid } from "@/lib/validation";

import styles from "@/components/case/workspace.module.css";

export const metadata: Metadata = { title: "Case workspace", robots: { index: false, follow: false } };

export default function CasePage({ params }: { params: Promise<{ caseId: string }> }) {
  return <Suspense fallback={<div className={styles.skeleton} aria-label="Loading case workspace" />}><CaseWorkspace params={params} /></Suspense>;
}

const FLAG_LABELS: Record<string, string> = {
  POSSIBLE_EXACT_DUPLICATE: "Level 1 · Possible exact duplicate",
  POSSIBLE_NEAR_DUPLICATE: "Same service, different name — review required",
  ARITHMETIC_MISMATCH: "Arithmetic needs review",
  ADVANCE_PAYMENT_MISMATCH: "Payment evidence needs review",
  ESTIMATE_DRIFT: "Estimate needs clarification",
  CROSS_DOCUMENT_OVERLAP: "Level 3 · Cross-document overlap needs clarification",
};

const FLAG_STATES: Record<string, string> = { OPEN: "Needs review", SUBMITTED_TO_PROVIDER: "Awaiting provider", PROVIDER_RESPONDED: "Response to review", RESOLVED: "Resolved", DISMISSED: "Dismissed after review" };

function QuestionCard({ flag, detail, workflow }: { flag: FlagOut; detail: CaseDetailOut; workflow: ProviderWorkflowOut }) {
  const allLines = detail.bills.flatMap((bill) => bill.line_items);
  const lines = allLines.filter((line) => flag.line_item_ids.includes(line.id));
  const responses = workflow.responses.filter((response) => response.flag_id === flag.id);
  const links = workflow.links.filter((link) => link.flag_id === flag.id);
  const resolved = ["RESOLVED", "DISMISSED"].includes(flag.status);
  const awaiting = links.some((link) => link.state === "ACTIVE");
  const undecided = responses.some((response) => !workflow.decisions.some((decision) => decision.response_id === response.id));
  const availableLines = lines.filter((line) => !links.some((link) => link.line_item_id === line.id && link.state === "ACTIVE") && !responses.some((response) => response.line_item_id === line.id && !workflow.decisions.some((decision) => decision.response_id === response.id)));
  return <article className={`${styles.sheet} ${resolved ? "" : styles.attention}`} id={`question-${flag.id}`} data-testid={`question-${flag.id}`}>
    <div className={styles.eyeline}><h3>{FLAG_LABELS[flag.flag_type] ?? "Needs clarification"}</h3><StatusBadge tone={resolved ? "confirmed" : "needs-review"}>{FLAG_STATES[flag.status] ?? flag.status}</StatusBadge></div>
    <p>{flag.explanation}</p>
    {flag.amount_involved ? <p className={styles.muted}>Amount involved <MoneyText value={flag.amount_involved} currency={detail.currency} /></p> : null}
    {lines.map((line) => <div className={styles.rule} key={line.id}><p><strong>Line {line.line_number}: {line.description_raw}</strong> <MoneyText value={line.line_total} currency={line.currency} /></p>{line.source_page ? <EvidenceRef page={line.source_page} snippet={line.source_text} /> : null}</div>)}
    {responses.map((response) => {
      const decision = workflow.decisions.find((item) => item.response_id === response.id);
      return <div className={styles.rule} key={response.id} data-testid={`response-${response.id}`}>
        <p><strong>{RESPONSE_LABELS[response.response_type]}</strong></p>
        <p>{response.response_text}</p>
        {response.corrected_amount !== null ? <p>Proposed charge <MoneyText value={response.corrected_amount} currency={response.currency} /></p> : null}
        <p className={styles.muted}>{response.responder_label} (self-reported), {formatDateTime(response.responded_at)}. Access verified by scoped link.</p>
        {decision ? <div className={styles.rule}><StatusBadge tone={decision.decision === "ACCEPT" ? "confirmed" : "needs-review"}>{decision.decision === "ACCEPT" ? "Resolution accepted" : decision.decision === "KEEP_OPEN" ? "Question kept open" : "Response rejected"}</StatusBadge><p>{decision.note}</p><p className={styles.muted}>{decision.actor_label}, {formatDateTime(decision.created_at)}</p>{decision.decision === "ACCEPT" ? <p>Recognized charge <MoneyText value={decision.recognized_amount} currency={decision.currency} /> · Adjustment <MoneyText value={decision.adjustment} currency={decision.currency} /></p> : null}</div> : null}
        {detail.family_permissions.can_review && <ResponseDecision key={`decision-${response.id}`} caseId={detail.id} responseId={response.id} recorded={Boolean(decision)} />}
      </div>;
    })}
    {detail.family_permissions.can_review && !resolved && lines.length > 0 ? <QuestionForm caseId={detail.id} flagId={flag.id} lines={availableLines} /> : null}
    {!resolved && awaiting ? <p className={styles.rule}>A provider link is active. The charge stays held while you wait. You can revoke the link below to replace it.</p> : null}
    {!resolved && lines.length === 0 ? <p className={styles.rule}>This finding concerns the supplied document or payment evidence. Review it in <Link href={`/cases/${detail.id}?tab=documents`}>Bill &amp; evidence</Link> before proceeding.</p> : null}
    {flag.resolution_note ? <p className={styles.rule}><strong>Resolution:</strong> {flag.resolution_note}</p> : null}
    {detail.family_permissions.can_review && !resolved && !awaiting && !undecided ? <DismissFinding caseId={detail.id} flagId={flag.id} /> : null}
  </article>;
}

async function CaseWorkspace({ params }: { params: Promise<{ caseId: string }> }) {
  await connection();
  const { caseId } = await params;
  if (!isUuid(caseId)) notFound();
  const loaded = await attempt(async () => {
    const payer = await getDemoPayer();
    if (!payer) return null;
    const [detail, workflow, activity, episode] = await Promise.all([
      apiGet<CaseDetailOut>(`/api/cases/${seg(caseId)}`, { actorId: payer.id }),
      apiGet<ProviderWorkflowOut>(`/api/cases/${seg(caseId)}/provider-workflow`, { actorId: payer.id }),
      apiGet<AuditEventOut[]>(`/api/cases/${seg(caseId)}/audit-events`, { actorId: payer.id }),
      apiGet<CareEpisodeOut>(`/api/cases/${seg(caseId)}/episode`, { actorId: payer.id }),
    ]);
    return { payer, detail, workflow, activity, episode };
  });
  if (!loaded.ok) { if (loaded.error.status === 404) notFound(); return <ApiProblem error={loaded.error} />; }
  if (!loaded.value) return <NoDemoPayer />;
  const { payer, detail, workflow, activity, episode } = loaded.value;
  const lines = detail.bills.flatMap((bill) => bill.line_items);
  const openFlags = detail.flags.filter((flag) => !["RESOLVED", "DISMISSED"].includes(flag.status));
  const provider = [...new Set(detail.bills.map((bill) => bill.provider_name))].join(", ");
  const orderedActivity = [...activity].sort((a, b) => b.seq - a.seq).slice(0, 20);
  const pageTitle = detail.episode_title || detail.case_reference;
  return <div className={styles.page}>
    <PageHeader title={pageTitle} back={{ href: "/cases", label: "All cases" }} meta={<div className={styles.meta}><p>{detail.patient_alias}</p><p>{detail.case_reference}</p><p>{provider || "Provider not supplied yet"}</p><CaseStatusBadge status={detail.status} /></div>} actions={<span className={styles.headerAction}><ButtonLink href={`/cases/${caseId}?tab=documents`} variant="secondary">Bill &amp; evidence</ButtonLink></span>} />
    <DemoIdentityNote name={payer.display_name} />
    <nav className={styles.nav} aria-label="Case"><Link href={`/cases/${caseId}`} aria-current="page">Overview</Link><Link href={`/cases/${caseId}?tab=documents`}>Bill &amp; evidence</Link><Link href="#questions">Questions {openFlags.length > 0 ? `(${openFlags.length})` : ""}</Link><Link href={`/cases/${caseId}?tab=payments`}>Payments</Link><Link href={`/cases/${caseId}?tab=history`}>Activity &amp; evidence</Link></nav>
    <section className={styles.sheet} aria-labelledby="episode-snapshot-heading"><h2 id="episode-snapshot-heading">Your care episode at a glance</h2><p>{episode.documents.length} connected records · {episode.overlaps.length} possible overlap questions · {episode.timeline.length} evidence events</p><div className={styles.nav}><ButtonLink href={`/cases/${caseId}?tab=timeline`} variant="quiet">Open treatment timeline</ButtonLink><ButtonLink href={`/cases/${caseId}?tab=duplicates`} variant="quiet">Compare duplicate evidence</ButtonLink><ButtonLink href={`/cases/${caseId}?tab=family`} variant="quiet">Family finances</ButtonLink></div></section>
    <FinancialStrip buckets={detail.buckets} />
    {!detail.buckets.consistent ? <Notice tone="error" title="These amounts need checking"><ul>{detail.buckets.issues.map((issue) => <li key={issue}>{issue}</li>)}</ul></Notice> : null}
    <div className={styles.columns}>
      <Section id="attention" title="What needs your attention" description={openFlags.length ? "Check the source, ask a specific question, then review the provider’s reply." : "Review the supplied charges before approving any payment."}>
        <div className={styles.stack}>
          {openFlags.length ? <ul className={styles.timeline}>{openFlags.map((flag) => <li key={flag.id}><Link href={`#question-${flag.id}`}>{FLAG_LABELS[flag.flag_type] ?? "Needs clarification"}</Link><p className={styles.muted}>{FLAG_STATES[flag.status]}</p></li>)}</ul> : <EmptyState title="No open billing questions"><p>Accepted resolutions stay in the activity record and original bill.</p></EmptyState>}
          {detail.buckets.pending_review !== "0.00" ? <p><Link href="#bill-lines">Review the remaining charges</Link> before payment approval.</p> : null}
          {detail.family_permissions.can_review && <WorkspaceAction caseId={caseId} action="checks" label="Refresh bill checks" />}
        </div>
      </Section>
      <Section id="supplied" title="The record so far">
        <div className={styles.sheet}><dl className={styles.stack}><div><dt>Supplied bills</dt><dd>{detail.bills.length}</dd></div><div><dt>External payment evidence</dt><dd>{detail.external_payments.length ? detail.external_payments.map((payment) => <ReceiptReview key={payment.id} caseId={caseId} payment={payment} canReview={detail.family_permissions.can_review} />) : "None supplied"}</dd></div></dl><p className={`${styles.muted} ${styles.rule}`}>Provider responses are proposals. Accepted resolutions and verified payments have separate entries in the record.</p></div>
      </Section>
    </div>
    <Section id="questions" title="Questions & provider replies" description="Clarify the bill without losing the original evidence. A private link gives access to one charge only.">
      <div className={styles.stack}>{detail.flags.length ? detail.flags.map((flag) => <QuestionCard flag={flag} detail={detail} workflow={workflow} key={flag.id} />) : <EmptyState title="No questions yet"><p>Refresh bill checks to look for arithmetic, duplicate or estimate differences in the supplied evidence.</p></EmptyState>}</div>
    </Section>
    <Section id="bill-lines" title="Bill charges" description="Original bill amounts stay saved. Any agreed change is shown beside the original charge.">
      <div className={styles.sheet}>{lines.length ? <ul className={styles.lineList}>{lines.map((line) => {
        return <li className={styles.line} key={line.id} data-testid={`line-${line.id}`}><div><h3>{line.line_number}. {line.description_raw}</h3><div className={styles.lineMeta}><span>{line.status === "ACCEPTED" ? "Accepted by payer" : line.status === "QUERIED" ? "Held for clarification" : "Needs payer review"}</span>{line.code ? <span>Code {line.code}</span> : null}</div>{line.source_page ? <EvidenceRef page={line.source_page} snippet={line.source_text} /> : null}</div><div className={styles.amount}><MoneyText value={line.line_total} currency={line.currency} />{line.recognized_amount !== line.line_total ? <p className={styles.muted}>Now <MoneyText value={line.recognized_amount} currency={line.currency} /></p> : null}</div>{detail.family_permissions.can_review && line.status === "PENDING_REVIEW" ? <div className={styles.actions}><WorkspaceAction caseId={caseId} action="accept" entityId={line.id} label={`Accept line ${line.line_number} after review`} /></div> : null}</li>;
      })}</ul> : <EmptyState title="No charges added yet"><p><Link href={`/cases/${caseId}?tab=documents`}>Upload a bill and review its extraction</Link> to add charges to the case.</p></EmptyState>}</div>
    </Section>
    {workflow.links.length ? <Section id="link-history" title="Provider link history" description="Links are created, not delivered. Tokens cannot be recovered from history."><ul className={styles.timeline}>{workflow.links.map((link) => <li key={link.id}><p>{link.question}</p><p className={styles.muted}>{link.state === "REVOKED" ? "Revoked" : link.state === "RESPONDED" ? "Response recorded" : link.state === "EXPIRED" ? "Expired" : "Active"} · expires {formatDateTime(link.expires_at)}</p>{detail.family_permissions.can_review && link.state === "ACTIVE" ? <RevokeLink caseId={caseId} flagId={link.flag_id} linkId={link.id} /> : null}</li>)}</ul></Section> : null}
    <Section id="activity" title="Case activity" description="An append-only record of extraction, human review and financial decisions."><div>{orderedActivity.length ? <ol className={styles.timeline}>{orderedActivity.map((event) => <li key={event.id}><p><strong>{event.event_type.toLowerCase().replaceAll("_", " ")}</strong></p><p>{event.actor_label}</p><time dateTime={event.created_at}>{formatDateTime(event.created_at)}</time></li>)}</ol> : <EmptyState title="The case is ready for its first document" />}</div></Section>
  </div>;
}
