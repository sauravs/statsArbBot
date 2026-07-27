import { test, expect, Page } from "@playwright/test";
import { resetDemoStateVia } from "./helpers/reset";

const PASSCODE = process.env.DASHBOARD_PASSWORD ?? "123456";

// Backend config default (backend/config.py MIN_LIQUIDITY_USD).
const DEFAULT_FLOOR = 1_000_000;

async function login(page: Page) {
  await page.goto("/login");
  const inputs = page.locator('input[inputmode="numeric"]');
  for (let i = 0; i < 6; i++) await inputs.nth(i).fill(PASSCODE[i]);
  await expect(page).toHaveURL(/\/dashboard$/);
}

test.beforeEach(async () => {
  await resetDemoStateVia();
});

test.describe("Scan floor — runtime control (WS1)", () => {
  // The control mutates the shared api process's global MIN_LIQUIDITY_USD, so
  // ALWAYS restore the default or later specs run against an unexpected floor.
  test.afterEach(async ({ page }) => {
    await page.request
      .post("/api/proxy/api/system/scan-floor", {
        data: { min_liquidity_usd: DEFAULT_FLOOR },
        headers: { "Content-Type": "application/json" },
      })
      .catch(() => {});
  });

  test("sets the floor from a preset and via the input (no restart)", async ({
    page,
  }) => {
    await login(page);

    const badge = page.getByTestId("scan-floor-badge");
    await expect(badge).toHaveText("$1M");

    // Preset: click $5M.
    await page
      .getByTestId("scan-floor-presets")
      .getByRole("button", { name: "$5M" })
      .click();
    await expect(badge).toHaveText("$5M");

    // Preset: Off (0 = no floor).
    await page
      .getByTestId("scan-floor-presets")
      .getByRole("button", { name: "Off" })
      .click();
    await expect(badge).toHaveText("Off");

    // Free input + Apply: a custom value.
    const input = page.getByTestId("scan-floor-input");
    await input.fill("2000000");
    await page.getByTestId("scan-floor-apply").click();
    await expect(badge).toHaveText("$2M");

    // The framing note is present (tractability, not alpha).
    await expect(page.getByTestId("scan-floor-control").getByTestId("info-tip")).toBeVisible();
  });

  test("rejects a negative floor (422) and surfaces the error", async ({ page }) => {
    await login(page);
    const input = page.getByTestId("scan-floor-input");
    await input.fill("-5");
    await page.getByTestId("scan-floor-apply").click();
    await expect(page.getByTestId("scan-floor-error")).toBeVisible();
    // Badge unchanged — the bad value never took effect.
    await expect(page.getByTestId("scan-floor-badge")).toHaveText("$1M");
  });
});
