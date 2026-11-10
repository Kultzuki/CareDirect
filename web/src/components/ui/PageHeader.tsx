import Link from "next/link";
import type { ReactNode } from "react";

import styles from "./PageHeader.module.css";

/** Title block for a screen: optional way back, the one h1, a line of facts, and actions. */
export function PageHeader({
  title,
  back,
  meta,
  actions,
  titleId,
}: {
  title: ReactNode;
  back?: { href: string; label: string };
  meta?: ReactNode;
  actions?: ReactNode;
  titleId?: string;
}) {
  return (
    <header className={styles.header}>
      {back ? (
        <Link href={back.href} className={styles.back}>
          <span aria-hidden="true">&lsaquo;</span> {back.label}
        </Link>
      ) : null}
      <div className={styles.row}>
        <div className={styles.titles}>
          <h1 id={titleId}>{title}</h1>
          {meta ? <div className={styles.meta}>{meta}</div> : null}
        </div>
        {actions ? <div className={styles.actions}>{actions}</div> : null}
      </div>
    </header>
  );
}
