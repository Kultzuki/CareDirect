"use client";

import { useState } from "react";
import { Button, ButtonLink, MoneyText } from "@/components/ui";
import type { CareEpisodeOut } from "@/lib/types";
import { EpisodeControls } from "./EpisodeControls";
import { EpisodeEvidence } from "./EpisodeEvidence";
import { EpisodeTimeline } from "./EpisodeTimeline";
import styles from "./EpisodeIntelligence.module.css";

export function EpisodeIntelligence({ episode, canReview = true, canManage = true }: { episode: CareEpisodeOut; canReview?: boolean; canManage?: boolean }) {
  const [view, setView] = useState("documents");
  const advice = episode.ai_insights;
  return <section className={styles.container} aria-labelledby="episode-intelligence-title">
    <div className={styles.headerRow}>
      <div className={styles.titleArea}><h2 id="episode-intelligence-title">Treatment: {episode.episode_title}</h2><p>{episode.patient_alias} · {episode.documents.length} connected records</p></div>
      <span className={styles.badgePill}>{advice.provider === "deepseek" ? "AI advice · review required" : "Document check"}</span>
    </div>
    {episode.clinical_context && <p>{episode.clinical_context}</p>}
    <div className={styles.links}><ButtonLink href={`/cases/${episode.case_id}?tab=documents`} variant="secondary">Add or review episode documents</ButtonLink><ButtonLink href={`/cases/${episode.case_id}?tab=comparison`} variant="quiet">Estimate vs final bill</ButtonLink><ButtonLink href={`/cases/${episode.case_id}?tab=insurance`} variant="quiet">Insurance and family share</ButtonLink><ButtonLink href={`/cases/${episode.case_id}?tab=family`} variant="quiet">Family contributions and permissions</ButtonLink></div>
    <div className={styles.summaryBox}>
      <h3>Episode review</h3><p>{advice.clinical_summary}</p>
      <p>{advice.affinity_explanation}</p>
      {advice.analysis_status === "stale" && <p>Previous AI advice is stale because episode evidence or model settings changed.</p>}
      {advice.analysis_status === "provider_unavailable" && <p>The model request failed or returned invalid evidence. Local review is shown.</p>}
      {!!advice.key_findings?.length && <ul>{advice.key_findings.map((text, index) => <li key={index}>{text}</li>)}</ul>}
      {!!advice.payer_recommendations?.length && <details><summary>Review suggestions</summary><ul>{advice.payer_recommendations.map((text, index) => <li key={index}>{text}</li>)}</ul></details>}
    </div>
    {!!episode.warnings.length && <ul className={styles.warnings}>{episode.warnings.map((text, index) => <li key={`${index}-${text}`}>{text}</li>)}</ul>}
    <div className={styles.tabsRow} aria-label="Episode views">
      <Button variant="quiet" aria-pressed={view === "documents"} onClick={() => setView("documents")}>Documents ({episode.documents.length})</Button>
      <Button variant="quiet" aria-pressed={view === "timeline"} onClick={() => setView("timeline")}>Timeline ({episode.timeline.length})</Button>
    </div>
    {view === "documents" ? <>
      {!episode.documents.length ? <p>No documents yet. Add all records for this treatment to this episode.</p> : <div className={styles.tableWrapper} tabIndex={0} role="region" aria-label="Scrollable episode documents">
        <table className={styles.docTable}><caption className="cd-visually-hidden">All episode evidence, including documents awaiting extraction</caption>
          <thead><tr><th scope="col">Document and evidence</th><th scope="col">Date</th><th scope="col">Amount</th><th scope="col">Does this belong to this treatment?</th></tr></thead>
          <tbody>{episode.documents.map((doc) => {
            const assessment = advice.document_assessments?.find((item) => item.document_id === doc.id);
            return <tr key={doc.id}>
              <td><strong>{doc.name}</strong><p>{doc.category.replaceAll("_", " ")} · {doc.extraction_status}</p><p>{doc.is_recorded ? "Recorded in case" : "Document only; not added to the bill"}{doc.is_synthetic ? " · Sample document" : ""}</p>
                {doc.source_available && <p>{doc.extraction_status === "EXTRACTED" ? <a href={`/cases/${episode.case_id}/review/${doc.id}`}>Check document details</a> : <a href={`/cases/${episode.case_id}?tab=documents#documents`}>Extract or review document</a>}{" · "}<a href={`/cases/${episode.case_id}/documents/${doc.id}/source`} target="_blank" rel="noreferrer">Open source</a></p>}
                {!!doc.lines.length && <details><summary>Source lines ({doc.lines.length})</summary>{doc.lines.map((line) => <div key={line.id} className={styles.sourceLine}>
                  <p>Line {line.line_number}: {line.description ?? "Description missing"}</p><p>Service date: {line.service_date ?? "Unknown"}</p>
                  <EpisodeEvidence sources={line.sources} caseId={episode.case_id} documentId={doc.source_available ? doc.id : undefined} />
                </div>)}</details>}
                {!!doc.sources.length && <details><summary>Document field evidence</summary><EpisodeEvidence sources={doc.sources} caseId={episode.case_id} documentId={doc.source_available ? doc.id : undefined} /></details>}
              </td>
              <td>{doc.date ?? "Unknown"}<p>{doc.date_basis.replaceAll("_", " ")}</p></td>
              <td>{doc.amount !== null && doc.currency ? <MoneyText value={doc.amount} currency={doc.currency} /> : "Not supplied"}</td>
              <td><strong>{doc.affinity_status}</strong><p>{doc.affinity_reason}</p>{doc.is_overlapping && <p className={styles.overlapBadge}>Possible overlap</p>}{assessment && <p>AI suggestion: {assessment.status.replaceAll("_", " ")} — {assessment.reason}</p>}</td>
            </tr>;
          })}</tbody>
        </table>
      </div>}
      <dl className={styles.financialStrip}>
        {[["Bill evidence total (before review)", episode.total_billed], ["Possible overlap exposure (not deducted)", episode.potential_overlap_amount], ["Recorded bill charges", episode.recorded_bill_total], ["Confirmed adjustments", episode.confirmed_adjustments], ["Recorded net charges", episode.net_episode_total], ["Reconciled payments", episode.already_paid], [episode.documents.some((d) => ["INSURANCE_PREAUTH", "INSURANCE_SETTLEMENT", "INSURER_PAYMENT"].includes(d.document_type)) ? "Hospital balance before insurance is split (see insurance)" : "Payable bucket (approval required)", episode.payable_now]].map(([label, value]) => <div className={styles.financialItem} key={label}><dt>{label}</dt><dd><MoneyText value={value} currency={episode.currency} /></dd></div>)}
      </dl>
      <div className={styles.form}><h3>Duplicate and overlap review</h3><p>Level 1 checks exact entries on a bill. Level 2 checks possible same services under different names. Level 3 checks separate bills and package inclusions, including laboratory invoices from another provider. AI service-name suggestions run only when you request analysis; local CBC aliases work without AI.</p><p>These questions do not authorize deductions. Use Refresh bill checks below to add questions to the provider review workflow.</p>{!episode.overlaps.length && <p>No near-duplicate or cross-document questions found in the currently reviewed evidence. This does not verify that every charge is distinct.</p>}{episode.overlaps.map((finding, index) => <details key={index}><summary>{finding.overlap_type === "NEAR_DUPLICATE" ? "Level 2" : "Level 3"} · {finding.title}</summary><p>{finding.description}</p><p>Amount to clarify: <MoneyText value={finding.amount} currency={finding.currency} /></p>{finding.sources.map((line) => <div key={`${line.document_id}:${line.id}`} className={styles.sourceLine}><p>Document {line.document_id.slice(0, 8)} · Line {line.line_number}: {line.description}</p><p>Service date: {line.service_date ?? "Unknown"} · Quantity: {line.quantity ?? "Unknown"} · Code: {line.code ?? "Not supplied"}</p>{line.line_total !== null && <p>Line amount: <MoneyText value={line.line_total} currency={finding.currency} /></p>}<EpisodeEvidence sources={line.sources} caseId={episode.case_id} documentId={line.source_available ? line.document_id : undefined} /></div>)}</details>)}</div>
    </> : <EpisodeTimeline timeline={episode.timeline} currency={episode.currency} caseId={episode.case_id} />}
    <EpisodeControls episode={episode} canReview={canReview} canManage={canManage} />
  </section>;
}
