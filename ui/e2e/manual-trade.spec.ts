import { test, expect, Page } from "@playwright/test";

const PASSCODE = process.env.DASHBOARD_PASSWORD ?? "123456";

async function login(page: Page) {
  await page.goto("/login");
  const inputs = page.locator('input[inputmode="numeric"]');
  for (let i = 0; i < 6; i++) await inputs.nth(i).fill(PASSCODE[i]);
  await expect(page).toHaveURL(/\/dashboard$/);
}

async function ensurePairs(page: Page) {
  const rows = page.getByTestId("pair-row");
  if ((await rows.count()) === 0) {
    await page.getByTestId("scan-full").click();
    await expect(rows.first()).toBeVisible({ timeout: 20_000 });
  }
}

async function setThreshold(page: Page, value: string) {
  await page.getByTestId("z-threshold-input").evaluate((el, v) => {
    const input = el as HTMLInputElement;
    const setter = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!;
    setter.call(input, v);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  }, value);
}

test.describe("Manual Trading — PR-1 UX quick wins (#37)", () => {
  test("header nav, both-leg signal, base/quote header, and Charts affordance", async ({
    page,
  }) => {
    await login(page);
    await ensurePairs(page);

    // Header nav has a "Manual Trading" entry linking home (#37 PR-1).
    const navManual = page.getByTestId("nav-manual");
    await expect(navManual).toBeVisible();
    await expect(navManual).toHaveText("Manual Trading");
    await expect(navManual).toHaveAttribute("href", "/dashboard");

    // PAIR column header names base vs quote.
    await expect(
      page.getByTestId("pairs-table").getByText("Pair (Base / Quote)"),
    ).toBeVisible();

    // Each pair row has an explicit "Charts ›" affordance to the 3-panel charts.
    const chartsLink = page.getByTestId("pair-charts-link").first();
    await expect(chartsLink).toBeVisible();
    await expect(chartsLink).toHaveText("Charts ›");

    // Signal names both legs when a pair is active.
    await setThreshold(page, "0.5");
    const sig = page
      .getByTestId("pair-row")
      .filter({ hasText: /SELL base · BUY quote|BUY base · SELL quote/ });
    await expect(sig.first()).toBeVisible();
  });

  test("threshold reveals record → record (OPEN) → close (CLOSED + P&L)", async ({
    page,
  }) => {
    await login(page);
    await ensurePairs(page);

    // At the default threshold (1.5) no demo pair is active (max |Z| ≈ 0.95),
    // so no Record button is shown (F4.3).
    await setThreshold(page, "1.5");
    await expect(page.getByTestId("record-trade-btn")).toHaveCount(0);

    // Lower the threshold → an active-signal pair reveals the Record button.
    await setThreshold(page, "0.5");
    const recordBtn = page.getByTestId("record-trade-btn").first();
    await expect(recordBtn).toBeVisible();

    // Record with capital for each leg (F4.4/F4.5).
    await recordBtn.click();
    await expect(page.getByTestId("record-modal")).toBeVisible();
    await page.getByTestId("capital-leg1").fill("150");
    await page.getByTestId("capital-leg2").fill("150");
    await page.getByTestId("record-confirm").click();

    // The trade appears in the separate Manual Trades section as OPEN (F4.6).
    const row = page.getByTestId("manual-row").first();
    await expect(row).toBeVisible({ timeout: 10_000 });
    await expect(row.getByTestId("manual-status")).toHaveText("OPEN");
    await expect(row.getByTestId("manual-pnl")).toHaveText("—");

    // Mark closed with exit prices → P&L computed, status CLOSED (F4.7).
    await row.getByTestId("close-trade-btn").click();
    await expect(page.getByTestId("close-modal")).toBeVisible();
    await page.getByTestId("exit-leg1").fill("999");
    await page.getByTestId("exit-leg2").fill("1");
    await page.getByTestId("close-confirm").click();

    const closedRow = page.getByTestId("manual-row").first();
    await expect(closedRow.getByTestId("manual-status")).toHaveText("CLOSED", {
      timeout: 10_000,
    });
    // P&L is now a number, not the em-dash placeholder.
    await expect(closedRow.getByTestId("manual-pnl")).not.toHaveText("—");
  });
});
