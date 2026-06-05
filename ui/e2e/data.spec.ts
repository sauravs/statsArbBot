import { test, expect, Page } from "@playwright/test";

// Historical-data inventory section (issue #80): a read-only view of the cached
// OHLCV/funding coverage the engines replay. Runs against the seeded cache in the
// containerised stack (the inventory reads the cache table directly, independent
// of the fake/dydx data-source toggle).

const PASSCODE = process.env.DASHBOARD_PASSWORD ?? "123456";

async function login(page: Page) {
  await page.goto("/login");
  const inputs = page.locator('input[inputmode="numeric"]');
  for (let i = 0; i < 6; i++) await inputs.nth(i).fill(PASSCODE[i]);
  await expect(page).toHaveURL(/\/dashboard$/);
}

test.describe("Data — historical-data inventory (#80)", () => {
  test("nav → Data section shows cached coverage summary + per-market table", async ({
    page,
  }) => {
    await login(page);

    await page.getByTestId("nav-data").click();
    await expect(page).toHaveURL(/\/dashboard\/data$/);

    await expect(page.getByTestId("data-inventory")).toBeVisible({ timeout: 15_000 });

    // Summary: a positive market count + a coverage range.
    const markets = await page.getByTestId("di-markets").textContent();
    expect(Number(markets)).toBeGreaterThan(0);
    await expect(page.getByTestId("di-coverage")).toContainText(/\d{4}-\d{2}-\d{2} → \d{4}-\d{2}-\d{2}/);

    // Per-market table renders at least one row with a completeness %.
    await expect(page.getByTestId("di-table")).toBeVisible();
    await expect(page.getByTestId("di-row").first()).toBeVisible();
    await expect(page.getByTestId("di-row").first()).toContainText("%");
  });

  test("fetch control validates the range before hitting the indexer (#81)", async ({
    page,
  }) => {
    await login(page);
    await page.getByTestId("nav-data").click();
    await expect(page.getByTestId("data-fetch")).toBeVisible({ timeout: 15_000 });

    // Client-side guard: start ≥ end.
    await page.getByTestId("fetch-start").fill("2024-02-01");
    await page.getByTestId("fetch-end").fill("2024-01-01");
    await page.getByTestId("fetch-start-btn").click();
    await expect(page.getByTestId("fetch-error")).toContainText(/before/i);

    // Server-side cap: an over-long span is rejected (422) before any fetch runs.
    await page.getByTestId("fetch-start").fill("2020-01-01");
    await page.getByTestId("fetch-end").fill("2024-01-01");
    await page.getByTestId("fetch-start-btn").click();
    await expect(page.getByTestId("fetch-error")).toContainText(/range too large/i);
  });
});
