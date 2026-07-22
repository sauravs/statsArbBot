import { test, expect, Page } from "@playwright/test";
import { resetDemoStateVia } from "./helpers/reset";

const PASSCODE = process.env.DASHBOARD_PASSWORD ?? "123456";

async function login(page: Page) {
  await page.goto("/login");
  const inputs = page.locator('input[inputmode="numeric"]');
  for (let i = 0; i < 6; i++) await inputs.nth(i).fill(PASSCODE[i]);
  await expect(page).toHaveURL(/\/dashboard$/);
}

// Every test starts from a known backend state. The FastAPI process holds global
// config (data source, signal thresholds, scan state) and the database keeps every
// row an earlier test created, so without this a test's result depends on what ran
// before it — which is exactly why this suite used to fail a different set of tests
// on every run. See e2e/helpers/reset.ts.
test.beforeEach(async () => {
  await resetDemoStateVia();
});

test.describe("Manual Trading — data-source toggle (#43)", () => {
  // Safety net: the toggle mutates the shared api process's global source, so
  // ALWAYS restore fake mode regardless of how the test ends, or later specs
  // would run against the live dYdX indexer.
  test.afterEach(async ({ page }) => {
    await page.request
      .post("/api/proxy/api/system/data-source", {
        data: { source: "fake" },
        headers: { "Content-Type": "application/json" },
      })
      .catch(() => {});
  });

  test("selects Demo / dYdX / Hyperliquid from the header (no restart)", async ({ page }) => {
    await login(page);

    const badge = page.getByTestId("data-source-badge");
    const select = page.getByTestId("data-source-select");
    await expect(badge).toHaveText("DEMO DATA");

    // Switch to dYdX (two-step: select → Switch).
    await select.selectOption("dydx");
    await page.getByTestId("data-source-confirm").click();
    await expect(badge).toHaveText("DYDX LIVE");

    // Switch to Hyperliquid (the new venue, Slice 5).
    await select.selectOption("hyperliquid");
    await page.getByTestId("data-source-confirm").click();
    await expect(badge).toHaveText("HYPERLIQUID LIVE");

    // Back to demo.
    await select.selectOption("fake");
    await page.getByTestId("data-source-confirm").click();
    await expect(badge).toHaveText("DEMO DATA");
  });
});
