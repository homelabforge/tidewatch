import { test, expect } from '@playwright/test';
import { toast } from './helpers/selectors';

test.describe('Settings', () => {
  test('loads settings page with all tabs', async ({ page }) => {
    await page.goto('/settings');
    await expect(page.getByRole('button', { name: /System/i })).toBeVisible({ timeout: 15000 });

    // All 6 settings tabs should be visible
    await expect(page.getByRole('button', { name: /System/i })).toBeVisible({ timeout: 10000 });
    await expect(page.getByRole('button', { name: /^Updates$/i })).toBeVisible();
    await expect(page.getByRole('button', { name: /Docker/i })).toBeVisible();
    await expect(page.getByRole('button', { name: /Integrations/i })).toBeVisible();
    await expect(page.getByRole('button', { name: /Notifications/i })).toBeVisible();
    await expect(page.getByRole('button', { name: /Backup/i })).toBeVisible();
  });

  test('can switch between settings tabs', async ({ page }) => {
    await page.goto('/settings');
    await expect(page.getByRole('button', { name: /System/i })).toBeVisible({ timeout: 15000 });

    // Wait for initial tab to load
    await expect(page.getByRole('button', { name: /System/i })).toBeVisible({ timeout: 10000 });

    // Click Notifications tab
    await page.getByRole('button', { name: /Notifications/i }).click();
    await expect(
      page.getByText(/ntfy|discord|slack|telegram|email|notification/i).first()
    ).toBeVisible({ timeout: 5000 });

    // Click Docker tab
    await page.getByRole('button', { name: /Docker/i }).click();
    await expect(
      page.getByText(/docker|socket|registry/i).first()
    ).toBeVisible({ timeout: 5000 });

    // Should not show error toast during tab switches
    await expect(toast.error(page)).not.toBeVisible({ timeout: 1000 });
  });
});
