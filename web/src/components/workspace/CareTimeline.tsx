"use client";

import { useState } from "react";
import type { CareEpisodeOut } from "@/lib/types";
import { MoneyText } from "@/components/ui";
import { EpisodeEvidence } from "@/components/episode/EpisodeEvidence";
import styles from "./Intelligence.module.css";

export function CareTimeline({ episode }: { episode: CareEpisodeOut }) {
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const events = episode.timeline.filter((event) => (kind === "all" || event.event_type === kind) && `${event.title} ${event.detail}`.toLowerCase().includes(query.toLowerCase()));
  const dated = events.filter((event) => event.event_date);
  const stamps = dated.map((event) => Date.parse(event.event_date!)).filter(Number.isFinite);
  const first = stamps.length ? Math.min(...stamps) : 0;
  const last = stamps.length ? Math.max(...stamps) : 0;
  const span = Math.max(last - first, 86400000);
  const types = [...new Set(events.map((event) => event.event_type))];
  const selected = events.find((event) => event.id === selectedId) ?? events[0];
  const dateLabel = (date: number) => new Date(date).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric", timeZone: "UTC" });
  return <div className={styles.split}>
    <section className={styles.panel} aria-labelledby="care-timeline-heading"><h2 id="care-timeline-heading">Treatment record timeline</h2><p className={styles.muted}>See when documents were issued and when services were listed. A service on a bill does not prove the treatment was completed.</p>
      <div className={styles.toolbar}><label>Find an event<input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search services or records" /></label><label>Record type<select value={kind} onChange={(event) => setKind(event.target.value)}><option value="all">All record types</option>{[...new Set(episode.timeline.map((event) => event.event_type))].map((type) => <option key={type} value={type}>{type.replaceAll("_", " ").toLowerCase()}</option>)}</select></label></div>
      {!events.length ? <p>No matching events. Add documents or clear the filters.</p> : <div className={styles.scroll} role="region" tabIndex={0} aria-label="Scrollable treatment timeline"><div className={styles.canvas}><div className={styles.axis}><strong>Type of record</strong><div className={styles.axisDates}>{stamps.length ? [...new Set([0,.25,.5,.75,1].map((step) => dateLabel(first + span * step)))].map((label) => <span key={label}>{label}</span>) : <span>No stated dates</span>}</div></div>{types.map((type) => <div className={styles.lane} key={type}><div className={styles.laneLabel}>{type.replaceAll("_", " ").toLowerCase()}</div><div className={styles.track}>{dated.filter((event) => event.event_type === type).map((event) => <button key={event.id} className={styles.event} style={{ left: `${Math.min(96, (Date.parse(event.event_date!) - first) / span * 96)}%`, background: `var(--cd-chart-${["SURGERY","DIAGNOSTICS","PHARMACY","CONSULTATION"].includes(event.event_type) ? "purple" : ["RECEIPT","PAYMENT","PROVIDER_RESPONSE","PAYER_DECISION"].includes(event.event_type) ? "teal" : "blue"})` }} title={`${event.event_date}: ${event.title}`} aria-label={`${event.event_date}: ${event.title}`} aria-pressed={event.id === selected?.id} onClick={() => setSelectedId(event.id)} />)}</div></div>)}</div></div>}
      {!!events.filter((event) => !event.event_date).length && <details><summary>Records with unknown dates ({events.filter((event) => !event.event_date).length})</summary><ul>{events.filter((event) => !event.event_date).map((event) => <li key={event.id}><button onClick={() => setSelectedId(event.id)}>{event.title}</button></li>)}</ul></details>}
      <div className={styles.legend}><span>Recorded evidence</span><span>Listed services</span><span>Financial events</span></div>
      {selected && <div className={styles.selected}><span>{selected.event_date ?? "Date unknown"} · {selected.date_basis.replaceAll("_", " ")}</span><h3>{selected.title}</h3><p>{selected.detail}</p>{selected.amount && <p><MoneyText value={selected.amount} currency={selected.currency ?? episode.currency} /></p>}<EpisodeEvidence caseId={episode.case_id} documentId={selected.document_id ?? undefined} sources={selected.sources} /></div>}
    </section>
    <aside className={styles.rail}><section className={styles.panel}><h2>Hospital bills</h2><p className={styles.muted}>Bill totals before checking for repeated charges</p><p><MoneyText value={episode.total_billed} currency={episode.currency} /></p><ul className={styles.list}>{episode.documents.filter((doc) => doc.document_type === "BILL").map((doc) => <li key={doc.id}><strong>{doc.provider ?? "Provider not supplied"}</strong><small>{doc.date ?? "Date unknown"} · {doc.review_state.replaceAll("_", " ")}</small>{doc.amount && <MoneyText value={doc.amount} currency={doc.currency ?? episode.currency} />}</li>)}</ul></section><section className={styles.panel}><h2>Records to complete</h2><p>{episode.documents.filter((doc) => ["awaiting_extraction", "needs_review"].includes(doc.review_state)).length} documents still need to be read or checked.</p><p className={styles.muted}>Only uploaded records are shown. Ask the hospital if you think something is missing.</p><a href={`/cases/${episode.case_id}?tab=documents`}>Add or check documents</a></section></aside>
  </div>;
}
