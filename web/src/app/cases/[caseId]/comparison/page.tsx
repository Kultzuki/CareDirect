import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { connection } from "next/server";
import { Suspense } from "react";

import { ApiProblem, NoDemoPayer } from "@/components/PageProblems";
import { Button, ButtonLink, MoneyText, PageHeader, Section } from "@/components/ui";
import { apiGet, seg } from "@/lib/api";
import { getDemoPayer } from "@/lib/demo-identity";
import type { ComparisonLine, ComparisonSource, EstimateComparison } from "@/lib/estimate-comparison-types";
import { attempt } from "@/lib/load";
import { isUuid } from "@/lib/validation";
import styles from "./comparison.module.css";
import { VarianceOverview } from "@/components/workspace/FinancialOverviews";

export const metadata: Metadata = { title: "Estimate vs final bill" };
type Props = {
  params: Promise<{ caseId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

export default function ComparisonPage(props: Props) {
  return <Suspense fallback={<p>Loading comparisonâ€¦</p>}><Comparison {...props} /></Suspense>;
}

function Amount({ value, currency }: { value: string | null | undefined; currency: string }) {
  return value == null ? <span>Not supplied</span> : <MoneyText value={value} currency={currency} />;
}

function Sources({ sources, caseId }: { sources: ComparisonSource[]; caseId: string }) {
  return <ul className={styles.sources}>{sources.map((field, index) => <li key={`${field.path}-${index}`}>
    <span>{field.path.split(".").at(-1)?.replaceAll("_", " ")} · {field.state}{field.needs_review ? " · needs review" : ""}</span>
    {field.source ? <>
      {" â€” "}<a href={`/cases/${seg(caseId)}/documents/${seg(field.source.document_id)}/source#page=${field.source.page}`} target="_blank" rel="noreferrer">
        Source page {field.source.page}
      </a>
      {field.source.snippet ? <q>{field.source.snippet}</q> : <span>Location recorded as a bounding box; open the page to inspect.</span>}
    </> : <span> · No source location recorded</span>}
  </li>)}</ul>;
}

function Lines({ lines, label, currency, caseId }: { lines: ComparisonLine[]; label: string; currency: string; caseId: string }) {
  return <div><h4>{label}</h4>{lines.length ? lines.map((line, index) => <div key={index} className={styles.line}>
    <p>{line.line_number == null ? "Tax" : `Line ${line.line_number}`} · {line.description}</p>
    <p>Quantity: {line.quantity ?? "Not supplied"} · Unit price: <Amount value={line.unit_price} currency={currency} /> · Total: <Amount value={line.line_total} currency={currency} /></p>
    <Sources sources={line.sources} caseId={caseId} />
  </div>) : <p>No matching service line in this document.</p>}</div>;
}

async function Comparison({ params, searchParams }: Props) {
  await connection();
  const { caseId } = await params;
  if (!isUuid(caseId)) notFound();
  const query = await searchParams;
  const selected = new URLSearchParams();
  for (const key of ["estimate_document_id", "final_document_id"]) {
    const value = query[key];
    if (typeof value === "string" && isUuid(value)) selected.set(key, value);
  }
  const loaded = await attempt(async () => {
    const payer = await getDemoPayer();
    if (!payer) return null;
    return apiGet<EstimateComparison>(`/api/cases/${seg(caseId)}/estimate-comparison?${selected}`, { actorId: payer.id });
  });
  if (!loaded.ok) {
    if (loaded.error.status === 404) notFound();
    return <ApiProblem error={loaded.error} />;
  }
  if (!loaded.value) return <NoDemoPayer />;
  const comparison = loaded.value;
  const currency = comparison.currency ?? "INR";
  return <div className={styles.page}>
    <PageHeader title="Estimate vs final bill" back={{ href: `/cases/${caseId}?tab=documents`, label: "Review documents" }} />
    <VarianceOverview comparison={comparison} />
    <Section id="comparison-documents" title="Choose your documents" description="Compare the original estimate with the final bill for the same treatment and provider.">
      <form method="get" className={styles.form}><input type="hidden" name="tab" value="comparison" />
        {(["ESTIMATE", "BILL"] as const).map((kind) => {
          const key = kind === "ESTIMATE" ? "estimate_document_id" : "final_document_id";
          const options = comparison.documents.filter((doc) => doc.document_type === kind);
          return <label key={kind}>{kind === "ESTIMATE" ? "Original estimate" : "Final bill"}
            <select name={key} required defaultValue={selected.get(key) ?? (options.length === 1 ? options[0].id : "")}>
              <option value="" disabled>Select a document</option>
              {options.map((doc) => <option key={doc.id} value={doc.id}>{doc.id.slice(0, 8)} · {doc.created_at.slice(0, 10)} · {doc.extraction_status.replaceAll("_", " ").toLowerCase()}</option>)}
            </select>
          </label>;
        })}
        <Button type="submit">Compare documents</Button>
      </form>
      <ButtonLink variant="quiet" href={`/cases/${caseId}?tab=documents`}>Upload or review documents</ButtonLink>
    </Section>
    {!!comparison.rows.length && <Section id="comparison-services" title="Service comparison" description="Open a service to see every contributing source line. A positive difference means the final bill is higher.">
      <div className={styles.scroll} tabIndex={0} role="region" aria-label="Scrollable service comparison"><table className={styles.table}>
        <caption className="cd-visually-hidden">Estimate and final bill amounts by service</caption>
        <thead><tr><th scope="col">Service</th><th scope="col">Estimate</th><th scope="col">Final bill</th><th scope="col">Difference</th></tr></thead>
        <tbody>{comparison.rows.map((row, index) => <tr key={index}>
          <th scope="row"><details><summary>{row.description}{row.code ? ` (${row.code})` : ""}</summary>
            <div className={styles.evidence}>
              <Lines lines={row.estimate_lines} label="Estimate" currency={currency} caseId={caseId} />
              <Lines lines={row.final_lines} label="Final bill" currency={currency} caseId={caseId} />
            </div>
          </details><ul className={styles.changes}>{row.changes.map((change) => <li key={change}>{change.replaceAll("_", " ")}</li>)}</ul></th>
          <td><Amount value={row.estimate} currency={currency} /></td>
          <td><Amount value={row.final} currency={currency} /></td>
          <td>{row.difference && !row.difference.startsWith("-") && row.difference !== "0.00" ? "+" : ""}<Amount value={row.difference} currency={currency} /></td>
        </tr>)}</tbody>
      </table></div>
    </Section>}
    <Section id="comparison-summary" title="What changed">
      {Object.values(comparison.extraction_providers ?? {}).includes("mock") && <p className={styles.warnings}>Sample results: these details were prepared for the demo. They do not show how well AI reads a new document.</p>}
      <p className={styles.summary}>{comparison.summary}</p>
      {!!comparison.warnings?.length && <ul className={styles.warnings}>{comparison.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>}
      {comparison.currency && <dl className={styles.totals}>
        <div><dt>Estimate total</dt><dd><Amount value={comparison.estimate_total} currency={currency} /></dd></div>
        <div><dt>Final bill total</dt><dd><Amount value={comparison.final_total} currency={currency} /></dd></div>
        <div><dt>Net difference</dt><dd><Amount value={comparison.difference} currency={currency} /></dd></div>
        <div><dt>Difference traced to items</dt><dd><Amount value={comparison.itemized_difference} currency={currency} /></dd></div>
      </dl>}
      {comparison.total_sources && <details><summary>Evidence for stated totals and tax</summary><h4>Estimate</h4><Sources sources={comparison.total_sources.estimate} caseId={caseId} /><h4>Final bill</h4><Sources sources={comparison.total_sources.final} caseId={caseId} /></details>}
    </Section>
    {!!comparison.limitations?.length && <ul className={styles.limitations}>{comparison.limitations.map((note) => <li key={note}>{note}</li>)}</ul>}
  </div>;
}
