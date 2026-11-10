import AxeBuilder from "@axe-core/playwright";
import { expect, test, type APIRequestContext } from "@playwright/test";

import { API_URL, getDemoPayer } from "./helpers";

async function setup(request: APIRequestContext) {
  const payerId = await getDemoPayer(request);
  const headers = { "X-Demo-User-Id": payerId };
  const created = await request.post(`${API_URL}/api/cases`, { headers, data: { patient_alias: "Synthetic provider-workflow family", currency: "USD" } });
  expect(created.status()).toBe(201);
  const careCase = await created.json() as { id: string; case_reference: string };
  const added = await request.post(`${API_URL}/api/cases/${careCase.id}/bills`, { headers, data: {
    provider_name: "Synthetic Harbor Clinic", currency: "USD", bill_date: "2026-11-09", printed_total: "250.00", printed_advance_paid: "40.00", printed_balance_due: "210.00",
    lines: [
      { line_number: 1, description_raw: "Consultation and diagnostic services", line_total: "210.00" },
      { line_number: 2, description_raw: "Laboratory panel", code: "LAB-01", service_date: "2026-11-09", quantity: "1", unit_price: "20.00", line_total: "20.00", source_page: 1, source_text: "2 Laboratory panel LAB-01 20.00" },
      { line_number: 3, description_raw: "Laboratory panel", code: "LAB-01", service_date: "2026-11-09", quantity: "1", unit_price: "20.00", line_total: "20.00", source_page: 1, source_text: "3 Laboratory panel LAB-01 20.00" },
    ],
  } });
  expect(added.status()).toBe(201);
  const bill = await added.json() as { id: string; line_items: { id: string; line_number: number }[] };
  for (const line of bill.line_items) expect((await request.post(`${API_URL}/api/line-items/${line.id}/accept`, { headers, data: {} })).ok()).toBe(true);
  const external = await request.post(`${API_URL}/api/cases/${careCase.id}/external-payments`, { headers, data: { bill_id: bill.id, method: "OTHER", amount: "40.00", currency: "USD", payee_name: "Synthetic Harbor Clinic", paid_on: "2026-11-09", reference: `SYNTHETIC-${careCase.id}` } });
  expect(external.ok()).toBe(true);
  const payment = await external.json() as { id: string };
  expect((await request.post(`${API_URL}/api/external-payments/${payment.id}/reconcile`, { headers })).ok()).toBe(true);
  const checks = await request.post(`${API_URL}/api/cases/${careCase.id}/run-checks`, { headers });
  expect(checks.ok()).toBe(true);
  const result = await checks.json() as { flags_created: { id: string; flag_type: string }[] };
  const flag = result.flags_created.find((item) => item.flag_type === "POSSIBLE_EXACT_DUPLICATE");
  expect(flag).toBeTruthy();
  return { careCase, headers, flagId: flag!.id, lineId: bill.line_items.find((line) => line.line_number === 3)!.id };
}

test("provider proposal and payer resolution are separate, keyboard-accessible decisions", async ({ page, request, context }) => {
  test.setTimeout(180_000);
  const { careCase, headers, flagId, lineId } = await setup(request);
  await page.goto(`/cases/${careCase.id}`);
  await expect(page.getByRole("heading", { level: 1, name: careCase.case_reference })).toBeVisible();
  const card = page.getByTestId(`question-${flagId}`);
  await card.getByLabel("Charge to question").selectOption(lineId);
  const question = card.getByLabel("Your question to the provider");
  await question.fill("The laboratory panel appears twice on the same date. Please clarify the second entry.");
  await card.getByRole("button", { name: "Preview provider question" }).click();
  await expect(card.getByRole("heading", { name: "What the provider will see" })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(question).toBeFocused();
  await expect(question).toHaveValue(/laboratory panel appears twice/);
  await card.getByRole("button", { name: "Preview provider question" }).click();
  await card.getByRole("button", { name: "Hold charge and create provider link" }).click();
  await expect(card.getByRole("status").filter({ hasText: "Provider link created" })).toBeVisible();
  const path = await card.getByLabel("Private provider link").inputValue();
  expect(path).toMatch(/^\/provider\/respond\/[A-Za-z0-9_-]{43}$/);
  const provider = await context.newPage();
  await provider.goto(path);
  await expect(provider.getByRole("heading", { level: 1, name: "Clarify a bill charge" })).toBeVisible();
  await expect(provider.getByRole("navigation", { name: "Main", exact: true })).toHaveCount(0);
  await expect(provider.getByText(careCase.case_reference, { exact: true })).toHaveCount(0);
  await provider.getByRole("radio", { name: "Propose a corrected amount" }).check();
  await provider.getByLabel("Proposed charge (USD)").fill("0.00");
  await provider.getByLabel("Reason and supporting explanation").fill("This synthetic second laboratory entry was repeated. We propose a credit of the full charge.");
  await provider.getByLabel("Your name or billing-team reference").fill("Synthetic Harbor billing desk");
  await provider.getByRole("button", { name: "Review response", exact: true }).click();
  await expect(provider.getByRole("heading", { name: "Review your response" })).toBeFocused();
  await provider.keyboard.press("Escape");
  await expect(provider.getByRole("radio", { name: "Credit the charge" })).toBeFocused();
  await expect(provider.getByLabel("Proposed charge (USD)")).toHaveValue("0.00");
  await provider.getByRole("button", { name: "Review response", exact: true }).click();
  await provider.getByRole("button", { name: "Record response for payer review" }).click();
  await expect(provider.getByRole("status").filter({ hasText: "Response recorded" })).toBeVisible();
  await provider.reload();
  await expect(provider.getByText("This link cannot submit another response.", { exact: false })).toBeVisible();

  // A provider proposal alone has no effect on the net bill or previous payments.
  const before = await request.get(`${API_URL}/api/cases/${careCase.id}/buckets`, { headers });
  expect(await before.json()).toMatchObject({ original_bill_total: "250.00", net_bill_total: "250.00", payable_now: "190.00", queried: "20.00", already_paid: "40.00" });
  await page.reload();
  await card.getByRole("button", { name: "Review financial effect" }).click();
  await expect(card.getByRole("table", { name: "Proposed resolution in USD" })).toContainText("$230.00");
  const axe = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]).exclude("nextjs-portal").analyze();
  expect(axe.violations).toEqual([]);
  await card.getByLabel("Reason for your decision").fill("I reviewed both source entries and accept the proposed full credit for the repeated entry.");
  await card.getByRole("checkbox").check();
  await card.getByRole("button", { name: "Accept resolution: $0.00", exact: true }).click();
  await expect(card.getByText("Resolution accepted", { exact: true })).toBeVisible();
  await expect(page.getByTestId("financial-summary")).toContainText("-$20.00");
  const after = await request.get(`${API_URL}/api/cases/${careCase.id}/buckets`, { headers });
  expect(await after.json()).toMatchObject({ original_bill_total: "250.00", adjustments: "-20.00", net_bill_total: "230.00", payable_now: "190.00", queried: "0.00", already_paid: "40.00", consistent: true });
  await page.reload();
  await expect(card.getByRole("button", { name: "Accept resolution: $0.00", exact: true })).toHaveCount(0);
  const workflow = await request.get(`${API_URL}/api/cases/${careCase.id}/provider-workflow`, { headers });
  const history = await workflow.json() as { decisions: unknown[] };
  expect(history.decisions).toHaveLength(1);
  await provider.close();
});
