import { test, expect } from "@playwright/test";
import { resetDemoStateVia } from "./helpers/reset";

const PASSCODE = process.env.DASHBOARD_PASSWORD ?? "123456";

// Every test starts from a known backend state. The FastAPI process holds global
// config (data source, signal thresholds, scan state) and the database keeps every
// row an earlier test created, so without this a test's result depends on what ran
// before it — which is exactly why this suite used to fail a different set of tests
// on every run. See e2e/helpers/reset.ts.
test.beforeEach(async () => {
  await resetDemoStateVia();
});

test.describe("Phase 0 smoke", () => {
  test("unauthenticated visit redirects to login", async ({ page }) => {
    await page.goto("/dashboard");
    await expect(page).toHaveURL(/\/login$/);
    await expect(
      page.getByRole("heading", { name: "statsArbBot" }),
    ).toBeVisible();
  });

  test("wrong passcode is rejected", async ({ page }) => {
    await page.goto("/login");
    const inputs = page.locator('input[inputmode="numeric"]');
    const wrong = "000000";
    for (let i = 0; i < 6; i++) {
      await inputs.nth(i).fill(wrong[i]);
    }
    await expect(page.getByText(/Incorrect passcode/i)).toBeVisible();
    await expect(page).toHaveURL(/\/login$/);
  });

  test("correct passcode logs in and lands on the dashboard", async ({
    page,
  }) => {
    await page.goto("/login");
    const inputs = page.locator('input[inputmode="numeric"]');
    for (let i = 0; i < 6; i++) {
      await inputs.nth(i).fill(PASSCODE[i]);
    }
    await expect(page).toHaveURL(/\/dashboard$/);
    await expect(
      page.getByRole("heading", { name: "Manual Trading" }),
    ).toBeVisible();
  });
});
