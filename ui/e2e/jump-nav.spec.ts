import { test, expect, Page } from "@playwright/test";
import { resetDemoStateVia } from "./helpers/reset";

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
// Every test starts from a known backend state. The FastAPI process holds global
// config (data source, signal thresholds, scan state) and the database keeps every
// row an earlier test created, so without this a test's result depends on what ran
// before it — which is exactly why this suite used to fail a different set of tests
// on every run. See e2e/helpers/reset.ts.
test.beforeEach(async () => {
  await resetDemoStateVia();
});

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

  // Regression: the real page grows AFTER mount as data loads (the live scan
  // fills the pairs table with hundreds of rows). On a full-height window the
  // page is short at mount — not scrollable — and content arriving later never
  // fires a scroll/resize event. The FAB must still appear once the page
  // becomes scrollable (ResizeObserver on <body>), or it stays hidden forever
  // on exactly the data-heavy pages that need it most.
  test("FAB appears when the page grows scrollable after mount", async ({
    page,
  }) => {
    // Tall viewport so the demo page fits with no scrollbar → FAB hidden.
    await page.setViewportSize({ width: 1280, height: 1000 });
    await login(page);
    await ensurePairs(page);
    await waitForStableHeight(page);

    const fab = page.getByTestId("jump-nav-btn");
    await expect(fab).toHaveCount(0); // page fits → nothing to jump to

    // Grow the page past the fold WITHOUT a scroll/resize event (mimics rows
    // streaming in). Only the body-size observer can notice this.
    await page.evaluate(() => {
      const spacer = document.createElement("div");
      spacer.style.height = "2000px";
      spacer.setAttribute("data-testid", "test-spacer");
      document.body.appendChild(spacer);
    });

    await expect(fab).toBeVisible({ timeout: 5_000 });
    await expect(fab).toHaveAttribute("data-direction", "down");
  });
});
