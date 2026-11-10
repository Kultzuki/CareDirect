import { expect, test } from "@playwright/test";

test("API health reports ok with database", async ({ request }) => {
  const res = await request.get("http://127.0.0.1:8100/health");
  expect(res.status()).toBe(200);
  expect(await res.json()).toEqual({ status: "ok", database: "ok" });
});

test("web health reports ok", async ({ request }) => {
  const res = await request.get("/health");
  expect(res.status()).toBe(200);
  expect(await res.json()).toEqual({ status: "ok", service: "web" });
});

test("home page shows API status ok", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "CareDirect" })).toBeVisible();
  await expect(page.getByTestId("api-status")).toHaveText("API: ok");
});
