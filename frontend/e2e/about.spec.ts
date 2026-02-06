import { test, expect } from '@playwright/test';

test.describe('About', () => {
  test('displays version and project information', async ({ page }) => {
    await page.goto('/about');

    // About page should show TideWatch info
    await expect(
      page.getByText(/tidewatch/i).first()
    ).toBeVisible({ timeout: 10000 });

    // Should show version number
    await expect(
      page.getByText(/\d+\.\d+\.\d+/).first()
    ).toBeVisible({ timeout: 5000 });
  });
});
