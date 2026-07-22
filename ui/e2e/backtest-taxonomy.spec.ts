import { test as base, expect, Locator, Page } from "@playwright/test";
import { resetDemoStateVia } from "./helpers/reset";

// Strategy-list taxonomy UX (PRs #217 / #218), driven through the real app against
// the offline demo data. The point of this screen is that a run's net P&L can never
// again be read without the two qualifiers that decide whether it means anything —
// so these tests assert the QUALIFIERS, not the arithmetic: that a zero-cost
// counterfactual is unmistakable, that an in-sample run cannot pass for a validated
// one, and that the controls expressing all that actually respond.
//
// Fixtures are created through the create form (costs and span are real inputs), so
// classification is exercised end-to-end — form → API → DB → list → detail — rather
// than against a hand-built object.
//
// The suite is serial and each file resets the backend first, but these specs still
// scope every assertion to a row they own and never assert a global count: the demo
// list is shared state, and a test that only passes because the database happened to
// be empty is exactly the kind this suite had too many of.

const PASSCODE = process.env.DASHBOARD_PASSWORD ?? "123456";

// Distinct per worker process, so a previous run that died before cleanup cannot
// collide with this one.
const RUN = Math.random().toString(36).slice(2, 7);

type Fixtures = {
  /** Unique suffix for this test's strategies. */
  tag: string;
  names: { oos: string; free: string; tuned: string };
};

const test = base.extend<Fixtures>({
  tag: async ({}, use, testInfo) => {
    await use(`e2etax-${RUN}-${testInfo.testId.slice(-6)}`);
  },
  names: async ({ tag }, use) => {
    // The name PREFIX drives family classification, so it has to survive tagging.
    await use({
      oos: `reval-3.5-s2-${tag}`,
      free: `cost-000-s2-${tag}`,
      tuned: `entry-sweep-3.5-${tag}`,
    });
  },
});

// s2 (out-of-sample) and s1 (the designated in-sample window), in the format a
// datetime-local input accepts.
const S2 = { start: "2025-11-07T00:00", end: "2026-03-01T00:00" };
const S1 = { start: "2026-03-01T16:09", end: "2026-06-23T16:10" };

const MODELLED_COST = "0.05";

async function login(page: Page) {
  await page.goto("/login");
  const inputs = page.locator('input[inputmode="numeric"]');
  for (let i = 0; i < 6; i++) await inputs.nth(i).fill(PASSCODE[i]);
  await expect(page).toHaveURL(/\/dashboard$/);
}

async function createStrategy(
  page: Page,
  opts: { name: string; entryZ: string; span: { start: string; end: string }; zeroCost?: boolean },
) {
  await page.getByTestId("strategy-name").fill(opts.name);
  await page.getByTestId("strategy-entry-z").fill(opts.entryZ);
  await page.getByTestId("strategy-exit-z").fill("0.5");
  await page.getByTestId("strategy-scan-days").fill("7");
  await page.getByTestId("strategy-trade-days").fill("3");
  await page.getByTestId("strategy-start").fill(opts.span.start);
  await page.getByTestId("strategy-end").fill(opts.span.end);

  // Costs are set on EVERY create, never only for the zero-cost case: the form
  // resets just the name after a submit, so a previous zero-cost run would
  // otherwise leak into the next strategy and quietly invalidate the assertions.
  const panel = page.getByTestId("strategy-advanced-panel");
  if (!(await panel.isVisible())) await page.getByTestId("strategy-advanced-toggle").click();
  const cost = opts.zeroCost ? "0" : MODELLED_COST;
  await page.getByTestId("strategy-slippage").fill(cost);
  await page.getByTestId("strategy-taker-fee").fill(cost);

  await page.getByTestId("create-strategy-btn").click();

  // Assert the row landed in the LIST rather than waiting on the detail panel: a
  // rejected create leaves the previous strategy selected, and that one is PENDING
  // too — so a status-badge check would pass while nothing had been created.
  await expect(page.getByTestId("create-strategy-error")).toHaveCount(0);
  await expect(row(page, opts.name)).toBeVisible();
}

/** The list row for a strategy, by exact name. */
function row(page: Page, name: string): Locator {
  return page.getByTestId("strategy-row").filter({ hasText: name });
}

async function filterToFamily(page: Page, label: string) {
  await page.getByTestId("family-filter-select").selectOption({ label });
}

