import { test, expect } from '@playwright/test';
import { nav } from './helpers/selectors';

test.describe('Navigation', () => {
  test('can navigate to all main pages via nav bar', async ({ page }) => {
    await page.goto('/');
    await expect(nav.dashboard(page)).toBeVisible({ timeout: 15000 });

    // Updates
    await nav.updates(page).click();
    await expect(page).toHaveURL('/updates');

    // History
    await nav.history(page).click();
    await expect(page).toHaveURL('/history');

    // Settings
    await nav.settings(page).click();
    await expect(page).toHaveURL('/settings');

    // About
    await nav.about(page).click();
    await expect(page).toHaveURL('/about');

    // Back to Dashboard via logo
    await nav.logo(page).click();
    await expect(page).toHaveURL('/');
  });

  test('SSE connection indicator is visible', async ({ page }) => {
    await page.goto('/');
    await expect(nav.dashboard(page)).toBeVisible({ timeout: 15000 });

    // Connection status indicator should show one of the three states
    await expect(
      page
        .getByText('Live')
        .or(page.getByText('Offline'))
        .or(page.getByText('Reconnecting'))
    ).toBeVisible({ timeout: 10000 });
  });
});
