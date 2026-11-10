import type { ReactNode } from "react";

import { Icon, type IconName } from "./Icon";
import styles from "./Notice.module.css";

export type NoticeTone = "info" | "success" | "warning" | "error";

const ICON: Record<NoticeTone, IconName> = {
  info: "info",
  success: "check",
  warning: "alert",
  error: "cross",
};

/**
 * Inline feedback. Errors use role="alert" (announced at once); everything else uses
 * role="status" (announced politely). Say what happened and what to do next.
 */
export function Notice({
  tone = "info",
  title,
  children,
  testId,
}: {
  tone?: NoticeTone;
  title?: ReactNode;
  children?: ReactNode;
  testId?: string;
}) {
  return (
    <div
      className={styles.notice}
      data-tone={tone}
      role={tone === "error" ? "alert" : "status"}
      data-testid={testId}
    >
      <Icon name={ICON[tone]} size={20} />
      <div className={styles.body}>
        {title ? <p className={styles.title}>{title}</p> : null}
        {children ? <div className={styles.text}>{children}</div> : null}
      </div>
    </div>
  );
}
