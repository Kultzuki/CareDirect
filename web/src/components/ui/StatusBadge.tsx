import type { ReactNode } from "react";

import { Icon, type IconName } from "./Icon";
import styles from "./StatusBadge.module.css";

/** The shared status vocabulary. Add a tone here, then style it in StatusBadge.module.css. */
export type StatusTone =
  | "neutral"
  // Provenance: where a value came from and what a person did to it
  | "extracted"
  | "needs-review"
  | "confirmed"
  | "corrected"
  | "provider-confirmed"
  | "paypal-confirmed"
  // The three buckets
  | "payable"
  | "queried"
  | "paid"
  // Feedback
  | "info"
  | "success"
  | "warning"
  | "error";

const DEFAULT_ICON: Partial<Record<StatusTone, IconName>> = {
  "needs-review": "alert",
  confirmed: "check",
  corrected: "pencil",
  "provider-confirmed": "check",
  "paypal-confirmed": "check",
  success: "check",
  warning: "alert",
  error: "cross",
  info: "info",
};

/**
 * A status is always words first. Colour and icon support the text, never replace it, so the
 * badge still works for colour-blind users and in forced-colours mode.
 */
export function StatusBadge({
  tone = "neutral",
  icon,
  children,
}: {
  tone?: StatusTone;
  /** Pass `null` to hide the default icon for this tone. */
  icon?: IconName | null;
  children: ReactNode;
}) {
  const iconName = icon === undefined ? DEFAULT_ICON[tone] : icon;
  return (
    <span className={styles.badge} data-tone={tone}>
      {iconName ? <Icon name={iconName} size={14} /> : null}
      <span>{children}</span>
    </span>
  );
}
