import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

import { API_URL, getDemoPayer } from "./helpers";

const viewports = [
  { name: "desktop-1440", width: 1440, height: 900 },
  { name: "desktop-1280", width: 1280, height: 800 },
  { name: "tablet-768", width: 768, height: 1024 },
  { name: "mobile-390", width: 390, height: 844 },
  { name: "mobile-360", width: 360, height: 800 },
];

async function capture(page: Page, state: string, position?: () => Promise<void>) {
  const directory = path.resolve(__dirname, "../../output/playwright/prompt06");
  fs.mkdirSync(directory, { recursive: true });
  for (const viewport of viewports) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    if (position) await position();
    else await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: path.join(directory, `${state}-${viewport.name}.png`) });
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
      `${state} has no page-wide overflow at ${viewport.width}px`,
    ).toBe(true);
  }
}

test("provider resolution visual and keyboard acceptance at five viewports", async ({ page, request }) => {
  test.setTimeout(180_000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => { if (message.type() === "error") errors.push(message.text()); });
  const payer = await getDemoPayer(request);
  const headers = { "X-Demo-User-Id": payer };
  const created = await request.post(`${API_URL}/api/cases`, {
    headers, data: { patient_alias: "Synthetic Harbor family", currency: "USD" },
  });
  expect(created.ok()).toBeTruthy();
  const careCase = await created.json() as { id: string; case_reference: string };
  const billResponse = await request.post(`${API_URL}/api/cases/${careCase.id}/bills`, {
    headers,
    data: {
      provider_name: "Synthetic Harbor Clinic", currency: "USD", bill_date: "2026-11-09",
      printed_total: "250.00", printed_advance_paid: "40.00", printed_balance_due: "210.00",
      lines: [
        { line_number: 1, description_raw: "Outpatient consultation", line_total: "210.00", service_date: "2026-11-09" },
        { line_number: 2, description_raw: "Laboratory panel", line_total: "20.00", code: "LAB-01", service_date: "2026-11-09", source_page: 1, source_text: "2  Laboratory panel  LAB-01  1  20.00  20.00" },
        { line_number: 3, description_raw: "Laboratory panel", line_total: "20.00", code: "LAB-01", service_date: "2026-11-09", source_page: 1, source_text: "3  Laboratory panel  LAB-01  1  20.00  20.00" },
      ],
    },
  });
  expect(billResponse.ok()).toBeTruthy();
  const bill = await billResponse.json() as { id: string; line_items: { id: string; line_number: number }[] };
  for (const line of bill.line_items) {
    expect((await request.post(`${API_URL}/api/line-items/${line.id}/accept`, { headers, data: {} })).ok()).toBeTruthy();
  }
  const check = await request.post(`${API_URL}/api/cases/${careCase.id}/run-checks`, { headers, data: {} });
  const checked = await check.json() as { flags_created: { id: string; flag_type: string }[] };
  const flag = checked.flags_created.find((item) => item.flag_type === "POSSIBLE_EXACT_DUPLICATE")!;
  const selected = bill.line_items.find((item) => item.line_number === 3)!;
  expect((await request.post(`${API_URL}/api/line-items/${selected.id}/query`, {
    headers, data: { reason: "Please clarify the repeated laboratory panel.", flag_id: flag.id },
  })).ok()).toBeTruthy();
  const receipt = await request.post(`${API_URL}/api/cases/${careCase.id}/external-payments`, {
    headers, data: { method: "OTHER", amount: "40.00", currency: "USD", paid_on: "2026-11-09", reference: "SYNTHETIC-USD-VISUAL", payee_name: "Synthetic Harbor Clinic", bill_id: bill.id },
  });
  const external = await receipt.json() as { id: string };
  expect((await request.post(`${API_URL}/api/external-payments/${external.id}/reconcile`, { headers })).ok()).toBeTruthy();
  await page.goto(`/cases/${careCase.id}`);
  await expect(page.getByRole("heading", { level: 1, name: careCase.case_reference })).toBeVisible();
  await expect(page.getByTestId("financial-summary")).toContainText("$190.00");
  await capture(page, "workspace");
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);

  const linkResponse = await request.post(`${API_URL}/api/flags/${flag.id}/provider-links`, {
    headers, data: { line_item_id: selected.id, question: "These two laboratory entries have the same code, date and amount. Please explain or propose a correction." },
  });
  expect(linkResponse.ok()).toBeTruthy();
  const link = await linkResponse.json() as { token: string };
  await page.goto(`/provider/respond/${link.token}`);
  await expect(page.getByRole("heading", { level: 1, name: "Clarify a bill charge" })).toBeVisible();
  await capture(page, "provider");
  await capture(page, "provider-response", async () => {
    await page.getByRole("group", { name: "How would you resolve this question?" }).evaluate((element) => element.scrollIntoView({ block: "start" }));
  });
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);

  // The provider and payer remain separate actors and separate financial decisions.
  const responseResult = await request.post(`${API_URL}/api/provider/respond/${link.token}`, {
    data: { response_type: "CORRECT", response_text: "Our synthetic billing review confirms the second panel was entered twice. We propose crediting this line in full.", corrected_amount: "0.00", responder_label: "Synthetic Harbor billing desk" },
  });
  expect(responseResult.ok()).toBeTruthy();
  await page.goto(`/cases/${careCase.id}#questions`);
  const trigger = page.getByRole("button", { name: "Review financial effect" });
  await trigger.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "Review the exact financial effect" })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(trigger).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "Review the exact financial effect" })).toBeFocused();
  await page.setViewportSize({ width: 1440, height: 900 });
  await capture(page, "resolution", async () => {
    await page.getByRole("heading", { name: "Review the exact financial effect" }).evaluate((element) => element.scrollIntoView({ block: "start" }));
  });
  await capture(page, "resolution-controls", async () => {
    await page.getByRole("group", { name: "Your decision" }).evaluate((element) => element.scrollIntoView({ block: "start" }));
  });
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  expect(errors).toEqual([]);
});
