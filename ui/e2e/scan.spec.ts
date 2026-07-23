import { test, expect, Page } from "@playwright/test";
import { resetDemoStateVia } from "./helpers/reset";

const PASSCODE = process.env.DASHBOARD_PASSWORD ?? "123456";

async function login(page: Page) {
  await page.goto("/login");
  const inputs = page.locator('input[inputmode="numeric"]');
  for (let i = 0; i < 6; i++) {
    await inputs.nth(i).fill(PASSCODE[i]);
  }
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

    // Serial column numbers the rows 1..N, and the footer states the total.
    await expect(page.getByTestId("pair-serial").first()).toHaveText("1");
    await expect(page.getByTestId("pair-serial").last()).toHaveText(String(count));
    await expect(page.getByTestId("pairs-total")).toHaveText(
      `${count} ${count === 1 ? "pair" : "pairs"} total`,
    );

    // Survive reload: pairs are read back from the DB, not in-memory state.
    await page.reload();
    await expect(page.getByTestId("pair-row").first()).toBeVisible({
      timeout: 10_000,
    });
    expect(await page.getByTestId("pair-row").count()).toBe(count);
  });

  test("Stop scan: control shows while running and calls the stop endpoint (#59)", async ({
    page,
  }) => {
    // A fake-mode scan completes in milliseconds, so stub the status as running
    // to deterministically exercise the Stop control + its endpoint wiring.
    const runningStatus = {
      running: true,
      phase: 3,
      progress_msg: "Pairs: 100/210 (47.6%) — 2 cointegrated",
      started_at: new Date().toISOString(),
      completed_at: null,
      error: null,
      markets_fetched: 21,
      total_markets: 21,
      pairs_tested: 100,
      pairs_found: 2,
      total_pairs: 210,
      timed_out: false,
      stop_requested: false,
      stopped: false,
    };
    await page.route("**/api/proxy/api/scan/status", (route) =>
      route.fulfill({ status: 200, json: runningStatus }),
    );

    let stopCalled = false;
    await page.route("**/api/proxy/api/scan/stop", (route) => {
      stopCalled = true;
      route.fulfill({
        status: 200,
        json: { ...runningStatus, stop_requested: true, progress_msg: "Stopping scan…" },
      });
    });

    await login(page);

    // While running, the Stop control is offered (and Full scan is disabled).
    const stop = page.getByTestId("scan-stop");
    await expect(stop).toBeVisible();
    await expect(page.getByTestId("scan-full")).toBeDisabled();

    // Clicking it requests a stop and reflects the "Stopping…" state.
    await stop.click();
    await expect.poll(() => stopCalled).toBe(true);
    await expect(stop).toHaveText("Stopping…");
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
