import AxeBuilder from "@axe-core/playwright";
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

import { API_URL, getDemoPayer } from "./helpers";

async function syntheticCase(request: APIRequestContext) {
  const payer = await getDemoPayer(request);
  const headers = { "X-Demo-User-Id": payer };
  const created = await request.post(`${API_URL}/api/demo/cases`, { headers, data: { patient_alias: "Synthetic payment acceptance family", currency: "USD" } });
  expect(created.status()).toBe(201);
  const careCase = await created.json() as { id: string; case_reference: string };
  const added = await request.post(`${API_URL}/api/cases/${careCase.id}/bills`, { headers, data: {
    provider_name: "Synthetic Harbor Clinic", currency: "USD", bill_date: "2026-11-09", printed_total: "250.00", printed_advance_paid: "40.00",
    lines: [
      { line_number: 1, description_raw: "Outpatient consultation", line_total: "210.00", service_date: "2026-11-09" },
      { line_number: 2, description_raw: "Laboratory panel", code: "LAB-01", line_total: "20.00", service_date: "2026-11-09" },
      { line_number: 3, description_raw: "Laboratory panel", code: "LAB-01", line_total: "20.00", service_date: "2026-11-09" },
    ],
  } });
  expect(added.ok()).toBe(true);
  const bill = await added.json() as { id: string; line_items: { id: string; line_number: number }[] };
  for (const line of bill.line_items) expect((await request.post(`${API_URL}/api/line-items/${line.id}/accept`, { headers, data: {} })).ok()).toBe(true);
  const receipt = await request.post(`${API_URL}/api/cases/${careCase.id}/external-payments`, { headers, data: { bill_id: bill.id, method: "OTHER", amount: "40.00", currency: "USD", payee_name: "Synthetic Harbor Clinic", paid_on: "2026-11-09", reference: `SYNTHETIC-${careCase.id}` } });
  const payment = await receipt.json() as { id: string };
  expect((await request.post(`${API_URL}/api/external-payments/${payment.id}/reconcile`, { headers })).ok()).toBe(true);
  const checked = await request.post(`${API_URL}/api/cases/${careCase.id}/run-checks`, { headers });
  const flags = await checked.json() as { flags_created: { id: string; flag_type: string }[] };
  const flag = flags.flags_created.find((item) => item.flag_type === "POSSIBLE_EXACT_DUPLICATE")!;
  expect(flag).toBeTruthy();
  expect((await request.post(`${API_URL}/api/line-items/${bill.line_items.find((item) => item.line_number === 3)!.id}/query`, { headers, data: { flag_id: flag.id, reason: "Please clarify the repeated laboratory entry." } })).ok()).toBe(true);
  const linkResponse = await request.post(`${API_URL}/api/flags/${flag.id}/provider-links`, { headers, data: { line_item_id: bill.line_items.find((item) => item.line_number === 3)!.id, question: "Please clarify the repeated laboratory entry." } });
  expect(linkResponse.ok()).toBe(true);
  const link = await linkResponse.json() as { token: string };
  const response = await request.post(`${API_URL}/api/provider/respond/${link.token}`, { data: { response_type: "ACCEPT", response_text: "Synthetic billing review proposes full credit for the repeated entry.", responder_label: "Synthetic billing desk" } });
  const proposal = await response.json() as { id: string };
  const previewResponse = await request.get(`${API_URL}/api/provider-responses/${proposal.id}/preview`, { headers });
  const preview = await previewResponse.json() as { state_fingerprint: string };
  expect((await request.post(`${API_URL}/api/provider-responses/${proposal.id}/decision`, { headers, data: { decision: "ACCEPT", note: "Payer reviewed source and accepts the full credit.", state_fingerprint: preview.state_fingerprint } })).ok()).toBe(true);
  return { careCase, headers };
}

