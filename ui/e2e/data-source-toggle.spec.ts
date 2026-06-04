import { test, expect, Page } from "@playwright/test";

const PASSCODE = process.env.DASHBOARD_PASSWORD ?? "123456";

async function login(page: Page) {
  await page.goto("/login");
  const inputs = page.locator('input[inputmode="numeric"]');
  for (let i = 0; i < 6; i++) await inputs.nth(i).fill(PASSCODE[i]);
  await expect(page).toHaveURL(/\/dashboard$/);
}

test.describe("Manual Trading — data-source toggle (#43)", () => {
  // Safety net: the toggle mutates the shared api process's global source, so
  // ALWAYS restore fake mode regardless of how the test ends, or later specs
  // would run against the live dYdX indexer.
  test.afterEach(async ({ page }) => {
    await page.request
      .post("/api/proxy/api/system/data-source", {
        data: { source: "fake" },
        headers: { "Content-Type": "application/json" },
      })
      .catch(() => {});
  });

  test("switches DEMO ↔ LIVE from the header (no restart)", async ({ page }) => {
    await login(page);

    const badge = page.getByTestId("data-source-badge");
    await expect(badge).toHaveText("DEMO DATA");

    // Switch to live (two-step confirm).
    await page.getByTestId("data-source-toggle").click();
    await page.getByTestId("data-source-confirm").click();
    await expect(badge).toHaveText("LIVE DATA");

    // Switch back to demo.
    await page.getByTestId("data-source-toggle").click();
    await page.getByTestId("data-source-confirm").click();
    await expect(badge).toHaveText("DEMO DATA");
  });
});
