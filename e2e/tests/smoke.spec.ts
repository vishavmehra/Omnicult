import { expect, test } from "@playwright/test";

test("the landing page renders and names the product", async ({ page }) => {
  const response = await page.goto("/");
  expect(response?.ok()).toBeTruthy();
  await expect(page).toHaveTitle(/Omnicult/);
});

test("the sign-in page is reachable", async ({ page }) => {
  const response = await page.goto("/login");
  expect(response?.ok()).toBeTruthy();
  await expect(page).toHaveTitle(/Omnicult/);
});
