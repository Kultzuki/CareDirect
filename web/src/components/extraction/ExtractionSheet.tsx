import type { ReactNode } from "react";

import { EvidenceRef } from "@/components/ui";
import type { FieldOut } from "@/lib/types";

import { FieldRow } from "./FieldRow";
import styles from "./ExtractionSheet.module.css";

export interface ExtractionSheetProps {
  fields: FieldOut[];
  currency: string;
  /** Extra controls per field. Only the client review form passes this. */
  renderControls?: (field: FieldOut) => ReactNode;
}

function sourceKey(field: FieldOut): string | null {
  return field.source ? `${field.source.page}|${field.source.snippet ?? ""}` : null;
}

/** The page and text shared by at least two fields of one line, or null. */
function commonSource(lineFields: FieldOut[]): FieldOut["source"] {
  const counts = new Map<string, { n: number; field: FieldOut }>();
  for (const field of lineFields) {
    const key = sourceKey(field);
    if (key === null) continue;
    const entry = counts.get(key);
    counts.set(key, { n: (entry?.n ?? 0) + 1, field: entry?.field ?? field });
  }
  let best: { n: number; field: FieldOut } | null = null;
  for (const entry of counts.values()) {
    if (!best || entry.n > best.n) best = entry;
  }
  return best && best.n >= 2 ? best.field.source : null;
}

function groupLines(fields: FieldOut[]): FieldOut[][] {
  const byLine = new Map<number, FieldOut[]>();
  for (const field of fields) {
    if (field.line_index === null) continue;
    byLine.set(field.line_index, [...(byLine.get(field.line_index) ?? []), field]);
  }
  return [...byLine.entries()].sort((a, b) => a[0] - b[0]).map(([, group]) => group);
}

/**
 * Every extracted field of one document, grouped as the document is laid out. Safe in server
 * and client components: it holds no state and no hooks.
 */
export function ExtractionSheet({ fields, currency, renderControls }: ExtractionSheetProps) {
  const documentFields = fields.filter((f) => f.group === "document");
  const lines = groupLines(fields.filter((f) => f.group === "line_item"));
  const totals = fields.filter((f) => f.group === "totals");
  const receipt = fields.filter((f) => f.group === "receipt");
  const insurance = fields.filter((f) => f.group === "insurance");

  const row = (field: FieldOut, hideEvidence = false) => (
    <FieldRow
      key={field.path}
      field={field}
      currency={currency}
      hideEvidence={hideEvidence}
      controls={renderControls?.(field)}
    />
  );

  return (
    <div className={styles.sheet}>
      {documentFields.length > 0 ? (
        <section className={styles.group} aria-labelledby="group-document">
          <h2 id="group-document">Document details</h2>
          <dl className={styles.grid}>{documentFields.map((f) => row(f))}</dl>
        </section>
      ) : null}

      {lines.length > 0 ? (
        <section className={styles.group} aria-labelledby="group-lines">
          <h2 id="group-lines">Line items</h2>
          <ol className={styles.lines}>
            {lines.map((lineFields) => {
              const first = lineFields[0];
              const shared = commonSource(lineFields);
              const sharedKey = shared ? `${shared.page}|${shared.snippet ?? ""}` : null;
              return (
                <li
                  key={first.line_index}
                  className={styles.line}
                  data-testid={`line-${first.line_number}`}
                >
                  <div className={styles.lineHead}>
                    <h3>Line {first.line_number}</h3>
                    {shared ? <EvidenceRef page={shared.page} snippet={shared.snippet} /> : null}
                  </div>
                  <dl className={styles.lineFields}>
                    {lineFields.map((f) => row(f, sharedKey !== null && sourceKey(f) === sharedKey))}
                  </dl>
                </li>
              );
            })}
          </ol>
        </section>
      ) : null}

      {totals.length > 0 ? (
        <section className={styles.group} aria-labelledby="group-totals">
          <h2 id="group-totals">Totals as printed</h2>
          <dl className={styles.grid}>{totals.map((f) => row(f))}</dl>
        </section>
      ) : null}

      {insurance.length > 0 && <section className={styles.group} aria-labelledby="group-insurance"><h2 id="group-insurance">Insurance facts as stated</h2><p>Confirm these values against the document. Approval is not proof of payment; unstated amounts remain unknown.</p><dl className={styles.grid}>{insurance.map((f) => row(f))}</dl></section>}
      {receipt.length > 0 ? (
        <section className={styles.group} aria-labelledby="group-receipt">
          <h2 id="group-receipt">Payment receipt</h2>
          <dl className={styles.grid}>{receipt.map((f) => row(f))}</dl>
        </section>
      ) : null}
    </div>
  );
}
