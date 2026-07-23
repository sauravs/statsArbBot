import { test, expect, Page } from "@playwright/test";
import { resetDemoStateVia } from "./helpers/reset";

// Phase 5b — Live Trading UI. Drives the real engine path against the offline
// demo trade client (SCAN_DATA_SOURCE=fake): activate → account renders →
// entry scan opens a position → abort moves it to history → deactivate. Verifies
// "UI reflects engine state; controls work" deterministically with no network.

const PASSCODE = process.env.DASHBOARD_PASSWORD ?? "123456";

async function login(page: Page) {
  await page.goto("/login");
  const inputs = page.locator('input[inputmode="numeric"]');
  for (let i = 0; i < 6; i++) await inputs.nth(i).fill(PASSCODE[i]);
  await expect(page).toHaveURL(/\/dashboard$/);
}

async function ensurePairs(page: Page) {
  // The live entry scan reads the latest cointegration scan from the DB, so seed
  // it from the dashboard first if no pairs exist yet.
  const rows = page.getByTestId("pair-row");
  if ((await rows.count()) === 0) {
    await page.getByTestId("scan-full").click();
    await expect(rows.first()).toBeVisible({ timeout: 20_000 });
  }
}

// Every test starts from a known backend state. The FastAPI process holds global
// config (data source, signal thresholds, scan state) and the database keeps every
// row an earlier test created, so without this a test's result depends on what ran
// before it — which is exactly why this suite used to fail a different set of tests
// on every run. See e2e/helpers/reset.ts.
test.beforeEach(async () => {
  await resetDemoStateVia();
});

test.describe("Phase 5b — Live Trading UI", () => {
  test("activate → account → entry scan opens trade → abort → history → deactivate", async ({
    page,
  }) => {
    await login(page);
    await ensurePairs(page);

    // Navigate to the live trading page.
    await page.getByTestId("nav-live").click();
    await expect(page).toHaveURL(/\/dashboard\/live$/);
    await expect(page.getByTestId("bot-controls")).toBeVisible();

    // Forward-test is the default mode; production tab shows a warning.
    await expect(page.getByTestId("mode-tab-forward_test")).toBeVisible();
    await page.getByTestId("mode-tab-production").click();
    await expect(page.getByTestId("production-warning")).toBeVisible();
    await page.getByTestId("mode-tab-forward_test").click();

    // Account card renders the demo collateral/equity from the engine.
    await expect(page.getByTestId("account-collateral")).not.toHaveText("—");
    await expect(page.getByTestId("account-equity")).not.toHaveText("—");

    // Activate the bot — status flips to ACTIVE.
    await expect(page.getByTestId("bot-status")).toHaveText("INACTIVE");
    await page.getByTestId("activate-btn").click();
    await expect(page.getByTestId("bot-status")).toHaveText("ACTIVE");

    // No open positions yet.
    await expect(page.getByTestId("open-trades-empty")).toBeVisible();

    // Lower the entry-Z so a demo pair (|Z| ≈ 0.95) becomes an active signal, then
    // run the entry scan — a real two-leg position opens through the engine.
    await page.getByTestId("entry-z-input").fill("0.5");
    const [scan] = await Promise.all([
      page.waitForResponse((r) => r.url().includes("entry-scan")),
      page.getByTestId("entry-scan-btn").click(),
    ]);

    // An approval gate is a process-wide singleton (trading/approval.py). When
    // Telegram credentials are present the runtime swaps the auto-approve default
    // for the Telegram gate, which holds every signal for a human and reports the
    // pair as "rejected" — so this scenario cannot open a position at all. That is
    // a property of the environment, not a regression, and it is why this used to
    // fail with an opaque 15s timeout on any machine with Telegram configured.
    // Say so plainly instead. CI runs without those credentials, so the assertions
    // below execute for real there.
    const outcome = await scan.json().catch(() => ({}) as any);
    const gated = (outcome?.outcomes ?? []).some((o: any) => o.action === "rejected");
    test.skip(
      gated,
      "An approval gate (Telegram) is installed in this environment, so entry " +
        "signals are held for human approval and no position can open. Run without " +
        "TELEGRAM_* credentials to exercise this path.",
    );

    const openRow = page.getByTestId("open-trade-row").first();
    await expect(openRow).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("portfolio-open")).toHaveText("1");

    // Abort all — confirm in the modal — closes the position and books it as
    // ABORTED in the trade history; open table empties.
    await page.getByTestId("abort-btn").click();
    await expect(page.getByTestId("abort-modal")).toBeVisible();
    await page.getByTestId("abort-confirm").click();

    const historyRow = page.getByTestId("history-row").first();
    await expect(historyRow).toBeVisible({ timeout: 15_000 });
    await expect(historyRow.getByTestId("history-status")).toHaveText("CLOSED");
    await expect(page.getByTestId("open-trades-empty")).toBeVisible();

    // Deactivate — status flips back to INACTIVE.
    await page.getByTestId("deactivate-btn").click();
    await expect(page.getByTestId("bot-status")).toHaveText("INACTIVE");
  });
});