// Every test starts from a known backend state. The FastAPI process holds global
// config (data source, signal thresholds, scan state) and the database keeps every
// row an earlier test created, so without this a test's result depends on what ran
// before it — which is exactly why this suite used to fail a different set of tests
// on every run. See e2e/helpers/reset.ts.
test.beforeEach(async () => {
  await resetDemoStateVia();
});

test.describe("Backtest strategy taxonomy", () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
    await page.getByTestId("nav-backtest").click();
    await expect(page).toHaveURL(/\/dashboard\/backtest$/);
    await expect(page.getByTestId("create-strategy-form")).toBeVisible();
  });

  // Delete only this test's own rows, through the same authenticated proxy the app
  // uses, so a full-suite run leaves the demo list as it found it.
  test.afterEach(async ({ page, tag }) => {
    const res = await page.request.get("/api/proxy/api/backtest/strategies");
    if (!res.ok()) return;
    const { strategies } = (await res.json()) as { strategies: { id: string; name: string }[] };
    for (const s of strategies.filter((x) => x.name.includes(tag))) {
      await page.request.delete(`/api/proxy/api/backtest/strategies/${s.id}`);
    }
  });

  test("safety badges come from config: zero-cost and in-sample runs are unmistakable", async ({
    page,
    names,
  }) => {
    await createStrategy(page, { name: names.oos, entryZ: "3.5", span: S2 });
    await createStrategy(page, { name: names.free, entryZ: "3.5", span: S2, zeroCost: true });
    await createStrategy(page, { name: names.tuned, entryZ: "3.5", span: S1 });

    // A realistic run on an unseen span: out-of-sample, and no cost warning at all.
    const oos = row(page, names.oos);
    await expect(oos).toBeVisible();
    await expect(oos.getByTestId("badge-span")).toContainText("OUT-OF-SAMPLE");
    await expect(oos.getByTestId("badge-span")).toContainText("s2");
    await expect(oos.getByTestId("badge-cost")).toHaveCount(0);

    // The counterfactual: same span, same name shape, but the FORM zeroed its costs.
    // It must carry the loud badge — and must not be hidden.
    const free = row(page, names.free);
    await expect(free).toBeVisible();
    await expect(free.getByTestId("badge-cost")).toContainText("NO-COST");

    // The tuning window must never read as a validated result.
    const tuned = row(page, names.tuned);
    await expect(tuned.getByTestId("badge-span")).toContainText("IN-SAMPLE");
    await expect(tuned.getByTestId("badge-span")).not.toContainText("OUT-OF-SAMPLE");
    // ...and it is genuinely at modelled cost, proving the badge above is a span
    // verdict rather than a cost one leaking through.
    await expect(tuned.getByTestId("badge-cost")).toHaveCount(0);
  });

  test("families group by experiment, and the row tooltip explains the run without opening it", async ({
    page,
    names,
  }) => {
    await createStrategy(page, { name: names.oos, entryZ: "3.5", span: S2 });
    await createStrategy(page, { name: names.free, entryZ: "3.5", span: S2, zeroCost: true });

    // Grouping is the default view — no control needs touching to get here.
    await expect(page.getByTestId("group-mode-select")).toHaveValue("family");
    const headers = page.getByTestId("strategy-group-header");
    await expect(headers.filter({ hasText: "Multi-span re-validation" })).toBeVisible();
    await expect(headers.filter({ hasText: "Cost decomposition" })).toBeVisible();

    // Collapsing a family hides its rows; re-expanding brings them back.
    const revalHeader = headers.filter({ hasText: "Multi-span re-validation" });
    await revalHeader.click();
    await expect(row(page, names.oos)).toHaveCount(0);
    await revalHeader.click();
    await expect(row(page, names.oos)).toBeVisible();

    // Every row carries the full name, a description and the key config, so the
    // operator never has to open a strategy just to learn what it is.
    const tip = await row(page, names.oos).getAttribute("title");
    expect(tip).toContain(names.oos); // full name, untruncated
    expect(tip).toContain("Multi-span re-validation");
    expect(tip).toContain("Entry |Z|≥3.5");
    expect(tip).toContain("0.05% fee + 0.05% slippage");

    // ...and the counterfactual's tooltip states the zeroed costs outright.
    expect(await row(page, names.free).getAttribute("title")).toContain(
      "0% fee + 0% slippage",
    );
  });

  test("'realistic runs only' keeps the tradeable unseen run and drops the rest", async ({
    page,
    names,
  }) => {
    await createStrategy(page, { name: names.oos, entryZ: "3.5", span: S2 });
    await createStrategy(page, { name: names.free, entryZ: "3.5", span: S2, zeroCost: true });
    await createStrategy(page, { name: names.tuned, entryZ: "3.5", span: S1 });

    // Off by default: a counterfactual is visible, not hidden.
    const toggle = page.getByTestId("realistic-only-toggle").locator("input");
    await expect(toggle).not.toBeChecked();
    await expect(row(page, names.free)).toBeVisible();

    await toggle.check();

    // Only the tradeable, never-seen-before run survives.
    await expect(row(page, names.oos)).toBeVisible();
    await expect(row(page, names.free)).toHaveCount(0); // untradeable costs
    await expect(row(page, names.tuned)).toHaveCount(0); // measured on the tuning window

    await toggle.uncheck();
    await expect(row(page, names.free)).toBeVisible();
  });

  // Regression for #218: selecting a sort did nothing an operator could see — rows
  // moved only WITHIN a family, the families kept their fixed order, and with the
  // families collapsed nothing moved at all.
  test("sorting reorders what is on screen, and reopens collapsed families", async ({
    page,
    names,
  }) => {
    await createStrategy(page, { name: names.oos, entryZ: "3.5", span: S2 });
    await createStrategy(page, { name: names.free, entryZ: "3.5", span: S2, zeroCost: true });

    // Ranking by net P&L is available but deliberately not the default.
    await expect(page.getByTestId("sort-select")).toHaveValue("default");

    // Collapse everything — the state the bug was reported from.
    await page.getByTestId("expand-all-btn").click();
    await expect(page.getByTestId("strategy-row")).toHaveCount(0);

    // Asking for an order must put rows back on screen.
    await page.getByTestId("sort-select").selectOption("pnl");
    await expect(row(page, names.oos)).toBeVisible();
    await expect(row(page, names.free)).toBeVisible();

    // And the expand/collapse control still round-trips afterwards.
    await page.getByTestId("expand-all-btn").click();
    await expect(page.getByTestId("strategy-row")).toHaveCount(0);
    await page.getByTestId("expand-all-btn").click();
    await expect(row(page, names.oos)).toBeVisible();
  });

  test("family and cost filters narrow the list", async ({ page, names }) => {
    await createStrategy(page, { name: names.oos, entryZ: "3.5", span: S2 });
    await createStrategy(page, { name: names.free, entryZ: "3.5", span: S2, zeroCost: true });

    await filterToFamily(page, "Cost decomposition");
    await expect(row(page, names.free)).toBeVisible();
    await expect(row(page, names.oos)).toHaveCount(0);

    await filterToFamily(page, "All families");
    await page.getByTestId("cost-filter-select").selectOption("tradeable");
    await expect(row(page, names.oos)).toBeVisible();
    await expect(row(page, names.free)).toHaveCount(0);

    await page.getByTestId("cost-filter-select").selectOption("diagnostic");
    await expect(row(page, names.free)).toBeVisible();
    await expect(row(page, names.oos)).toHaveCount(0);
  });

  test("detail panel names the category and explains the run", async ({ page, names }) => {
    await createStrategy(page, { name: names.free, entryZ: "3.5", span: S2, zeroCost: true });
    await row(page, names.free).click();

    const detail = page.getByTestId("strategy-detail");
    await expect(detail).toBeVisible();

    // Category sits alongside the existing headline stats.
    await expect(detail.getByTestId("bt-category")).toHaveText("Cost decomposition");
    await expect(detail.getByTestId("bt-net-pnl")).toBeVisible();

    // The same loud badge as the list — a counterfactual is unmistakable wherever
    // it is looked at.
    // Case-insensitive: the badge is uppercased by CSS, so the DOM text is not.
    await expect(detail.getByTestId("badge-cost")).toContainText(/not tradeable/i);

    // The description section explains the family and this specific run.
    const about = page.getByTestId("bt-about");
    await expect(about).toContainText("What this tests");
    await expect(about).toContainText("What it means");
    await expect(about).toContainText("This run specifically");
    await expect(about).toContainText("fees and slippage set to 0");
    // Untradeable runs get an explicit warning, not just a badge.
    await expect(about).toContainText("not a forecast of your money");

    // A realistic out-of-sample run gets its own category and no such warning.
    await createStrategy(page, { name: names.oos, entryZ: "3.5", span: S2 });
    await row(page, names.oos).click();
    await expect(detail.getByTestId("bt-category")).toHaveText("Multi-span re-validation");
    await expect(page.getByTestId("bt-about")).not.toContainText(
      "not a forecast of your money",
    );
  });
});
