import { test, expect, Page } from "@playwright/test";
import { resetDemoStateVia } from "./helpers/reset";

const PASSCODE = process.env.DASHBOARD_PASSWORD ?? "123456";

async function login(page: Page) {
  await page.goto("/login");
  const inputs = page.locator('input[inputmode="numeric"]');
  for (let i = 0; i < 6; i++) await inputs.nth(i).fill(PASSCODE[i]);
  await expect(page).toHaveURL(/\/dashboard$/);
}

test.beforeEach(async () => {
  await resetDemoStateVia();
});

test.describe("Scan list minimisation — read-time filter (WS2)", () => {
  // The knobs are process-global; always restore OFF so later specs see the full list.
  test.afterEach(async ({ page }) => {
    await page.request
      .post("/api/proxy/api/system/scan-list-filters", {
        data: { max_half_spread_pct: 0, top_n: 0 },
        headers: { "Content-Type": "application/json" },
      })
      .catch(() => {});
  });

  test("top-N cap trims the pairs list without a re-scan", async ({ page }) => {
    await login(page);

    // A demo scan produces several cointegrated pairs.
    await page.getByTestId("scan-full").click();
    const rows = page.getByTestId("pair-row");
    await expect(rows.first()).toBeVisible({ timeout: 20_000 });
    const before = await rows.count();
    expect(before).toBeGreaterThanOrEqual(1);

    // The framing note is present (tractability, not alpha).
    await expect(
      page.getByTestId("scan-list-filter-control").getByTestId("info-tip"),
    ).toBeVisible();

    // Cap to top-1 by tradability — no re-scan; the stored scan is untouched.
    await page.getByTestId("scan-list-topn-input").fill("1");
    await page.getByTestId("scan-list-filter-apply").click();

    // Badge reflects the active cap and the list trims to a single row.
    await expect(page.getByTestId("scan-list-filter-badge")).toContainText("top 1");
    await expect(page.getByTestId("pair-row")).toHaveCount(1, { timeout: 10_000 });
  });

  test("rejects a negative top-N (422) and surfaces the error", async ({ page }) => {
    await login(page);
    await page.getByTestId("scan-list-topn-input").fill("-5");
    await page.getByTestId("scan-list-filter-apply").click();
    await expect(page.getByTestId("scan-list-filter-error")).toBeVisible();
  });
});
