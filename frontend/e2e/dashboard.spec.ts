import { test, expect } from '@playwright/test';
import { nav, toast } from './helpers/selectors';

test.describe('Dashboard', () => {
  test('loads and displays dashboard content', async ({ page }) => {
    await page.goto('/');
    await expect(nav.dashboard(page)).toBeVisible({ timeout: 15000 });

    // All navigation links should be present
    await expect(nav.updates(page)).toBeVisible();
    await expect(nav.history(page)).toBeVisible();
    await expect(nav.settings(page)).toBeVisible();
    await expect(nav.about(page)).toBeVisible();
  });

  test('sync containers button triggers sync', async ({ page }) => {
    await page.goto('/');
    await expect(nav.dashboard(page)).toBeVisible({ timeout: 15000 });

    const syncButton = page.getByRole('button', { name: /Sync/i });
    if (await syncButton.isVisible({ timeout: 5000 }).catch(() => false)) {
      await syncButton.click();
      // Should show a toast notification
      await expect(toast.any(page)).toBeVisible({ timeout: 15000 });
    }
  });

  test('check updates button initiates check', async ({ page }) => {
    await page.goto('/');
    await expect(nav.dashboard(page)).toBeVisible({ timeout: 15000 });

    const checkButton = page.getByRole('button', { name: /Check.*Updates/i });
    if (await checkButton.isVisible({ timeout: 5000 }).catch(() => false)) {
      await checkButton.click();
      // Should show progress or toast
      await expect(
        toast.any(page).or(page.locator('[class*="progress"]'))
      ).toBeVisible({ timeout: 15000 });
    }
  });
});
