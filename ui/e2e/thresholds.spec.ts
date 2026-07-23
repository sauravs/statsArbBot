import { test, expect, Page } from "@playwright/test";
import { resetDemoStateVia } from "./helpers/reset";

// UI-configurable Option-B Z thresholds (issue #74): edit entry/exit/stop on the
// dashboard → applied app-wide → the pair-detail Z chart reflects them.

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
  const rows = page.getByTestId("pair-row");
  if ((await rows.count()) === 0) {
    await page.getByTestId("scan-full").click();
    await expect(rows.first()).toBeVisible({ timeout: 20_000 });
  }
}

async function setThresholds(
  page: Page,
  entry: string,
  exit: string,
  stop: string,
) {
  await page.getByTestId("threshold-edit").click();
  await page.getByTestId("threshold-entry").fill(entry);
  await page.getByTestId("threshold-exit").fill(exit);
  await page.getByTestId("threshold-stop").fill(stop);
  await page.getByTestId("threshold-apply").click();
}

// Every test starts from a known backend state. The FastAPI process holds global
// config (data source, signal thresholds, scan state) and the database keeps every
// row an earlier test created, so without this a test's result depends on what ran
// before it — which is exactly why this suite used to fail a different set of tests
// on every run. See e2e/helpers/reset.ts.
test.beforeEach(async () => {
  await resetDemoStateVia();
});

test.describe("Manual Trading — configurable Z thresholds (#74)", () => {
  // Restore defaults after each test so the runtime change doesn't leak into the
  // shared API process. Done via the proxy (the page carries the session cookie)
  // rather than the UI, so it can't race the badge's initial load.
  test.afterEach(async ({ page }) => {
    await page.request
      .post("/api/proxy/api/system/thresholds", {
        data: { entry: 1.5, exit: 0.5, stop: 4 },
      })
      .catch(() => {});
  });

  test("edit thresholds on the dashboard → chart reflects them", async ({
    page,
  }) => {
    await login(page);
    await ensurePairs(page);

    // Establish a known baseline — the shared API process may carry a persisted
    // value from earlier operator/test activity (the #74 persistence feature).
    await page.request.post("/api/proxy/api/system/thresholds", {
      data: { entry: 1.5, exit: 0.5, stop: 4 },
    });
    await page.reload();
    await expect(page.getByTestId("strategy-thresholds-badge")).toHaveText(
      "entry ±1.5 · exit ±0.5 · stop ±4",
    );

    await setThresholds(page, "2", "0.4", "5");

    // Badge updates (edit form closed → back to the static badge).
    await expect(page.getByTestId("strategy-thresholds-badge")).toHaveText(
      "entry ±2 · exit ±0.4 · stop ±5",
    );

    // The pair-detail Z panel now draws the new threshold values.
    await page.getByTestId("pair-link").first().click();
    await expect(page).toHaveURL(/\/dashboard\/pair\/.+\/.+$/);
    await expect(page.getByTestId("pair-charts")).toBeVisible({ timeout: 15_000 });
    const zPanel = page.getByTestId("chart-zscore").locator("..");
    await expect(zPanel).toHaveText(/entry ±2 · exit ±0\.4 · stop ±5/);

    // Restore defaults via the dashboard for the afterEach hook.
    await page.getByTestId("back-to-dashboard").click();
    await expect(page).toHaveURL(/\/dashboard$/);
  });

  test("rejects an out-of-order set client-side (exit ≥ entry)", async ({
    page,
  }) => {
    await login(page);

    // Capture the badge before editing so the assertion is leak-proof regardless
    // of any prior test's (restored) state. Wait for it to have LOADED first — it
    // renders "…" until the thresholds arrive, and capturing that placeholder made
    // the final comparison fail against the real values a moment later.
    const badge = page.getByTestId("strategy-thresholds-badge");
    await expect(badge).toHaveText(/entry ±/);
    const before = await badge.textContent();

    await page.getByTestId("threshold-edit").click();
    await page.getByTestId("threshold-entry").fill("1");
    await page.getByTestId("threshold-exit").fill("1.5");
    await page.getByTestId("threshold-stop").fill("4");
    await page.getByTestId("threshold-apply").click();

    await expect(page.getByTestId("threshold-error")).toBeVisible();
    // No change applied — badge is unchanged from before the rejected edit.
    await page.getByRole("button", { name: "Cancel" }).click();
    await expect(badge).toHaveText(before ?? "");
  });
});
