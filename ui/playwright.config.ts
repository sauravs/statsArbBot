import { defineConfig, devices } from "@playwright/test";

const BASE_URL = process.env.BASE_URL ?? "http://localhost:3000";

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  // Deliberately serial. Every test resets the backend to a known demo state in
  // `beforeEach` (e2e/helpers/reset.ts), and there is exactly ONE backend: the
  // FastAPI process holds global config (active data source, signal thresholds,
  // scan state) and a single database. Running files concurrently means one file's
  // reset wipes another's fixtures mid-test, and specs that legitimately toggle the
  // data source flip it under everyone else.
  //
  // This was not a theoretical risk — it was the observed behaviour. Before this,
  // every spec passed alone and the full suite failed a DIFFERENT set of 6-9 tests
  // each run. Determinism is worth more here than the ~60s saved: the whole suite
  // runs in well under two minutes.
  fullyParallel: false,
  workers: 1,
  // One retry in CI absorbs genuine network/timing blips without hiding a real
  // regression (a deterministic failure still fails twice). Locally, none — a flake
  // should be visible while you are working on it.
  retries: process.env.CI ? 1 : 0,
  reporter: "list",
  use: {
    baseURL: BASE_URL,
    trace: "on-first-retry",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
