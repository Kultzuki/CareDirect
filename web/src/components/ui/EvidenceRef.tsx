import styles from "./EvidenceRef.module.css";

/**
 * Where a value was read on the source document: the page, and the words printed there.
 * The snippet is set in the serif "paper" face because it is quoted from the document.
 */
export function EvidenceRef({
  page,
  snippet,
}: {
  page: number;
  snippet: string | null;
}) {
  return (
    <p className={styles.evidence}>
      <span className={styles.page}>Page {page}</span>
      {snippet ? <q className={styles.quote}>{snippet}</q> : null}
    </p>
  );
}
