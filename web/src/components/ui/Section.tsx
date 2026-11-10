import type { ReactNode } from "react";

import styles from "./Section.module.css";

/** A titled region of a page: one h2, optional intro text, then the content. */
export function Section({
  id,
  title,
  description,
  children,
}: {
  id: string;
  title: ReactNode;
  description?: ReactNode;
  children: ReactNode;
}) {
  const headingId = `${id}-heading`;
  return (
    <section id={id} className={styles.section} aria-labelledby={headingId}>
      <div className={styles.head}>
        <h2 id={headingId}>{title}</h2>
        {description ? <p className={styles.description}>{description}</p> : null}
      </div>
      {children}
    </section>
  );
}

/** Dashed, friendly placeholder for a list with nothing in it yet. Invite the next action. */
export function EmptyState({
  title,
  children,
}: {
  title: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div className={styles.empty}>
      <p className={styles.emptyTitle}>{title}</p>
      {children ? <div className={styles.emptyBody}>{children}</div> : null}
    </div>
  );
}
