import { test, expect } from "@playwright/test";

const PASSCODE = process.env.DASHBOARD_PASSWORD ?? "123456";

test.describe("Phase 0 smoke", () => {
  test("unauthenticated visit redirects to login", async ({ page }) => {
    await page.goto("/dashboard");
    await expect(page).toHaveURL(/\/login$/);
    await expect(
      page.getByRole("heading", { name: "statsArbBot" }),
    ).toBeVisible();
  });

  test("wrong passcode is rejected", async ({ page }) => {
    await page.goto("/login");
    const inputs = page.locator('input[inputmode="numeric"]');
    const wrong = "000000";
    for (let i = 0; i < 6; i++) {
      await inputs.nth(i).fill(wrong[i]);
    }
    await expect(page.getByText(/Incorrect passcode/i)).toBeVisible();
    await expect(page).toHaveURL(/\/login$/);
  });

  test("correct passcode logs in and lands on the dashboard", async ({
    page,
  }) => {
    await page.goto("/login");
    const inputs = page.locator('input[inputmode="numeric"]');
    for (let i = 0; i < 6; i++) {
      await inputs.nth(i).fill(PASSCODE[i]);
    }
    await expect(page).toHaveURL(/\/dashboard$/);
    await expect(
      page.getByRole("heading", { name: "Manual Trading" }),
    ).toBeVisible();
  });
});
