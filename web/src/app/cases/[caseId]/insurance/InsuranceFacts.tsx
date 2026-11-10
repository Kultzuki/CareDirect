import type { InsuranceFact } from "@/lib/insurance-types";
import styles from "../comparison/comparison.module.css";

export function InsuranceFacts({ facts, caseId }: { facts: InsuranceFact[]; caseId: string }) {
  return <ul className={styles.sources}>{facts.map((fact) => <li key={fact.id}>
    <strong>{fact.label}:</strong> {fact.value}
    {fact.document_id ? <>{" · "}<a href={`/cases/${encodeURIComponent(caseId)}/documents/${encodeURIComponent(fact.document_id)}/source${fact.source?.page ? `#page=${fact.source.page}` : ""}`} target="_blank" rel="noreferrer">{fact.source?.page ? `Source page ${fact.source.page}` : "Open source document"}</a>{fact.source?.snippet && <q>{fact.source.snippet}</q>}</> : <span> · Checked bill or payment record</span>}
  </li>)}</ul>;
}
