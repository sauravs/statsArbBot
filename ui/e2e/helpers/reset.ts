import { APIRequestContext, expect, request as playwrightRequest } from "@playwright/test";

// Shared backend state is what made this suite unreliable. Every spec passed when
// run alone and failed after other specs had run, because the FastAPI process holds
// process-global config (data source, signal thresholds, scan state) and the
// database keeps every manual trade / strategy a previous spec created. Tests that
// assert "the list empties" or "the page is short enough that no jump button is
// needed" are assertions about the whole backend, not about the feature.
//
// So each spec file starts from a known state instead of from whatever the previous
// file left behind.
//
// SAFETY: this can only ever delete DEMO data. Setting the source to "fake" is the
// first thing it does, and both the manual-trade and strategy lists are scoped by
// the active data source server-side (`config.SCAN_DATA_SOURCE`) — so the
// list-then-delete below is structurally incapable of seeing, let alone removing, a
// dydx or hyperliquid row. It is also refused outright unless the switch back to
// demo succeeded.

const PASSCODE = process.env.DASHBOARD_PASSWORD ?? "123456";

/** Backend defaults from backend/config.py — what a fresh process starts with. */
export const DEFAULT_THRESHOLDS = { entry: 1.5, exit: 0.5, stop: 4.0 };

/** An API context carrying a valid dashboard session cookie. */
export async function authedRequest(baseURL: string): Promise<APIRequestContext> {
  const ctx = await playwrightRequest.newContext({ baseURL });
  const res = await ctx.post("/api/auth/login", { data: { password: PASSCODE } });
  expect(
    res.ok(),
    `e2e reset could not authenticate (${res.status()}). Is DASHBOARD_PASSWORD set correctly?`,
  ).toBeTruthy();
  return ctx;
}

async function deleteAll(
  api: APIRequestContext,
  listPath: string,
  pick: (body: any) => { id: string }[],
  deletePath: (id: string) => string,
) {
  const res = await api.get(listPath);
  if (!res.ok()) return;
  const rows = pick(await res.json()) ?? [];
  for (const r of rows) await api.delete(deletePath(r.id));
}

/**
 * Return the backend to a known, empty demo state.
 *
 * Deliberately ordered: demo mode first (so everything below is demo-scoped), then
 * release anything holding state open, then clear rows, then restore config.
 */
export async function resetDemoState(api: APIRequestContext): Promise<void> {
  const setSource = (source: string) =>
    api.post("/api/proxy/api/system/data-source", {
      data: { source },
      headers: { "Content-Type": "application/json" },
    });

  // 1. Demo mode FIRST — this is what scopes every list/delete below, and it is the
  //    guarantee that live data can never be touched.
  //
  //    Done as a real transition (away, then back) on purpose: the backend clears
  //    the persisted scan pairs only when the source actually CHANGES, and the
  //    source is usually already "fake", so a plain set would leave a previous
  //    spec's pairs in the table. Neither call performs any network I/O — the
  //    switch is a config assignment plus a local pair-table clear — and the
  //    sequence always ENDS on demo, before anything is read or deleted.
  await setSource("dydx").catch(() => {});
  const src = await setSource("fake");
  expect(
    src.ok(),
    "e2e reset refused to continue: could not switch the backend to demo mode, so " +
      "deleting rows would not be guaranteed demo-scoped.",
  ).toBeTruthy();

  // 2. Stop anything still running. A live session left active by a previous spec
  //    keeps mutating trades underneath the next one.
  // ScopeBody defaults to the same exchange/mode the UI uses; sending it explicitly
  // keeps the call valid (the body is required) and a 4xx here is fine — it just
  // means there was no session to stop.
  await api
    .post("/api/proxy/api/live/session/stop", {
      data: { exchange: "dydx", mode: "forward_test" },
      headers: { "Content-Type": "application/json" },
    })
    .catch(() => {});

  // 3. Clear cached scan results, so a spec that asserts on a fresh scan is not
  //    reading pairs some earlier spec produced.
  await api.post("/api/proxy/api/scan/reset").catch(() => {});

  // 4. Drop demo rows. Both lists are data-source-scoped server-side.
  await deleteAll(
    api,
    "/api/proxy/api/manual",
    (b) => b.trades ?? b ?? [],
    (id) => `/api/proxy/api/manual/${id}`,
  );
  await deleteAll(
    api,
    "/api/proxy/api/backtest/strategies",
    (b) => b.strategies ?? [],
    (id) => `/api/proxy/api/backtest/strategies/${id}`,
  );

  // 5. Restore the app-wide signal thresholds. These are process-global and several
  //    specs write them, so a spec reading a chart inherits whatever ran last.
  await api
    .post("/api/proxy/api/system/thresholds", {
      data: DEFAULT_THRESHOLDS,
      headers: { "Content-Type": "application/json" },
    })
    .catch(() => {});
}

/** Convenience for `test.beforeAll` — opens its own authenticated context.
 *  Defaults to the same base URL playwright.config.ts uses, so a spec can call it
 *  with no arguments and no fixture plumbing. */
export async function resetDemoStateVia(
  baseURL: string = process.env.BASE_URL ?? "http://localhost:3000",
): Promise<void> {
  const api = await authedRequest(baseURL);
  try {
    await resetDemoState(api);
  } finally {
    await api.dispose();
  }
}
