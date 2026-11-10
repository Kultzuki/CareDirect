// Money, quantity and confidence stay decimal STRINGS from the API to the screen.
// Nothing here calls Number(), parseFloat() or does arithmetic on money.
// No "@/..." imports: Playwright's pure unit test imports this file directly.

const MONEY_PATTERN = /^-?\d{1,12}\.\d{2}$/;
const MONEY_INPUT_PATTERN = /^\d{1,12}(\.\d{1,2})?$/;
const QUANTITY_INPUT_PATTERN = /^\d{1,9}(\.\d{1,3})?$/;
const CONFIDENCE_PATTERN = /^([01])(?:\.(\d{1,3}))?$/;

/** True for an API money string such as "25000.00" (always two decimal places). */
export function isMoneyString(value: unknown): value is string {
  return typeof value === "string" && MONEY_PATTERN.test(value);
}

/** True for text a person may type as an amount, such as "1200" or "1200.5". */
export function isMoneyInput(value: string): boolean {
  return MONEY_INPUT_PATTERN.test(value);
}

/** True for text a person may type as a quantity, such as "2" or "0.5". */
export function isQuantityInput(value: string): boolean {
  return QUANTITY_INPUT_PATTERN.test(value);
}

function localeFor(currency: string): string {
  return currency === "INR" ? "en-IN" : "en-US";
}

/**
 * Format a decimal money string for display. Intl.NumberFormat formats string input exactly
 * (no float round trip). Throws on anything that is not a money string.
 */
export function formatMoney(value: string, currency: string): string {
  if (!isMoneyString(value)) {
    throw new RangeError("formatMoney expects a decimal string with two decimal places");
  }
  if (!/^[A-Z]{3}$/.test(currency)) {
    throw new RangeError("formatMoney expects a three-letter uppercase currency code");
  }
  return new Intl.NumberFormat(localeFor(currency), { style: "currency", currency }).format(
    value as `${number}`,
  );
}

/**
 * Turn a confidence string such as "0.550" into "55.0%" by moving the decimal point in the
 * text. Throws on anything outside 0 to 1 with up to three decimal places.
 */
export function formatConfidence(value: string): string {
  const match = CONFIDENCE_PATTERN.exec(value);
  if (!match) {
    throw new RangeError("formatConfidence expects a decimal string from 0 to 1");
  }
  const whole = match[1];
  const fraction = (match[2] ?? "").padEnd(3, "0");
  if (whole === "1") {
    if (fraction !== "000") {
      throw new RangeError("formatConfidence expects a decimal string from 0 to 1");
    }
    return "100.0%";
  }
  const percent = fraction.slice(0, 2).replace(/^0(?=\d)/, "");
  return `${percent}.${fraction.slice(2)}%`;
}
