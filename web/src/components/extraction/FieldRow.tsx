import type { ReactNode } from "react";

import { ConfidenceIndicator, EvidenceRef, MoneyText, StatusBadge } from "@/components/ui";
import { PAYMENT_METHOD_LABEL, formatDate } from "@/lib/format";
import type { FieldOut, FieldState, PaymentMethod } from "@/lib/types";

import styles from "./FieldRow.module.css";

const STATE_LABEL: Record<FieldState, string> = {
  extracted: "Read from document",
  confirmed: "Confirmed",
  corrected: "Corrected",
};

export function fieldDomId(path: string): string {
  return `fld-${path.replaceAll(".", "-")}`;
}

/** The text shown for a value, by kind. Money keeps its decimal string all the way. */
function ValueText({ kind, value, currency }: { kind: FieldOut["kind"]; value: string; currency: string }) {
  switch (kind) {
    case "money":
      return <MoneyText value={value} currency={currency} />;
    case "date":
      return <>{formatDate(value)}</>;
    case "payment_method":
      return <>{PAYMENT_METHOD_LABEL[value as PaymentMethod] ?? value}</>;
    default:
      return <>{value}</>;
  }
}

/**
 * One extracted field: label, current value, what has been done to it, how sure the model was,
 * and where on the page it was read. Presentational only. `needs_review` comes from the API and
 * is never recomputed here. Optional `controls` hold the correction inputs.
 */
export function FieldRow({
  field,
  currency,
  hideEvidence = false,
  controls,
}: {
  field: FieldOut;
  currency: string;
  /** Set when the same page and text is already shown once for the whole line. */
  hideEvidence?: boolean;
  controls?: ReactNode;
}) {
  const id = fieldDomId(field.path);
  const missing = field.value === null;
  const corrected = field.state === "corrected" && field.original_value !== field.value;
  // For line fields the visible label drops the "Line 1 " prefix; the full label stays in the
  // accessible name through visually hidden text.
  const linePrefix = field.line_number !== null ? `Line ${field.line_number} ` : "";
  const stripped =
    linePrefix && field.label.startsWith(linePrefix) ? field.label.slice(linePrefix.length) : field.label;
  const shortLabel = stripped.charAt(0).toUpperCase() + stripped.slice(1);

  return (
    <div
      className={styles.field}
      data-testid={`field-${field.path}`}
      data-needs-review={field.needs_review || undefined}
      data-state={field.state}
    >
      <dt className={styles.label} id={`${id}-label`}>
        {linePrefix && stripped !== field.label ? (
          <span className="cd-visually-hidden">{linePrefix}</span>
        ) : null}
        {shortLabel}
      </dt>
      <dd className={styles.body}>
        <div className={styles.valueLine}>
          <span className={styles.value} data-missing={missing || undefined}>
            {missing ? (
              "Not found in document"
            ) : (
              <ValueText kind={field.kind} value={field.value as string} currency={currency} />
            )}
          </span>
          <span className={styles.badges}>
            {field.needs_review ? <StatusBadge tone="needs-review">Needs review</StatusBadge> : null}
            {missing && field.state === "extracted" ? null : (
              <StatusBadge tone={field.state}>{STATE_LABEL[field.state]}</StatusBadge>
            )}
          </span>
        </div>
        {corrected ? (
          <p className={styles.original}>
            Model read{" "}
            <s className={styles.struck}>
              {field.original_value === null ? (
                "nothing"
              ) : (
                <ValueText kind={field.kind} value={field.original_value} currency={currency} />
              )}
            </s>
          </p>
        ) : null}
        <div className={styles.provenance}>
          <ConfidenceIndicator
            value={field.model_confidence}
            emphasis={field.needs_review}
            note={field.state === "corrected" ? "before correction" : undefined}
          />
          {field.source && !hideEvidence ? (
            <EvidenceRef page={field.source.page} snippet={field.source.snippet} />
          ) : null}
        </div>
        {controls}
      </dd>
    </div>
  );
}
