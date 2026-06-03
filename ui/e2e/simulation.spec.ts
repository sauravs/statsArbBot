import { test, expect, Page } from "@playwright/test";

// Phase 6 — Real-Time Simulation. Drives the real engine path against the offline
// demo data (SCAN_DATA_SOURCE=fake): create a session → run a tick → a virtual
// position opens on a real live signal (DEMO3/DEMO4, |Z| ≈ 0.95) → equity/positions
// update → stop force-closes it into the trade history. Verifies the gate
// "session ticks → virtual trades on real signals → positions/PnL/equity update"
// deterministically with no network.

const PASSCODE = process.env.DASHBOARD_PASSWORD ?? "123456";

async function login(page: Page) {
  await page.goto("/login");
  const inputs = page.locator('input[inputmode="numeric"]');
  for (let i = 0; i < 6; i++) await inputs.nth(i).fill(PASSCODE[i]);
  await expect(page).toHaveURL(/\/dashboard$/);
}

async function ensurePairs(page: Page) {
  // The simulation reads the latest cointegration scan from the DB, so seed it
  // from the dashboard first if no pairs exist yet.
  const rows = page.getByTestId("pair-row");
  if ((await rows.count()) === 0) {
    await page.getByTestId("scan-full").click();
    await expect(rows.first()).toBeVisible({ timeout: 20_000 });
  }
}

test.describe("Phase 6 — Real-Time Simulation", () => {
  test("create session → tick opens a virtual trade → stop closes it", async ({ page }) => {
    await login(page);
    await ensurePairs(page);

    // Navigate to the simulation page.
    await page.getByTestId("nav-sim").click();
    await expect(page).toHaveURL(/\/dashboard\/sim$/);
    await expect(page.getByTestId("create-sim-form")).toBeVisible();

    // Create a session with an entry threshold low enough for the demo signal
    // (DEMO3/DEMO4 sits at |Z| ≈ 0.95).
    await page.getByTestId("sim-label").fill("E2E sim");
    await page.getByTestId("sim-capital").fill("10000");
    await page.getByTestId("sim-entry-z").fill("0.5");
    await page.getByTestId("create-sim-btn").click();

    // The new session is auto-selected and RUNNING. Scope the status badge to the
    // detail panel (the session list also renders a per-row badge).
    const detail = page.getByTestId("sim-detail");
    const detailStatus = detail.getByTestId("sim-status-badge");
    await expect(detail).toBeVisible();
    await expect(detailStatus).toHaveText("RUNNING");
    await expect(page.getByTestId("sim-positions-empty")).toBeVisible();

    // Run one tick — a real two-leg virtual position opens through the engine.
    await page.getByTestId("sim-tick-btn").click();
    const posRow = page.getByTestId("sim-position-row").first();
    await expect(posRow).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("sim-tick-count")).toHaveText("1");
    // Equity is marked to market (non-empty, dollar-formatted).
    await expect(page.getByTestId("sim-equity-val")).toContainText("$");

    // Pause then resume — status transitions reflect engine state.
    await page.getByTestId("sim-pause-btn").click();
    await expect(detailStatus).toHaveText("PAUSED");
    await page.getByTestId("sim-resume-btn").click();
    await expect(detailStatus).toHaveText("RUNNING");

    // Stop — the open position is force-closed and booked into the trade history.
    await page.getByTestId("sim-stop-btn").click();
    await expect(detailStatus).toHaveText("STOPPED");
    const tradeRow = page.getByTestId("sim-trade-row").first();
    await expect(tradeRow).toBeVisible({ timeout: 15_000 });
    await expect(tradeRow.getByTestId("sim-trade-reason")).toHaveText("STOPPED");
    await expect(page.getByTestId("sim-positions-empty")).toBeVisible();
  });
});
