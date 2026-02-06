import { test, expect } from '@playwright/test';
import { toast } from './helpers/selectors';

test.describe('Updates', () => {
  test('loads updates page', async ({ page }) => {
    await page.goto('/updates');

    // Page should load with navigation visible
    await expect(page.getByRole('link', { name: 'Updates' })).toBeVisible({ timeout: 15000 });

    // Should not show error toast
    await expect(toast.error(page)).not.toBeVisible({ timeout: 2000 });
  });
});
