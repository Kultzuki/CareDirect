import Link from "next/link";

import type { DocumentOut } from "@/lib/types";

import styles from "./SourcePreview.module.css";

export function SourcePreview({ document }: { document: DocumentOut }) {
  const path = `/cases/${document.case_id}/documents/${document.id}/source`;
  return <section className={styles.source} aria-labelledby="source-heading">
    <div className={styles.head}><h2 id="source-heading">Original source</h2><Link href={path} target="_blank" rel="noreferrer noopener" prefetch={false}>Open source <span className="cd-visually-hidden">in a new tab</span></Link></div>
    <p id="source-help">Compare the document with the extracted values. Field rows include page references and text excerpts as an accessible alternative.</p>
    {document.mime_type === "application/pdf" ? <iframe src={path} title="Original sample document" aria-describedby="source-help" className={styles.preview} /> : <Link href={path} target="_blank" rel="noreferrer noopener" prefetch={false} className={styles.imageLink} aria-label="Open original source image in a new tab"><img src={path} alt="Original uploaded sample bill or receipt. Read the field text excerpts for the accessible source values." className={styles.image} /></Link>}
    <p className={styles.meta}>Private source · {document.page_count ?? "Unknown"} page(s) · SHA-256 {document.sha256.slice(0, 12)}</p>
  </section>;
}
