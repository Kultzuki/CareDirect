import { expect, test } from "@playwright/test";

import {
  createCase,
  createUploadLink,
  fixture,
  getCase,
  getDemoPayer,
  reviewPath,
} from "./helpers";

// Synthetic documents only. Each test makes its own case.

test.describe("upload and review", () => {
  test("relative uploads a photographed bill and the payer reviews low-confidence fields", async ({
    page,
    request,
  }) => {
    test.setTimeout(120_000);
    // Hydration mismatches and runtime errors show up as console errors in the dev build.
    const browserErrors: string[] = [];
    page.on("console", (message) => {
      if (message.type() === "error") browserErrors.push(message.text());
    });
    page.on("pageerror", (error) => browserErrors.push(error.message));

    const payerId = await getDemoPayer(request);
    const { id: caseId } = await createCase(request, payerId);

    // The payer creates an upload link on the review page and opens it.
    await page.goto(reviewPath(caseId));
    await page.getByRole("button", { name: "Create upload link" }).click();
    await expect(page.getByTestId("upload-link-result")).toContainText("Upload link created");
    await page.getByRole("link", { name: "Open upload page" }).click();

    // The relative uploads a bill.
    await expect(page.getByRole("heading", { level: 1, name: /Upload/ })).toBeVisible();
    await page.getByLabel("Document type").selectOption({ label: "Bill" });
    await page.getByLabel("File").setInputFiles(fixture("photographed_bill.png"));
    await page.getByRole("button", { name: "Upload" }).click();
    const uploaded = page.getByRole("status").filter({ hasText: "Uploaded" });
    await expect(uploaded).toContainText("Uploaded");
    await expect(uploaded).toContainText("1 page");

    // The payer extracts it.
    await page.goto(reviewPath(caseId));
    const row = page.getByTestId("document-list").getByRole("listitem").first();
    await row.getByRole("button", { name: "Extract" }).click();
    await expect(page).toHaveURL(/\/review\/[0-9a-f-]{36}$/);
    await expect(page.getByTestId("mock-label")).toContainText(
      "Mock extraction: replayed synthetic output, not a real AI model",
    );

    // Two fields are low confidence and block adding to the case.
    const lineTotal = page.getByTestId("field-line_items.0.line_total");
    const identifier = page.getByTestId("field-provider_identifier");
    await expect(lineTotal).toContainText("Needs review");
    await expect(identifier).toContainText("Needs review");
    await expect(page.getByTestId("review-summary")).toContainText("2 fields");
    await expect(page.getByTestId("field-invoice_date")).toContainText("Not found in document");
    await expect(page.getByRole("button", { name: "Add to case" })).toBeDisabled();
    const blockers = page.locator("#promotion-blockers");
    await expect(blockers).toContainText("Line 1 line total");
    await expect(blockers).toContainText("Provider identifier");

    // The payer corrects one value and confirms the other.
    await page.getByLabel("Corrected value for Line 1 line total").fill("1200.00");
    await page.getByLabel("Confirm Provider identifier").check();
    await page.getByLabel("Reason for changes").fill("Checked against the paper bill");
    await page.getByRole("button", { name: "Save review" }).click();

    await expect(page.getByText("Needs review", { exact: true })).toHaveCount(0);
    await expect(lineTotal).toContainText("Corrected");
    await expect(lineTotal).toContainText("₹1,200.00");
    await expect(identifier).toContainText("Confirmed");
    await expect(page.getByTestId("review-summary")).toContainText(
      "All low-confidence fields reviewed",
    );
    await expect(page.getByRole("button", { name: "Add to case" })).toBeEnabled();

    // Adding to the case.
    await page.getByRole("button", { name: "Add to case" }).click();
    const added = page.getByTestId("promoted-notice");
    await expect(added).toContainText("Added to case");
    await expect(added).toContainText("3 lines");
    await expect(added).toContainText("₹3,700.00");
    await expect(added).toContainText("still needs your review");

    // The API agrees: one bill, three lines, nothing accepted yet.
    const detail = await getCase(request, payerId, caseId);
    expect(detail.bills).toHaveLength(1);
    expect(detail.bills[0].source_type).toBe("AI_EXTRACTED");
    const lines = [...detail.bills[0].line_items].sort((a, b) => a.line_number - b.line_number);
    expect(lines).toHaveLength(3);
    for (const line of lines) {
      expect(line.status).toBe("PENDING_REVIEW");
      expect(line.source_type).toBe("AI_EXTRACTED");
    }
    expect(lines[0].line_total).toBe("1200.00");

    expect(browserErrors).toEqual([]);
  });

  test("clean bill needs no review and can be added", async ({ page, request }) => {
    test.setTimeout(120_000);
    const payerId = await getDemoPayer(request);
    const { id: caseId } = await createCase(request, payerId);
    const link = await createUploadLink(request, payerId, caseId, ["BILL"]);

    await page.goto(link.path);
    await page.getByLabel("File").setInputFiles(fixture("clean_bill.pdf"));
    await page.getByRole("button", { name: "Upload" }).click();
    await expect(page.getByRole("status").filter({ hasText: "Uploaded" })).toContainText("2 pages");

    await page.goto(reviewPath(caseId));
    await page
      .getByTestId("document-list")
      .getByRole("listitem")
      .first()
      .getByRole("button", { name: "Extract" })
      .click();

    await expect(page.getByTestId("review-summary")).toContainText(
      "All low-confidence fields reviewed",
    );
    await expect(page.getByText("Needs review", { exact: true })).toHaveCount(0);
    await page.getByRole("button", { name: "Add to case" }).click();

    const added = page.getByTestId("promoted-notice");
    await expect(added).toContainText("Added to case");
    await expect(added).toContainText("4 lines");
    await expect(added).toContainText("₹25,000.00");
  });

  test("upload rejects content that does not match its type", async ({ page, request }) => {
    const payerId = await getDemoPayer(request);
    const { id: caseId } = await createCase(request, payerId);
    const link = await createUploadLink(request, payerId, caseId, ["BILL"]);

    await page.goto(link.path);
    await page.getByLabel("File").setInputFiles(fixture("mismatch.pdf"));
    await page.getByRole("button", { name: "Upload" }).click();

    await expect(
      page.getByRole("alert").filter({ hasText: "does not match the declared type" }),
    ).toBeVisible();
    // Nothing was stored.
    const res = await request.get(`http://127.0.0.1:8100/api/cases/${caseId}/documents`, {
      headers: { "X-Demo-User-Id": payerId },
    });
    expect(await res.json()).toEqual([]);
  });

  test("invalid upload link shows a neutral message", async ({ page }) => {
    await page.goto(`/upload/${"A".repeat(43)}`);
    await expect(page.getByText("invalid or has expired")).toBeVisible();
    await expect(page.getByRole("button", { name: "Upload" })).toHaveCount(0);
  });
});
