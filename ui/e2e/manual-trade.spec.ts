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

// Set a React-controlled numeric input by its testid (native setter + input event).
async function setNativeInput(page: Page, testid: string, value: string) {
  await page.getByTestId(testid).evaluate((el, v) => {
    const input = el as HTMLInputElement;
    const setter = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!;
    setter.call(input, v);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  }, value);
}

// Every test starts from a known backend state. The FastAPI process holds global
// config (data source, signal thresholds, scan state) and the database keeps every
// row an earlier test created, so without this a test's result depends on what ran
// before it — which is exactly why this suite used to fail a different set of tests
// on every run. See e2e/helpers/reset.ts.
test.beforeEach(async () => {
  await resetDemoStateVia();
});

test.describe("Manual Trading — PR-1 UX quick wins (#37)", () => {
  test("header nav, both-leg signal, base/quote header, and Charts affordance", async ({
    page,
  }) => {
    await login(page);
    await ensurePairs(page);

    // Header nav has a "Manual Trading" entry linking home (#37 PR-1), shown
    // active on its own page (#42).
    const navManual = page.getByTestId("nav-manual");
    await expect(navManual).toBeVisible();
    await expect(navManual).toHaveText("Manual Trading");
    await expect(navManual).toHaveAttribute("href", "/dashboard");
    await expect(navManual).toHaveAttribute("aria-current", "page");

    // Header shows the data-source badge (fake mode → "DEMO DATA") (#42).
    const badge = page.getByTestId("data-source-badge");
    await expect(badge).toBeVisible();
    await expect(badge).toHaveText("DEMO DATA");

    // PAIR column header present (base/quote explained via its ⓘ tooltip).
    await expect(
      page.getByTestId("pairs-table").getByText("Pair", { exact: true }),
    ).toBeVisible();

    // Header info-tooltips (#49) are present.
    await expect(page.getByTestId("info-tip").first()).toBeVisible();

    // Each pair row has a chart affordance linking to the 3-panel charts.
    const chartsLink = page.getByTestId("pair-charts-link").first();
    await expect(chartsLink).toBeVisible();
    await expect(chartsLink).toHaveAttribute("href", /\/dashboard\/pair\//);

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

test.describe("Manual Trading — global p-value/half-life triage (#150)", () => {
  test("triage controls narrow the table and reset restores it", async ({
    page,
  }) => {
    await login(page);
    await ensurePairs(page);

    const rows = page.getByTestId("pair-row");
    const before = await rows.count();
    expect(before).toBeGreaterThan(0);

    // Tighten the half-life triage below every demo pair's half-life (~1–6h) →
    // all pairs are filtered out, showing the distinct "filtered" empty state.
    await setNativeInput(page, "triage-halflife", "0.1");
    await expect(page.getByTestId("pairs-empty-filtered")).toBeVisible();
    expect(await rows.count()).toBe(0);

    // Reset to the scan default → the full set returns.
    await setNativeInput(page, "triage-halflife", "72");
    await expect(rows.first()).toBeVisible();
    expect(await rows.count()).toBe(before);
  });

  test("triage p-value seeds the Record popup's entry filter", async ({
    page,
  }) => {
    await login(page);
    await ensurePairs(page);

    // A looser p-value keeps every pair visible (all already ≤0.05 ≤0.10), so
    // this isolates the seeding behaviour from the table filter.
    await setNativeInput(page, "triage-pvalue", "0.1");
    // Reveal a Record button (demo max |Z| ≈ 0.95).
    await setThreshold(page, "0.5");
    const recordBtn = page.getByTestId("record-trade-btn").first();
    await expect(recordBtn).toBeVisible();
    await recordBtn.click();
    await expect(page.getByTestId("record-modal")).toBeVisible();

    // The popup's advanced entry filter is pre-filled from the global triage.
    await page.getByTestId("toggle-entry-filters").click();
    await expect(page.getByTestId("filter-pvalue")).toHaveValue("0.1");
  });
});

test.describe("Manual Trading — recorded p-value/half-life columns (#153)", () => {
  test("a recorded trade shows its fresh at-entry p-value and half-life", async ({
    page,
  }) => {
    await login(page);
    await ensurePairs(page);

    // Record a trade (demo max |Z| ≈ 0.95 → lower the threshold to reveal it).
    await setThreshold(page, "0.5");
    const recordBtn = page.getByTestId("record-trade-btn").first();
    await expect(recordBtn).toBeVisible();
    await recordBtn.click();
    await expect(page.getByTestId("record-modal")).toBeVisible();
    await page.getByTestId("capital-leg1").fill("100");
    await page.getByTestId("capital-leg2").fill("100");
    await page.getByTestId("record-confirm").click();

    // The Manual Trades row shows the fresh, at-entry stats — a number, not "—".
    const row = page.getByTestId("manual-row").first();
    await expect(row).toBeVisible({ timeout: 10_000 });
    await expect(row.getByTestId("manual-halflife")).toHaveText(/\d/);
    await expect(row.getByTestId("manual-pvalue")).toHaveText(/\d/);
  });
});

test.describe("Manual Trading — Delete Record (#55)", () => {
  // Deletes every manual row (covers OPEN and CLOSED — prior tests leave a
  // CLOSED trade), asserting the warning + that each delete drops the count by
  // one. Self-cleaning: it leaves the manual table empty, so later tests start
  // from a known state (the shared E2E DB isn't truncated between tests).
  test("record → delete each row with confirm warning → list empties", async ({
    page,
  }) => {
    await login(page);
    await ensurePairs(page);

    // Ensure at least one OPEN trade exists to delete.
    await setThreshold(page, "0.5");
    await page.getByTestId("record-trade-btn").first().click();
    await expect(page.getByTestId("record-modal")).toBeVisible();
    await page.getByTestId("capital-leg1").fill("100");
    await page.getByTestId("capital-leg2").fill("100");
    await page.getByTestId("record-confirm").click();

    // Wait for the just-recorded OPEN trade to actually render before counting,
    // so a late record-refresh can't re-add a row mid-delete (there are no OPEN
    // trades before this test — prior tests close theirs).
    await expect(
      page.getByTestId("manual-status").filter({ hasText: "OPEN" }).first(),
    ).toBeVisible({ timeout: 10_000 });

    const rows = page.getByTestId("manual-row");
    await expect(rows.first()).toBeVisible({ timeout: 10_000 });

    // Delete rows one at a time until none remain. Each iteration waits for the
    // actual DELETE response so sequential deletes never overlap (an in-flight
    // list refresh from a prior delete could otherwise restore a row).
    let first = true;
    for (let guard = 0; guard < 20; guard++) {
      const count = await rows.count();
      if (count === 0) break;

      await rows.first().getByTestId("delete-trade-btn").click();
      await expect(page.getByTestId("delete-modal")).toBeVisible();
      if (first) {
        // The destructive-action warning is shown before anything is deleted.
        await expect(page.getByTestId("delete-warning")).toContainText(
          "Warning! This will permanently delete the record from the database. Proceed with caution.",
        );
        first = false;
      }
      await Promise.all([
        page.waitForResponse(
          (r) =>
            /\/api\/proxy\/api\/manual\//.test(r.url()) &&
            r.request().method() === "DELETE",
        ),
        page.getByTestId("delete-confirm").click(),
      ]);
      await expect(page.getByTestId("delete-modal")).toBeHidden();
      // The list drops by exactly one.
      await expect(rows).toHaveCount(count - 1, { timeout: 10_000 });
    }

    // The table is now empty (the deleted records are gone permanently).
    await expect(page.getByTestId("manual-empty")).toBeVisible();
  });
});

test.describe("Manual Trading — PR-2 live prices + portfolio (#37)", () => {
  test("pairs table shows current prices; portfolio card summarizes an OPEN trade", async ({
    page,
  }) => {
    await login(page);
    await ensurePairs(page);

    // Pairs table shows a current price for at least one pair (fake data source
    // → prices populate after the scan). Format is "<base> / <quote>".
    const priceCell = page.getByTestId("pair-price").first();
    await expect(priceCell).toBeVisible();
    await expect(priceCell).toHaveText(/\d+\.\d{2}\s*\/\s*\d+\.\d{2}/, {
      timeout: 10_000,
    });

    // Record an OPEN trade ($150 + $150 = $300 allocated).
    await setThreshold(page, "0.5");
    await page.getByTestId("record-trade-btn").first().click();
    await expect(page.getByTestId("record-modal")).toBeVisible();
    await page.getByTestId("capital-leg1").fill("150");
    await page.getByTestId("capital-leg2").fill("150");
    await page.getByTestId("record-confirm").click();
    await expect(page.getByTestId("manual-row").first()).toBeVisible({
      timeout: 10_000,
    });

    // Portfolio summary card reflects the OPEN trade.
    const summary = page.getByTestId("portfolio-summary");
    await expect(summary).toBeVisible();
    await expect(page.getByTestId("portfolio-allocated")).toHaveText("$300.00");
    // One OPEN trade (this test's); closed count may be non-zero from prior tests.
    await expect(page.getByTestId("portfolio-counts")).toHaveText(/^1 \/ \d+$/);
    // Marked to market → a $ figure (or "—" if unpriced), never empty.
    await expect(page.getByTestId("portfolio-unrealized")).toHaveText(
      /^(-?\$\d+\.\d{2}|—)$/,
    );
  });
});

test.describe("Manual Trading — chart link + entry overlay", () => {
  // A recorded trade's row deep-links to the pair charts, carrying its entry
  // context (Z, prices, spread, time) in the URL so the charts can overlay the
  // entry. Self-cleaning: it deletes the trade it records, so the shared E2E DB
  // returns to the baseline the prior tests left.
  test("manual row → charts deep-link renders the 'your entry' overlay", async ({
    page,
  }) => {
    await login(page);
    await ensurePairs(page);

    // Record an OPEN trade to get a Manual Trades row.
    await setThreshold(page, "0.5");
    await page.getByTestId("record-trade-btn").first().click();
    await expect(page.getByTestId("record-modal")).toBeVisible();
    await page.getByTestId("capital-leg1").fill("100");
    await page.getByTestId("capital-leg2").fill("100");
    await page.getByTestId("record-confirm").click();
    // Wait for the modal to close (record succeeded) before reading the list, so
    // the newest row is our trade and no overlay intercepts the link click.
    await expect(page.getByTestId("record-modal")).toBeHidden({ timeout: 10_000 });

    const row = page.getByTestId("manual-row").first();
    await expect(row).toBeVisible({ timeout: 10_000 });

    // The row carries a blue chart deep-link with the entry context in the URL.
    const chartsLink = row.getByTestId("manual-charts-link");
    await expect(chartsLink).toBeVisible();
    const href = await chartsLink.getAttribute("href");
    expect(href).toMatch(/\/dashboard\/pair\/.+\/.+\?.*\bze=/);
    expect(href).toMatch(/\bpb=/);
    expect(href).toMatch(/\bpq=/);

    // Open it → the "Showing your recorded entry" badge + charts render.
    await chartsLink.click();
    await expect(page).toHaveURL(/\/dashboard\/pair\/.+\/.+\?.+/);
    const badge = page.getByTestId("entry-overlay-badge");
    await expect(badge).toBeVisible();
    await expect(badge).toContainText("Showing your recorded entry");
    await expect(page.getByTestId("pair-charts")).toBeVisible({ timeout: 15_000 });

    // The Z panel legend gained the recorded-entry readout (overlay is wired
    // through). The legend renders it as `entry <signed Z>` (PairCharts.tsx), which
    // is what distinguishes it from the always-present threshold readout
    // `entry ±1.5` — so match the signed number, not the word.
    //
    // This previously asserted /your entry/, a string the app has never rendered:
    // the overlay's label has been "entry" since it was introduced (#121). The
    // assertion could not pass, and went unnoticed because e2e did not run in CI.
    const zPanel = page.getByTestId("chart-zscore").locator("..");
    await expect(zPanel).toContainText(/entry\s-?\d+\.\d{2}/);

    // Opening the same pair WITHOUT entry params shows no overlay badge.
    await page.goto(new URL(page.url()).pathname);
    await expect(page.getByTestId("entry-overlay-badge")).toHaveCount(0);

    // Clean up: delete the trade we recorded so the DB returns to baseline.
    await page.getByTestId("back-to-dashboard").click();
    await expect(page).toHaveURL(/\/dashboard$/);
    await page
      .getByTestId("manual-row")
      .first()
      .getByTestId("delete-trade-btn")
      .click();
    await expect(page.getByTestId("delete-modal")).toBeVisible();
    await Promise.all([
      page.waitForResponse(
        (r) =>
          /\/api\/proxy\/api\/manual\//.test(r.url()) &&
          r.request().method() === "DELETE",
      ),
      page.getByTestId("delete-confirm").click(),
    ]);
  });
});
