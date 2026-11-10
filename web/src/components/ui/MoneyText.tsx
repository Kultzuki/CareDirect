import { formatMoney, isMoneyString } from "@/lib/money";

import styles from "./MoneyText.module.css";

/**
 * Renders a decimal money string with Intl formatting. If the value is not a valid money
 * string the raw text is shown (never a guessed number) so a bad value is visible, not hidden.
 */
export function MoneyText({
  value,
  currency,
  size = "md",
}: {
  value: string;
  currency: string;
  size?: "md" | "lg";
}) {
  let text = value;
  if (isMoneyString(value)) {
    try {
      text = formatMoney(value, currency);
    } catch {
      text = `${value} ${currency}`;
    }
  }
  return (
    <span className={styles.money} data-size={size}>
      {text}
    </span>
  );
}
