import { test, expect, Page } from "@playwright/test";

// Phase 8 — Walk-Forward Backtest. Drives the real backtest engine against the
// offline demo data (SCAN_DATA_SOURCE=fake): create a strategy with short
// scan/trade windows over the demo history → run it → the background sweep
// completes → the saved aggregates + report render (equity curve, per-window
// table, per-pair P&L, report). A second strategy demonstrates ranking. Verifies
// the gate "a backtest runs to completion, ranks strategies, and renders equity
// curves + reports" deterministically with no network.

const PASSCODE = process.env.DASHBOARD_PASSWORD ?? "123456";

async function login(page: Page) {
  await page.goto("/login");
  const inputs = page.locator('input[inputmode="numeric"]');
  for (let i = 0; i < 6; i++) await inputs.nth(i).fill(PASSCODE[i]);
  await expect(page).toHaveURL(/\/dashboard$/);
}

async function createStrategy(page: Page, name: string, entryZ: string) {
  await page.getByTestId("strategy-name").fill(name);
  await page.getByTestId("strategy-entry-z").fill(entryZ);
  // Exit must satisfy exit < entry (#78); the loose case uses entry 0.5, so keep
  // exit below it.
  await page.getByTestId("strategy-exit-z").fill("0.3");
  await page.getByTestId("strategy-scan-days").fill("7");
  await page.getByTestId("strategy-trade-days").fill("3");
  await page.getByTestId("create-strategy-btn").click();
  // The new strategy is auto-selected. Its detail loads asynchronously, so the
  // panel briefly still shows the *previous* selection's detail — if we clicked Run
  // then, it would act on the stale strategy id. A freshly-created strategy is
  // PENDING, so wait for that badge to confirm the new strategy's detail is loaded
  // before any Run/assert (the Run button reads the loaded detail's id).
  await expect(page.getByTestId("strategy-detail")).toBeVisible();
  await expect(
    page.getByTestId("strategy-detail").getByTestId("bt-status-badge"),
  ).toHaveText("PENDING");
}

async function runToCompletion(page: Page) {
  await page.getByTestId("bt-run-btn").click();
  const status = page.getByTestId("strategy-detail").getByTestId("bt-status-badge");
  await expect(status).toHaveText("COMPLETED", { timeout: 30_000 });
}

