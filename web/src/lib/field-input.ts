// Checks for values a person types into the correction form. Shared by the form (to show a
// message early) and by the Server Action (which never trusts the form). The API validates
// again: these checks only give faster, kinder messages. No numbers are parsed from money.

import { PAYMENT_METHODS } from "./format";
import { isMoneyInput, isQuantityInput } from "./money";
import type { FieldKind } from "./types";

export const MAX_TEXT_LENGTH = 500;

/** A message when `value` is not acceptable for `kind`, otherwise null. Empty means "clear it". */
export function fieldInputError(kind: FieldKind, value: string): string | null {
  if (value === "") return null;
  switch (kind) {
    case "money":
      return isMoneyInput(value) ? null : "Enter an amount such as 1200 or 1200.50.";
    case "quantity":
      return isQuantityInput(value) ? null : "Enter a quantity such as 2 or 0.5.";
    case "date":
      return /^\d{4}-\d{2}-\d{2}$/.test(value) ? null : "Enter a date as year-month-day.";
    case "currency":
      return /^[A-Za-z]{3}$/.test(value) ? null : "Enter a three-letter currency code, such as INR.";
    case "payment_method":
      return (PAYMENT_METHODS as string[]).includes(value) ? null : "Choose a payment method.";
    case "text":
      return value.length <= MAX_TEXT_LENGTH
        ? null
        : `Use ${MAX_TEXT_LENGTH} characters or fewer.`;
  }
}

/** The string sent to the API: currency codes upper-case, everything else as typed. */
export function normaliseFieldInput(kind: FieldKind, value: string): string | null {
  const trimmed = value.trim();
  if (trimmed === "") return null;
  return kind === "currency" ? trimmed.toUpperCase() : trimmed;
}
