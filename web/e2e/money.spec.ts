import { expect, test } from "@playwright/test";

import {
  formatConfidence,
  formatMoney,
  isMoneyInput,
  isMoneyString,
  isQuantityInput,
} from "../src/lib/money";

// Pure unit checks on the money helpers. No browser or server is used.

test("formatMoney formats decimal strings exactly", () => {
  expect(formatMoney("25000.00", "INR")).toBe("₹25,000.00");
  expect(formatMoney("125000.50", "INR")).toBe("₹1,25,000.50");
  expect(formatMoney("0.00", "INR")).toBe("₹0.00");
  expect(formatMoney("19000.00", "USD")).toBe("$19,000.00");
});

test("formatMoney keeps digits a float would lose", () => {
  // 12 whole digits plus 2 decimals is past what a double represents exactly.
  expect(formatMoney("999999999999.99", "USD")).toBe("$999,999,999,999.99");
  expect(formatMoney("-1200.05", "INR")).toBe("-₹1,200.05");
});

test("formatMoney rejects anything that is not a two-decimal money string", () => {
  for (const bad of ["1e3", "12.345", "", "1,000.00", "12", "12.5", " 12.00", "NaN"]) {
    expect(() => formatMoney(bad, "INR"), `input ${JSON.stringify(bad)}`).toThrow();
  }
  expect(() => formatMoney("12.00", "inr")).toThrow();
});

test("isMoneyString, isMoneyInput and isQuantityInput", () => {
  expect(isMoneyString("25000.00")).toBe(true);
  expect(isMoneyString("25000")).toBe(false);
  expect(isMoneyString(25000)).toBe(false);
  expect(isMoneyInput("1200")).toBe(true);
  expect(isMoneyInput("1200.5")).toBe(true);
  expect(isMoneyInput("1200.555")).toBe(false);
  expect(isMoneyInput("1,200")).toBe(false);
  expect(isMoneyInput("-5")).toBe(false);
  expect(isQuantityInput("2")).toBe(true);
  expect(isQuantityInput("0.125")).toBe(true);
  expect(isQuantityInput("0.1255")).toBe(false);
});

test("formatConfidence moves the decimal point in the text", () => {
  expect(formatConfidence("0.550")).toBe("55.0%");
  expect(formatConfidence("0.925")).toBe("92.5%");
  expect(formatConfidence("0.9")).toBe("90.0%");
  expect(formatConfidence("0.055")).toBe("5.5%");
  expect(formatConfidence("0")).toBe("0.0%");
  expect(formatConfidence("1")).toBe("100.0%");
  expect(formatConfidence("1.000")).toBe("100.0%");
});

test("formatConfidence rejects values outside 0 to 1", () => {
  for (const bad of ["", "1.5", "2", "-0.1", "0.5555", "abc", ".5"]) {
    expect(() => formatConfidence(bad), `input ${JSON.stringify(bad)}`).toThrow();
  }
});
