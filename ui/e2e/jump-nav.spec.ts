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

// The dashboard grows asynchronously after load (live prices, portfolio card),
// which shifts the page height. Wait until the height stops changing so a jump
// lands on a stable layout rather than chasing a moving section.
async function waitForStableHeight(page: Page) {
  let last = -1;
  for (let i = 0; i < 20; i++) {
    const h = await page.evaluate(
      () => document.documentElement.scrollHeight,
    );
    if (h === last) return;
    last = h;
    await page.waitForTimeout(250);
  }
}

// Feature #: as the Cointegrated Pairs table grows, the "Manual Trades" section
// is pushed far down. A bidirectional floating jump button lets the operator
// hop straight to Manual Trades and back to the top without dragging the
// scrollbar the whole way.
test.describe("Manual Trading — jump-to-section FAB", () => {
  test("FAB jumps down to Manual Trades then back to the top", async ({
    page,
  }) => {
    // A short viewport guarantees the page is taller than the fold so the jump
    // is meaningful (demo pairs table + panels overflow 600px easily).
    await page.setViewportSize({ width: 1280, height: 600 });

    await login(page);
    await ensurePairs(page);
    await waitForStableHeight(page);

    const fab = page.getByTestId("jump-nav-btn");
    const pairsTable = page.getByTestId("pairs-table");
    // Distance from the Manual Trades section's top to the top of the viewport.
    // Large = still below the fold; small = we've scrolled up to it.
    const manualOffset = () =>
      page
        .getByTestId("manual-trades-section")
        .evaluate((el) => el.getBoundingClientRect().top);
    const scrollY = () => page.evaluate(() => window.scrollY);

    // At the top of the page the button offers to jump DOWN to Manual Trades:
    // we're unscrolled and the section sits well below the top of the viewport.
    await expect(fab).toBeVisible();
    await expect(fab).toHaveAttribute("data-direction", "down");
    expect(await scrollY()).toBeLessThan(50);
    const offsetAtTop = await manualOffset();
    expect(offsetAtTop).toBeGreaterThan(150);

    // Click → the page scrolls down to the Manual Trades section (the page is
    // short in the demo dataset, so it scrolls to the bottom), the section moves
    // up into view, and the button flips to a "back to top" affordance.
    await fab.click();
    await expect(fab).toHaveAttribute("data-direction", "up", { timeout: 5_000 });
    await expect.poll(scrollY).toBeGreaterThan(80); // scrolled down meaningfully
    // The section has moved up toward the top of the viewport.
    expect(await manualOffset()).toBeLessThan(offsetAtTop - 80);

    // Click again → we return to the top, where the pairs table is in view.
    await fab.click();
    await expect(fab).toHaveAttribute("data-direction", "down", {
      timeout: 5_000,
    });
    await expect(pairsTable).toBeInViewport();
    await expect.poll(scrollY).toBeLessThan(50);
  });
});
