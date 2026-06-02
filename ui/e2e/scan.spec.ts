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

  test("Z-threshold slider control updates live", async ({ page }) => {
    await login(page);
    // The single-handle Z-threshold slider (PRD F4.1) is present and live.
    await expect(page.getByTestId("z-threshold-slider")).toBeVisible();
    const slider = page.getByTestId("z-threshold-input");
    await slider.evaluate((el, v) => {
      const input = el as HTMLInputElement;
      const setter = Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value",
      )!.set!;
      setter.call(input, v);
      input.dispatchEvent(new Event("input", { bubbles: true }));
    }, "2.5");
    await expect(page.getByTestId("z-threshold-value")).toHaveText("±2.5");
  });
});
