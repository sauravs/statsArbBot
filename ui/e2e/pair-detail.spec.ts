import { test, expect, Page } from "@playwright/test";
import { resetDemoStateVia } from "./helpers/reset";

const PASSCODE = process.env.DASHBOARD_PASSWORD ?? "123456";

async function login(page: Page) {
  await page.goto("/login");
  const inputs = page.locator('input[inputmode="numeric"]');
  for (let i = 0; i < 6; i++) {
    await inputs.nth(i).fill(PASSCODE[i]);
  }
  await expect(page).toHaveURL(/\/dashboard$/);
}

async function ensurePairs(page: Page) {
  // Run a scan (fake data source → DEMO pairs) if the table is empty.
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

test.describe("Phase 3 — pair detail + 3-panel charts", () => {
  test("click a pair → detail route renders all three chart panels", async ({
    page,
  }) => {
    await login(page);
    await ensurePairs(page);

    // Navigate into the first pair's detail view.
    const firstLink = page.getByTestId("pair-link").first();
    const label = (await firstLink.innerText()).trim();
    await firstLink.click();

    await expect(page).toHaveURL(/\/dashboard\/pair\/.+\/.+$/);

    // All three panels render (no error / loading state lingering).
    await expect(page.getByTestId("pair-charts")).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByTestId("pair-charts-error")).toHaveCount(0);

    for (const id of [
      "chart-normalized",
      "chart-raw",
      "chart-spread",
      "chart-zscore",
    ]) {
      const panel = page.getByTestId(id);
      await expect(panel).toBeVisible();
      // lightweight-charts renders into a <canvas> inside the panel.
      await expect(panel.locator("canvas").first()).toBeVisible();
    }

    // The threshold legend (Option-B defaults) is shown on the Z-score panel.
    await expect(page.getByText(/entry ±1\.5/)).toBeVisible();
    await expect(page.getByText(/stop ±4/)).toBeVisible();

    // Back to the dashboard.
    await page.getByTestId("back-to-dashboard").click();
    await expect(page).toHaveURL(/\/dashboard$/);
    expect(label.length).toBeGreaterThan(0);
  });

  test("each panel header shows a Y-value readout that tracks the crosshair (#73)", async ({
    page,
  }) => {
    await login(page);
    await ensurePairs(page);

    await page.getByTestId("pair-link").first().click();
    await expect(page).toHaveURL(/\/dashboard\/pair\/.+\/.+$/);
    await expect(page.getByTestId("pair-charts")).toBeVisible({ timeout: 15_000 });

    // Not hovering → each panel header carries its latest value (a number).
    const spreadPanel = page.getByTestId("chart-spread").locator("..");
    const zPanel = page.getByTestId("chart-zscore").locator("..");
    await expect(spreadPanel).toHaveText(/spread\s+-?\d/);
    await expect(zPanel).toHaveText(/Z\s+-?\d/);

    // Hover the spread canvas → the readout still resolves to a number (the
    // crosshair handler ran without clearing the legend to "—").
    const canvas = page.getByTestId("chart-spread").locator("canvas").first();
    const box = await canvas.boundingBox();
    if (box) {
      await page.mouse.move(box.x + box.width * 0.5, box.y + box.height * 0.5);
    }
    await expect(spreadPanel).toHaveText(/spread\s+-?\d/);
  });
});
