import { formatConfidence } from "@/lib/money";

import styles from "./ConfidenceIndicator.module.css";

/**
 * Shows the model's confidence as text ("Model confidence 55.0%") with a small bar for a quick
 * read. The percentage is derived from the decimal string; no floats. The bar is decoration.
 * `emphasis` is set by the caller from the API's own `needs_review`; this component never
 * decides what counts as low.
 */
export function ConfidenceIndicator({
  value,
  emphasis = false,
  note,
}: {
  value: string | null;
  emphasis?: boolean;
  /** Extra words after the percentage, such as "before correction". */
  note?: string;
}) {
  if (value === null) return null;
  let percent: string;
  try {
    percent = formatConfidence(value);
  } catch {
    return <span className={styles.confidence}>Model confidence unavailable</span>;
  }
  return (
    <span className={styles.confidence} data-emphasis={emphasis || undefined}>
      <span className={styles.track} aria-hidden="true">
        <span className={styles.fill} style={{ width: percent }} />
      </span>
      <span className={styles.text}>
        Model confidence <span className={styles.figure}>{percent}</span>
        {note ? ` ${note}` : ""}
      </span>
    </span>
  );
}
