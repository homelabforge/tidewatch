import { test, expect } from '@playwright/test';
import { toast } from './helpers/selectors';

test.describe('History', () => {
  test('loads history page without errors', async ({ page }) => {
    await page.goto('/history');

    // Page should load (either shows history events or empty state)
    await expect(page.getByRole('link', { name: 'History' })).toBeVisible({ timeout: 15000 });

    // Should not show error toast
    await expect(toast.error(page)).not.toBeVisible({ timeout: 2000 });
  });
});
