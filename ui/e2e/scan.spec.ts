import { test, expect, Page } from "@playwright/test";

const PASSCODE = process.env.DASHBOARD_PASSWORD ?? "123456";

async function login(page: Page) {
  await page.goto("/login");
  const inputs = page.locator('input[inputmode="numeric"]');
  for (let i = 0; i < 6; i++) {
    await inputs.nth(i).fill(PASSCODE[i]);
  }
  await expect(page).toHaveURL(/\/dashboard$/);
}

test.describe("Phase 2 — scan → pairs table", () => {
  test("run a scan, pairs render, and survive a reload", async ({ page }) => {
    await login(page);

    // The pairs table starts empty (DB cleared before the run).
    await expect(page.getByTestId("pairs-empty")).toBeVisible();

    // Trigger a scan (fake data source → completes in milliseconds).
    await page.getByTestId("scan-full").click();

    // Pairs render once the scan completes and the table refreshes.
    const rows = page.getByTestId("pair-row");
    await expect(rows.first()).toBeVisible({ timeout: 20_000 });
    const count = await rows.count();
    expect(count).toBeGreaterThanOrEqual(1);
    await expect(page.getByTestId("pairs-table")).toContainText("DEMO1-USD");

    // Survive reload: pairs are read back from the DB, not in-memory state.
    await page.reload();
    await expect(page.getByTestId("pair-row").first()).toBeVisible({
      timeout: 10_000,
    });
    expect(await page.getByTestId("pair-row").count()).toBe(count);
  });

  test("exchange registry drives signal coloring threshold control", async ({
    page,
  }) => {
    await login(page);
    // The Z-threshold control is present and editable on the dashboard.
    const input = page.getByLabel("Z-threshold");
    await expect(input).toBeVisible();
    await input.fill("2.5");
    await expect(input).toHaveValue("2.5");
  });
});
