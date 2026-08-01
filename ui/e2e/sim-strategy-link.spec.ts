import { test, expect, Page } from "@playwright/test";
import { authedRequest, resetDemoStateVia } from "./helpers/reset";

// Phase 5 — the simulation form can express the recommended parameterisation, and a
// strategy being paper-traded is visibly marked on the backtest list.
//
// Both are regressions worth guarding. The form previously exposed four fields and
// could not set per-leg size or the concurrency cap at all — the two knobs that
// decide whether a paper run is executable by hand. And the "in sim" highlight is
// the operator-facing answer to "which strategy did we pick?", which is invisible
// unless the session→strategy link survives the round trip.

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

test.describe("Phase 5 — sim parameters & strategy link", () => {
  test("the create form exposes the executable knobs and loads the preset", async ({
    page,
  }) => {
    await login(page);
    await page.goto("/dashboard/sim");

    // The two fields whose absence made the rehearsal unexpressible.
    await expect(page.getByTestId("sim-usd-per-trade")).toBeVisible();
    await expect(page.getByTestId("sim-max-active-pairs")).toBeVisible();

    await page.getByTestId("sim-preset-btn").click();
    await expect(page.getByTestId("sim-entry-z")).toHaveValue("4");
    await expect(page.getByTestId("sim-exit-z")).toHaveValue("0.5");
    await expect(page.getByTestId("sim-stop-z")).toHaveValue("5");
    await expect(page.getByTestId("sim-usd-per-trade")).toHaveValue("100");
    // The cap is the whole point of the recommendation.
    await expect(page.getByTestId("sim-max-active-pairs")).toHaveValue("5");

    await page.getByTestId("sim-advanced-toggle").click();
    await expect(page.getByTestId("sim-pvalue-max")).toHaveValue("0.01");
    await expect(page.getByTestId("sim-max-half-life")).toHaveValue("72");
  });

  test("a strategy paper-traded by a live session is marked on the backtest list", async ({
    page,
    baseURL,
  }) => {
    const api = await authedRequest(baseURL!);
    const stRes = await api.post("/api/proxy/api/backtest/strategies", {
      data: {
        name: "phase5-link-e2e",
        entry_threshold: 4.0,
        exit_threshold: 0.5,
        stop_threshold: 5.0,
        usd_per_trade: 100,
        starting_capital: 10000,
      },
    });
    expect(stRes.ok(), await stRes.text()).toBeTruthy();
    const strategy = await stRes.json();

    const simRes = await api.post("/api/proxy/api/sim/sessions", {
      data: {
        label: "phase5-link-e2e-sim",
        starting_capital: 2000,
        interval_seconds: 300,
        entry_threshold: 4.0,
        usd_per_trade: 100,
        max_active_pairs: 5,
        pvalue_max: 0.01,
        max_half_life_h: 72,
        source_strategy_id: strategy.id,
      },
    });
    expect(simRes.ok(), await simRes.text()).toBeTruthy();
    const session = await simRes.json();
    // The link must survive the write→read round trip; the serialiser whitelists
    // columns, so a dropped field would silently disable the highlight.
    expect(session.source_strategy_id).toBe(strategy.id);

    await login(page);
    await page.goto("/dashboard/backtest");

    const row = page
      .getByTestId("strategy-row")
      .filter({ hasText: "phase5-link-e2e" })
      .first();
    await expect(row).toBeVisible({ timeout: 20_000 });
    await expect(row.getByTestId("badge-live-sim")).toHaveText(/In sim/i);

    await api.dispose();
  });
});
