import { test, expect, Page } from "@playwright/test";

// Phase 7 — Fast-Forward Simulation. Drives the real replay engine against the
// offline demo data (SCAN_DATA_SOURCE=fake): seed a cointegration scan → create a
// replay over the demo history → the background run completes → the saved
// aggregates render (equity curve, per-pair P&L, exit reasons, trade count).
// Verifies the gate "an FF run completes over a chosen date range and persists
// viewable results" deterministically with no network.

const PASSCODE = process.env.DASHBOARD_PASSWORD ?? "123456";

async function login(page: Page) {
  await page.goto("/login");
  const inputs = page.locator('input[inputmode="numeric"]');
  for (let i = 0; i < 6; i++) await inputs.nth(i).fill(PASSCODE[i]);
  await expect(page).toHaveURL(/\/dashboard$/);
}

async function ensurePairs(page: Page) {
  // The replay reads the latest cointegration scan from the DB; seed it first.
  const rows = page.getByTestId("pair-row");
  if ((await rows.count()) === 0) {
    await page.getByTestId("scan-full").click();
    await expect(rows.first()).toBeVisible({ timeout: 20_000 });
  }
}

test.describe("Phase 7 — Fast-Forward Simulation", () => {
  test("create a replay → it completes → saved aggregates render", async ({ page }) => {
    await login(page);
    await ensurePairs(page);

    // Navigate to the fast-forward page.
    await page.getByTestId("nav-ff").click();
    await expect(page).toHaveURL(/\/dashboard\/ff$/);
    await expect(page.getByTestId("create-ff-form")).toBeVisible();

    // Create a replay with a low entry threshold so the demo signals trade. Leave
    // the date range blank → the server replays the full demo history.
    await page.getByTestId("ff-label").fill("E2E replay");
    await page.getByTestId("ff-capital").fill("10000");
    await page.getByTestId("ff-entry-z").fill("0.5");
    await page.getByTestId("create-ff-btn").click();

    // The new run is auto-selected; it polls RUNNING → COMPLETED.
    const detail = page.getByTestId("ff-detail");
    await expect(detail).toBeVisible();
    const status = detail.getByTestId("ff-status-badge");
    await expect(status).toHaveText("COMPLETED", { timeout: 30_000 });

    // Saved aggregates are viewable (PRD F7.2): equity curve, trades, per-pair P&L.
    await expect(page.getByTestId("ff-equity-chart")).toBeVisible();
    await expect(page.getByTestId("ff-perpair-table")).toBeVisible();
    await expect(page.getByTestId("ff-perpair-row").first()).toBeVisible();
    await expect(page.getByTestId("ff-exits-list")).toBeVisible();

    // Trade count is a positive integer.
    const trades = await page.getByTestId("ff-total-trades").textContent();
    expect(Number(trades)).toBeGreaterThan(0);
    // Pairs replayed matches the seeded demo scan (2 cointegrated demo pairs).
    await expect(page.getByTestId("ff-pairs-count")).toHaveText("2");
  });
});