async function capture(page: Page, state: string) {
  const directory = path.resolve(__dirname, "../../output/playwright/prompt07-mocked");
  fs.mkdirSync(directory, { recursive: true });
  for (const [name, width, height] of [["desktop1440", 1440, 900], ["desktop1280", 1280, 800], ["tablet768", 768, 1024], ["mobile390", 390, 844], ["mobile360", 360, 800]] as const) {
    await page.setViewportSize({ width, height });
    await page.screenshot({ path: path.join(directory, `${state}-${name}.png`), fullPage: true });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), `${state} fits ${width}`).toBe(true);
  }
}

test("exact approval and payment reconciliation use deterministic HTTP only", async ({ page, request }) => {
  test.skip(process.env.CAREDIRECT_E2E_MOCK !== "1", "Explicit isolated mock harness required; never creates a live invoice");
  test.setTimeout(180_000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => { if (message.type() === "error") errors.push(message.text()); });
  const { careCase, headers } = await syntheticCase(request);
  await page.goto(`/cases/${careCase.id}/payments`);
  await expect(page.getByRole("heading", { level: 1, name: `${careCase.case_reference}: Payments` })).toBeVisible();
  await expect(page.getByRole("button", { name: "Review approval for $190.00" })).toBeDisabled();
  await page.getByRole("button", { name: "Check Sandbox account evidence" }).click();
  const review = page.getByRole("button", { name: "Review approval for $190.00" });
  await expect(review).toBeEnabled();
  await capture(page, "ready-for-approval");
  await review.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "Approve $190.00 to collect now" })).toBeFocused();
  await page.getByLabel("Payment purpose", { exact: true }).fill("Synthetic outpatient bill, exact approved collection.");
  await page.keyboard.press("Escape");
  await expect(review).toBeFocused();
  await review.click();
  await expect(page.getByLabel("Payment purpose", { exact: true })).toHaveValue(/Synthetic outpatient/);
  await page.getByRole("checkbox").check();
  expect((await new AxeBuilder({ page }).exclude("nextjs-portal").analyze()).violations).toEqual([]);
  await page.getByRole("button", { name: "Approve $190.00 collection", exact: true }).click();
  await expect(page.getByText("Current approval recorded", { exact: true })).toBeVisible();
  await capture(page, "approved");
  await page.reload();
  const before = await (await request.get(`${API_URL}/__test__/counts`)).json() as { create: number };
  await page.getByRole("button", { name: "Create approved Sandbox invoice", exact: true }).click();
  await expect(page.getByText("Awaiting Sandbox buyer", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Open existing Sandbox invoice" })).toBeVisible();
  await capture(page, "awaiting-buyer");
  const workspace = await (await request.get(`${API_URL}/api/cases/${careCase.id}/payments`, { headers })).json() as { invoice: { paypal_invoice_id: string } };
  // Test control simulates authoritative responses; no buyer URL is opened.
  expect((await request.post(`${API_URL}/__test__/invoices/${workspace.invoice.paypal_invoice_id}/complete`)).ok()).toBe(true);
  await page.getByRole("button", { name: "Verify current PayPal state", exact: true }).click();
  await expect(page.getByText("Payment verified by PayPal", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Verify current PayPal state", exact: true })).toBeEnabled();
  await page.reload();
  await page.getByRole("button", { name: "Verify current PayPal state", exact: true }).click();
  await expect(page.getByText("Payment verified by PayPal", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Verify current PayPal state", exact: true })).toBeEnabled();
  await capture(page, "verified-paid");
  const buckets = await (await request.get(`${API_URL}/api/cases/${careCase.id}/buckets`, { headers })).json();
  expect(buckets).toMatchObject({ original_bill_total: "250.00", adjustments: "-20.00", net_bill_total: "230.00", payable_now: "0.00", queried: "0.00", already_paid: "230.00", consistent: true });
  const after = await (await request.get(`${API_URL}/__test__/counts`)).json() as { create: number };
  expect(after.create - before.create).toBe(1);
  expect((await new AxeBuilder({ page }).exclude("nextjs-portal").analyze()).violations).toEqual([]);
  expect(errors).toEqual([]);
});
