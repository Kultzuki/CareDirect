import type { EpisodeFieldSource } from "@/lib/types";

export function EpisodeEvidence({ sources, caseId, documentId }: { sources: EpisodeFieldSource[]; caseId: string; documentId?: string }) {
  const seen = new Set<string>();
  const locations = sources.filter((field) => {
    if (!field.source) return false;
    const key = `${field.source.page}:${field.source.snippet ?? field.path}`;
    if (seen.has(key)) return false;
    seen.add(key); return true;
  });
  return <ul>{locations.map((field) => <li key={field.path}>
    {documentId && field.source?.page ? <a href={`/cases/${caseId}/documents/${documentId}/source#page=${field.source.page}`} target="_blank" rel="noreferrer">Source page {field.source.page}</a> : <span>Source location {field.source?.page ?? "not supplied"}</span>}
    {" · "}{field.state}{field.needs_review ? " · needs review" : ""}
    {field.source?.snippet && <blockquote>{field.source.snippet}</blockquote>}
  </li>)}</ul>;
}
