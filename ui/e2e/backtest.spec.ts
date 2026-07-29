import { test, expect, Page } from "@playwright/test";
import { resetDemoStateVia } from "./helpers/reset";

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

// Every test starts from a known backend state. The FastAPI process holds global
// config (data source, signal thresholds, scan state) and the database keeps every
// row an earlier test created, so without this a test's result depends on what ran
// before it — which is exactly why this suite used to fail a different set of tests
// on every run. See e2e/helpers/reset.ts.
test.beforeEach(async () => {
  await resetDemoStateVia();
});

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

    // Gate B3 (Slice 4): once the run completes, the list refreshes and merges the
    // Deflated-Sharpe significance from /api/backtest/significance, so the row carries
    // a "corrected significance" DSR badge (the completed run has enough windows to
    // score). This is the dashboard surface of the multiple-testing correction.
    const dsrBadge = page.getByTestId("badge-dsr").first();
    await expect(dsrBadge).toBeVisible({ timeout: 15_000 });
    await expect(dsrBadge).toContainText("DSR");

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

    // Reason is a plain-English, P&L-neutral label (not the raw enum), and the
    // separate Win/Loss Outcome chip makes the dollar result unmistakable — so a
    // losing take-profit reads as "Reverted" + "Loss", never a green "TAKE_PROFIT"
    // that looks like a win.
    const reason0 = page.getByTestId("bt-blotter-reason").first();
    await expect(reason0).toBeVisible();
    await expect(reason0).not.toContainText("TAKE_PROFIT");
    await expect(reason0).toContainText(/Reverted|Z-stop|Time-stop|Window end|Stopped/);
    await expect(page.getByTestId("bt-blotter-outcome").first()).toContainText(/Win|Loss|Flat/);

    // Cost transparency (Phase-4 Task A): the blotter breaks Net P&L into the
    // components that produce it, so funding — which accrues with hold time and
    // was previously invisible — is on screen next to Hold.
    await expect(page.getByTestId("bt-blotter-cost-legend")).toContainText(
      "Gross + Fees + Funding = Net",
    );
    const money = /^-?\$[\d,]+\.\d{2}$/;
    for (const col of ["gross", "fees", "funding", "net"]) {
      await expect(page.getByTestId(`bt-blotter-${col}`).first()).toHaveText(money);
    }
    // Fees are a deduction, always rendered negative (or exactly zero on a
    // zero-cost counterfactual) — never a credit.
    const fees0 = await page.getByTestId("bt-blotter-fees").first().textContent();
    expect(fees0).toMatch(/^(-\$|\$0\.00$)/);
    // And the four numbers must actually add up: gross + fees + funding = net.
    const usd = async (id: string) =>
      Number(((await page.getByTestId(id).first().textContent()) ?? "").replace(/[$,]/g, ""));
    const [g, f, fu, n] = await Promise.all([
      usd("bt-blotter-gross"),
      usd("bt-blotter-fees"),
      usd("bt-blotter-funding"),
      usd("bt-blotter-net"),
    ]);
    expect(g + f + fu).toBeCloseTo(n, 2);
    // No row may render the reconciliation warning on engine-produced data.
    await expect(page.getByTestId("bt-blotter-mismatch")).toHaveCount(0);

    // Slice A2 — the aggregate view. Both panels come from GET /costs, which
    // aggregates in Postgres (a real group_by, not the in-memory test fake), so
    // this is the only place that path is exercised end to end.
    const bucket = async (testid: string) => {
      const v = async (part: string) =>
        Number(
          ((await page.getByTestId(`${testid}-${part}`).textContent()) ?? "").replace(
            /[$,]/g,
            "",
          ),
        );
      return {
        gross: await v("gross"),
        fees: await v("fees"),
        funding: await v("funding"),
        net: await v("net"),
      };
    };

    // The open window's decomposition summarises the WHOLE window, so its trade
    // count must exceed the 25-row page when the window has more than 25 trades.
    const win = page.getByTestId("bt-window-cost-summary");
    await expect(win).toBeVisible();
    await expect(page.getByTestId("bt-window-cost-summary-meta")).toContainText(/trades? · avg hold \d+h/);
    const w = await bucket("bt-window-cost-summary");
    expect(w.gross + w.fees + w.funding).toBeCloseTo(w.net, 2);
    expect(w.fees).toBeLessThanOrEqual(0);

    // The run-level panel must reconcile too, and agree with the headline metric.
    const run = page.getByTestId("bt-cost-summary");
    await expect(run).toBeVisible();
    const r = await bucket("bt-cost-summary");
    expect(r.gross + r.fees + r.funding).toBeCloseTo(r.net, 2);
    const headline = Number(
      ((await page.getByTestId("bt-net-pnl").textContent()) ?? "").replace(/[$,]/g, ""),
    );
    expect(r.net).toBeCloseTo(headline, 2);

    // The "Losing take-profits" server-side filter narrows to reason=TAKE_PROFIT
    // AND net_pnl<0 — so no Win chip can survive it (or the empty-state shows).
    const ltpFilter = page.getByTestId("bt-blotter-filter-losing-tp");
    await expect(ltpFilter).toHaveAttribute("aria-pressed", "false");
    await ltpFilter.click();
    await expect(ltpFilter).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("bt-blotter-outcome").filter({ hasText: "Win" })).toHaveCount(0);
    // Toggle back off so the chart-link step below sees the full blotter.
    await ltpFilter.click();
    await expect(ltpFilter).toHaveAttribute("aria-pressed", "false");
    await expect(page.getByTestId("bt-blotter-row").first()).toBeVisible();

    // A trade's "Chart" link opens the 4-panel per-trade chart in a new tab (#166),
    // with the trade's entry/exit marked. Verify the chart page renders its panels.
    const [chartTab] = await Promise.all([
      page.context().waitForEvent("page"),
      page.getByTestId("bt-blotter-chart-link").first().click(),
    ]);
    await expect(chartTab.getByTestId("bt-trade-chart")).toBeVisible({ timeout: 15_000 });
    await expect(chartTab.getByTestId("chart-normalized")).toBeVisible();
    await expect(chartTab.getByTestId("chart-zscore")).toBeVisible();

    // The summary explains WHY net P&L ≠ "profit": net = gross − fees + funding.
    // And the reason badge uses the same P&L-neutral label as the blotter.
    const costs = chartTab.getByTestId("bt-trade-costs");
    await expect(costs).toBeVisible();
    await expect(costs).toContainText("Gross");
    await expect(costs).toContainText("Fees");
    await expect(costs).toContainText("Funding");
    await expect(chartTab.getByTestId("bt-trade-reason")).not.toContainText("TAKE_PROFIT");

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
    // The legend uses the same plain-English labels as the blotter (not raw enums).
    await expect(page.getByTestId("bt-exits-donut")).toBeVisible();
    await expect(page.getByTestId("bt-exits-list")).toContainText("%");
    await expect(page.getByTestId("bt-exits-list")).not.toContainText("TAKE_PROFIT");
    await expect(page.getByTestId("bt-exits-list")).toContainText(
      /Reverted|Z-stop|Time-stop|Window end|Stopped/,
    );
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

  test("per-strategy universe filter persists + carries the honesty note (WS1)", async ({
    page,
  }) => {
    await login(page);
    await page.getByTestId("nav-backtest").click();
    await expect(page.getByTestId("create-strategy-form")).toBeVisible();

    await page.getByTestId("strategy-name").fill("E2E Universe Filter");
    await page.getByTestId("strategy-entry-z").fill("1");
    await page.getByTestId("strategy-exit-z").fill("0.3");
    await page.getByTestId("strategy-scan-days").fill("7");
    await page.getByTestId("strategy-trade-days").fill("3");

    await page.getByTestId("strategy-advanced-toggle").click();
    // The filter is framed as tractability/honesty, NOT a profit lever.
    const note = page.getByTestId("strategy-univ-filter-note");
    await expect(note).toBeVisible();
    await expect(note).toContainText("not a profit lever");

    await page.getByTestId("strategy-univ-min-dollar-vol").fill("1000000");
    await page.getByTestId("strategy-univ-max-half-spread").fill("0.05");
    await page.getByTestId("create-strategy-btn").click();
    await expect(page.getByTestId("strategy-detail")).toBeVisible();

    // Full UI→API→DB round-trip: the created row persisted the per-strategy filter.
    const list = await page.request
      .get("/api/proxy/api/backtest/strategies")
      .then((r) => r.json());
    const row = list.strategies.find(
      (s: { name: string }) => s.name === "E2E Universe Filter",
    );
    expect(row).toBeTruthy();
    expect(row.backtest_min_dollar_volume).toBe(1_000_000);
    expect(row.backtest_max_half_spread_pct).toBe(0.05);
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
