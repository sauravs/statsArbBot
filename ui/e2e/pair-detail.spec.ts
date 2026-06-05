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

async function ensurePairs(page: Page) {
  // Run a scan (fake data source → DEMO pairs) if the table is empty.
  const rows = page.getByTestId("pair-row");
  if ((await rows.count()) === 0) {
    await page.getByTestId("scan-full").click();
    await expect(rows.first()).toBeVisible({ timeout: 20_000 });
  }
}

test.describe("Phase 3 — pair detail + 3-panel charts", () => {
  test("click a pair → detail route renders all three chart panels", async ({
    page,
  }) => {
    await login(page);
    await ensurePairs(page);

    // Navigate into the first pair's detail view.
    const firstLink = page.getByTestId("pair-link").first();
    const label = (await firstLink.innerText()).trim();
    await firstLink.click();

    await expect(page).toHaveURL(/\/dashboard\/pair\/.+\/.+$/);

    // All three panels render (no error / loading state lingering).
    await expect(page.getByTestId("pair-charts")).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByTestId("pair-charts-error")).toHaveCount(0);

    for (const id of [
      "chart-normalized",
      "chart-raw",
      "chart-spread",
      "chart-zscore",
    ]) {
      const panel = page.getByTestId(id);
      await expect(panel).toBeVisible();
      // lightweight-charts renders into a <canvas> inside the panel.
      await expect(panel.locator("canvas").first()).toBeVisible();
    }

    // The threshold legend (Option-B defaults) is shown on the Z-score panel.
    await expect(page.getByText(/entry ±1\.5/)).toBeVisible();
    await expect(page.getByText(/stop ±4/)).toBeVisible();

    // Back to the dashboard.
    await page.getByTestId("back-to-dashboard").click();
    await expect(page).toHaveURL(/\/dashboard$/);
    expect(label.length).toBeGreaterThan(0);
  });
});
