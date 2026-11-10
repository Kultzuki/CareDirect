"use client";

import { useState } from "react";
import type { CareEpisodeOut, CaseDetailOut, EpisodeOverlapOut } from "@/lib/types";
import { MoneyText } from "@/components/ui";
import { EpisodeEvidence } from "@/components/episode/EpisodeEvidence";
import { WorkspaceAction } from "@/components/case/WorkspaceAction";
import styles from "./Intelligence.module.css";

export function DuplicateWorkbench({ episode, detail }: { episode: CareEpisodeOut; detail: CaseDetailOut }) {
  const [level, setLevel] = useState("all");
  const [selectedId, setSelectedId] = useState("");
  const [left, setLeft] = useState(0);
  const [right, setRight] = useState(1);
  const findings = episode.overlaps.map((finding, index) => ({ ...finding, id: `episode-${index}`, level: finding.overlap_type === "NEAR_DUPLICATE" ? "2" : "3", flagId: detail.flags.find((flag) => (finding.line_item_ids.length > 0 && flag.line_item_ids.length === finding.line_item_ids.length && finding.line_item_ids.every((id) => flag.line_item_ids.includes(id)) && flag.flag_type === (finding.overlap_type === "NEAR_DUPLICATE" ? "POSSIBLE_NEAR_DUPLICATE" : "CROSS_DOCUMENT_OVERLAP")))?.id }));
  for (const flag of detail.flags.filter((flag) => flag.flag_type === "POSSIBLE_EXACT_DUPLICATE")) {
    const sources: EpisodeOverlapOut["sources"] = episode.documents.flatMap((doc) => doc.lines.filter((line) => line.ledger_line_id && flag.line_item_ids.includes(line.ledger_line_id)).map((line) => ({ ...line, document_id: doc.id, source_available: doc.source_available })));
    findings.push({ id: flag.id, level:"1", flagId:flag.id, overlap_type:"EXACT_DUPLICATE", title:"Possible exact duplicate", description:flag.explanation, amount:flag.amount_involved ?? "0.00", currency:detail.currency, sources, line_item_ids:flag.line_item_ids, involved_document_ids:[...new Set(sources.map((line) => line.document_id))] });
  }
  const visible = findings.filter((finding) => level === "all" || level === finding.level);
  const selected = visible.find((finding) => finding.id === selectedId) ?? visible[0];
  return <div className={styles.layout}>
    <div className={styles.toolbar}><label>What to check<select value={level} onChange={(event) => setLevel(event.target.value)}><option value="all">All review questions</option><option value="1">Same details repeated</option><option value="2">Same service, different name</option><option value="3">Same service on different bills</option></select></label>{detail.family_permissions.can_review && <WorkspaceAction caseId={detail.id} action="checks" label="Refresh bill checks" />}</div>
    <div className={styles.split}><section className={styles.panel} aria-labelledby="duplicate-comparison-heading"><h2 id="duplicate-comparison-heading">Compare the evidence</h2><p className={styles.muted}>A match is a question for human review. Nothing is removed from the bill.</p>
      {!selected ? <div className={styles.selected}><h3>No matching review questions</h3><p>Review your document fields, refresh bill checks, or request explicit AI service matching from the care timeline. Opening this tab does not contact an AI service.</p><a href={`/cases/${detail.id}?tab=documents`}>Add or review source documents</a></div> : <><div className={styles.selected}><span className={styles.badge}>Level {selected.level} · Human review required</span><h3>{selected.title}</h3><details><summary>Why this was flagged and what to check</summary><p>{selected.description}</p></details><p>Amount to clarify: <MoneyText value={selected.amount} currency={selected.currency} /></p></div><div className={styles.pair}>{[0,1].map((side) => {
        const index = side === 0 ? left : right;
        const source = selected.sources[index] ?? selected.sources[side] ?? selected.sources[0];
        if (!source) return <div className={styles.paper} key={side}>Source lines are unavailable. Review the recorded billing question.</div>;
        const doc = episode.documents.find((item) => item.id === source.document_id);
        return <article className={styles.paper} key={side}><header><label>{side === 0 ? "First source" : "Comparison source"}<select value={selected.sources.indexOf(source)} onChange={(event) => side === 0 ? setLeft(Number(event.target.value)) : setRight(Number(event.target.value))}>{selected.sources.map((line, n) => <option key={`${line.id}-${n}`} value={n}>{episode.documents.find((item) => item.id === line.document_id)?.provider ?? "Recorded document"} · Line {line.line_number}</option>)}</select></label></header><h3>{doc?.name ?? "Recorded billing evidence"}</h3><blockquote>{source.description}</blockquote><dl><dt>Service date</dt><dd>{source.service_date ?? "Unknown"}</dd><dt>Quantity / code</dt><dd>{source.quantity ?? "Unknown"} / {source.code ?? "Not supplied"}</dd><dt>Line amount</dt><dd>{source.line_total ? <MoneyText value={source.line_total} currency={selected.currency} /> : "Unknown"}</dd></dl><EpisodeEvidence caseId={detail.id} documentId={source.source_available ? source.document_id : undefined} sources={source.sources} />{source.source_available ? <details><summary>View original document</summary><iframe src={`/cases/${detail.id}/documents/${source.document_id}/source`} title={`${side === 0 ? "First" : "Comparison"} original document`} /></details> : <p className={styles.muted}>Manually recorded bill; no original upload is linked.</p>}</article>;
      })}</div>{selected.flagId && <p><a href={`/cases/${detail.id}#question-${selected.flagId}`}>Ask the hospital about this charge</a></p>}</>}
    </section><aside className={styles.rail}><section className={styles.panel}><h2>Review queue <span className={styles.badge}>{visible.length}</span></h2><div className={styles.list}>{visible.map((finding) => <button className={styles.candidate} key={finding.id} aria-pressed={finding.id === selected?.id} onClick={() => { setSelectedId(finding.id); setLeft(0); setRight(1); }}><small>Level {finding.level} · {finding.involved_document_ids.length > 1 ? "Across documents" : "Within one bill"}</small><strong>{finding.title}</strong><small>Source lines {finding.sources.map((source) => source.line_number).join(" / ")}</small><span><MoneyText value={finding.amount} currency={finding.currency} /></span></button>)}</div></section><section className={styles.panel}><h2>Before deciding</h2><ul><li>Check dates, quantities and service codes.</li><li>Confirm whether a package included the service.</li><li>Ask the provider before agreeing an adjustment.</li></ul></section></aside></div>
  </div>;
}