test.describe("Phase 8 — Walk-Forward Backtest", () => {
  test("create + run a backtest → completes with ranked results + report", async ({ page }) => {
    await login(page);

    // Navigate to the backtest page.
    await page.getByTestId("nav-backtest").click();
    await expect(page).toHaveURL(/\/dashboard\/backtest$/);
    await expect(page.getByTestId("create-strategy-form")).toBeVisible();

    // Create + run the first strategy (low entry threshold so the demo signals trade).
    await createStrategy(page, "E2E Loose", "0.5");
    await runToCompletion(page);

    // Saved aggregates are viewable (PRD F8): equity curve, per-window, report.
    await expect(page.getByTestId("bt-equity-chart")).toBeVisible();
    await expect(page.getByTestId("bt-perwindow-table")).toBeVisible();
    await expect(page.getByTestId("bt-perwindow-row").first()).toBeVisible();
    await expect(page.getByTestId("bt-report")).toBeVisible();
    await expect(page.getByTestId("bt-report")).toContainText("Backtest Report");

    // Trade count is a positive integer and the run is ranked.
    const trades = await page.getByTestId("bt-total-trades").textContent();
    expect(Number(trades)).toBeGreaterThan(0);
    await expect(page.getByTestId("bt-rank")).toBeVisible();

    // Drill into a window's per-trade blotter (#162): click a window row that has
    // trades (marked with ▸) → the blotter lazy-loads its trades with the
    // entry/exit + reason columns and a paginated range read.
    await page.getByTestId("bt-perwindow-row").filter({ hasText: "▸" }).first().click();
    await expect(page.getByTestId("bt-blotter")).toBeVisible();
    await expect(page.getByTestId("bt-blotter-row").first()).toBeVisible();
    await expect(page.getByTestId("bt-blotter-range")).toContainText("of");

    // A trade's "Chart" link opens the 4-panel per-trade chart in a new tab (#166),
    // with the trade's entry/exit marked. Verify the chart page renders its panels.
    const [chartTab] = await Promise.all([
      page.context().waitForEvent("page"),
      page.getByTestId("bt-blotter-chart-link").first().click(),
    ]);
    await expect(chartTab.getByTestId("bt-trade-chart")).toBeVisible({ timeout: 15_000 });
    await expect(chartTab.getByTestId("chart-normalized")).toBeVisible();
    await expect(chartTab.getByTestId("chart-zscore")).toBeVisible();

    // #172 — entry/exit are drawn as distinct-colored VERTICAL time-lines (not
    // near-identical horizontal price-lines). Both lines render across the panels,
    // and hovering one reveals a tooltip with that point's time (+ value).
    const vEntry = chartTab.getByTestId("bt-chart-vline-entry").first();
    const vExit = chartTab.getByTestId("bt-chart-vline-exit").first();
    await expect(vEntry).toBeVisible();
    await expect(vExit).toBeVisible();
    await vEntry.hover();
    const tip = chartTab.getByTestId("bt-chart-vline-tip").first();
    await expect(tip).toBeVisible();
    await expect(tip).toContainText("UTC");
    await chartTab.close();

    // Exit reasons render as a donut with a count·% legend + a health read (#79).
    await expect(page.getByTestId("bt-exits-donut")).toBeVisible();
    await expect(page.getByTestId("bt-exits-list")).toContainText("%");
    await expect(page.getByTestId("bt-exits-health")).toBeVisible();

    // A second strategy → both are ranked by net P&L (F8.3).
    await createStrategy(page, "E2E Tight", "1.5");
    await runToCompletion(page);

    // The comparison list now shows a rank-1 row.
    await expect(
      page.getByTestId("strategy-rank").filter({ hasText: /^1$/ }).first(),
    ).toBeVisible();
  });

  test("form exposes Exit/Stop + Advanced; summary reflects them (#78)", async ({
    page,
  }) => {
    await login(page);
    await page.getByTestId("nav-backtest").click();
    await expect(page.getByTestId("create-strategy-form")).toBeVisible();

    await page.getByTestId("strategy-name").fill("E2E Custom");
    await page.getByTestId("strategy-entry-z").fill("2");
    await page.getByTestId("strategy-exit-z").fill("0.3");
    await page.getByTestId("strategy-stop-z").fill("5");
    await page.getByTestId("strategy-scan-days").fill("7");
    await page.getByTestId("strategy-trade-days").fill("3");

    // Advanced is collapsed by default; open it and tweak a knob.
    await expect(page.getByTestId("strategy-advanced-panel")).toBeHidden();
    await page.getByTestId("strategy-advanced-toggle").click();
    await page.getByTestId("strategy-pvalue").fill("0.1");

    await page.getByTestId("create-strategy-btn").click();

    const detail = page.getByTestId("strategy-detail");
    await expect(detail).toBeVisible();
    await expect(detail).toContainText("Entry |Z|≥2");
    await expect(detail).toContainText("Exit |Z|<0.3");
    await expect(detail).toContainText("Stop |Z|≥5");
  });

  test("rejects exit ≥ entry client-side (#78)", async ({ page }) => {
    await login(page);
    await page.getByTestId("nav-backtest").click();
    await expect(page.getByTestId("create-strategy-form")).toBeVisible();

    await page.getByTestId("strategy-name").fill("E2E Bad");
    await page.getByTestId("strategy-entry-z").fill("1");
    await page.getByTestId("strategy-exit-z").fill("1.5");
    await page.getByTestId("create-strategy-btn").click();

    await expect(page.getByTestId("create-strategy-error")).toContainText(
      "exit < entry < stop",
    );
    // Nothing was created → the right pane still shows the empty state.
    await expect(page.getByTestId("strategy-detail")).toHaveCount(0);
  });
});
