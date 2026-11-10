import fs from "node:fs";

import AxeBuilder from "@axe-core/playwright";
import { expect, test, type APIRequestContext, type Page, type TestInfo } from "@playwright/test";

import {
  API_URL,
  createCase,
  createUploadLink,
  fixture,
  getDemoPayer,
  reviewPath,
} from "./helpers";

// WCAG 2.2 AA automated check (axe-core). Automated rules find roughly a third of real
// accessibility problems, so a clean run is a floor, not a pass on manual review.
const WCAG_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

async function expectNoViolations(page: Page, testInfo: TestInfo, name: string) {
  const results = await new AxeBuilder({ page })
    .withTags(WCAG_TAGS)
    // The Next.js dev overlay is not part of the product.
    .exclude("nextjs-portal")
    .analyze();
  await testInfo.attach(`axe-${name}`, {
    body: JSON.stringify(
      {
        url: results.url,
        violations: results.violations,
        passes: results.passes.map((rule) => rule.id),
        // Rules axe could not decide on its own (for example text over a gradient).
        incomplete: results.incomplete.map((rule) => ({
          id: rule.id,
          nodes: rule.nodes.map((node) => node.target),
        })),
      },
      null,
      2,
    ),
    contentType: "application/json",
  });
  expect(results.violations, `axe violations on ${name}`).toEqual([]);
  // Guard against a vacuous pass: the rules really ran on a real page.
  expect(results.passes.length, `axe rules that passed on ${name}`).toBeGreaterThan(10);
}

async function uploadViaApi(
  request: APIRequestContext,
  token: string,
  type: string,
  file: string,
  mime: string,
): Promise<string> {
  const res = await request.post(`${API_URL}/api/uploads/${token}?document_type=${type}`, {
    headers: { "Content-Type": mime },
    data: fs.readFileSync(fixture(file)),
  });
  expect(res.status()).toBe(201);
  return ((await res.json()) as { document_id: string }).document_id;
}

test.describe("accessibility (axe, WCAG 2.2 AA)", () => {
  test.setTimeout(120_000);

  test("upload page with a valid link", async ({ page, request }, testInfo) => {
    const payerId = await getDemoPayer(request);
    const { id: caseId } = await createCase(request, payerId);
    const link = await createUploadLink(request, payerId, caseId, ["BILL", "RECEIPT"]);

    await page.goto(link.path);
    await expect(page.getByRole("heading", { level: 1, name: "Upload documents" })).toBeVisible();
    await expectNoViolations(page, testInfo, "upload-page");
  });

  test("case review page with one document", async ({ page, request }, testInfo) => {
    const payerId = await getDemoPayer(request);
    const { id: caseId } = await createCase(request, payerId);
    const link = await createUploadLink(request, payerId, caseId, ["BILL"]);
    await uploadViaApi(request, link.token, "BILL", "photographed_bill.png", "image/png");

    await page.goto(reviewPath(caseId));
    await expect(page.getByTestId("document-list")).toBeVisible();
    await expectNoViolations(page, testInfo, "case-review-page");
  });

  test("extraction page in the needs-review state", async ({ page, request }, testInfo) => {
    const payerId = await getDemoPayer(request);
    const { id: caseId } = await createCase(request, payerId);
    const link = await createUploadLink(request, payerId, caseId, ["BILL"]);
    const documentId = await uploadViaApi(
      request,
      link.token,
      "BILL",
      "photographed_bill.png",
      "image/png",
    );
    const extract = await request.post(`${API_URL}/api/documents/${documentId}/extract`, {
      headers: { "X-Demo-User-Id": payerId },
    });
    expect(extract.status()).toBe(201);

    await page.goto(`${reviewPath(caseId)}/${documentId}`);
    await expect(page.getByTestId("review-summary")).toContainText("2 fields");
    await expect(page.getByTestId("field-line_items.0.line_total")).toContainText("Needs review");
    await expectNoViolations(page, testInfo, "extraction-needs-review");
  });

  test("upload page after an error alert is shown", async ({ page, request }, testInfo) => {
    const payerId = await getDemoPayer(request);
    const { id: caseId } = await createCase(request, payerId);
    const link = await createUploadLink(request, payerId, caseId, ["BILL"]);

    await page.goto(link.path);
    await page.getByLabel("File").setInputFiles(fixture("mismatch.pdf"));
    await page.getByRole("button", { name: "Upload" }).click();
    await expect(
      page.getByRole("alert").filter({ hasText: "does not match the declared type" }),
    ).toBeVisible();
    await expectNoViolations(page, testInfo, "upload-page-error");
  });
});
