import { test, expect, Page } from "@playwright/test";
import { resetDemoStateVia } from "./helpers/reset";

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

test.describe("Campaigns — launch + monitor (WS3 Slice 3)", () => {
  test("launch a grid campaign → it drives members to DONE, then delete", async ({
    page,
  }) => {
    await login(page);
    await page.getByTestId("nav-backtest").click();
    await expect(page.getByTestId("campaign-panel")).toBeVisible();
    await expect(page.getByTestId("campaign-empty")).toBeVisible();

    // Compose a 1-window × 2-entryZ grid (= 2 members) over the demo history range
    // (2024-01-01 → 2026-06-03), with short scan/trade windows so it runs fast.
    await page.getByTestId("campaign-name").fill("E2E Camp");
    await page.getByTestId("campaign-entry-z").fill("1.0, 1.5");
    await page.getByTestId("campaign-concurrency").fill("2");
    await page.getByTestId("campaign-scan-days").fill("7");
    await page.getByTestId("campaign-trade-days").fill("3");
    await page.getByTestId("campaign-window-start-0").fill("2026-03-01T00:00");
    await page.getByTestId("campaign-window-end-0").fill("2026-05-01T00:00");

    await page.getByTestId("campaign-launch").click();

    // A campaign row appears and drives to DONE (2/2), bounded-concurrency queue.
    const row = page.getByTestId("campaign-row");
    await expect(row).toHaveCount(1);
    await expect(page.getByTestId("campaign-row-name")).toHaveText("E2E Camp");
    await expect(page.getByTestId("campaign-row-status")).toHaveText("DONE", {
      timeout: 45_000,
    });
    await expect(page.getByTestId("campaign-row-progress")).toContainText("2/2 done");

    // Expand → both members COMPLETED.
    await page.getByTestId("campaign-row-name").click();
    const members = page.getByTestId("campaign-member-row");
    await expect(members).toHaveCount(2);
    await expect(members.filter({ hasText: "COMPLETED" })).toHaveCount(2);

    // Delete the campaign → the list empties (runs are detached, not shown here).
    await page.getByTestId("campaign-delete").click();
    await expect(page.getByTestId("campaign-empty")).toBeVisible({ timeout: 10_000 });
  });

  test("rejects a launch with no windows", async ({ page }) => {
    await login(page);
    await page.getByTestId("nav-backtest").click();
    await expect(page.getByTestId("campaign-panel")).toBeVisible();

    await page.getByTestId("campaign-name").fill("No Windows");
    // Leave the window start/end blank.
    await page.getByTestId("campaign-launch").click();
    await expect(page.getByTestId("campaign-error")).toContainText("window");
    await expect(page.getByTestId("campaign-empty")).toBeVisible();
  });
});
