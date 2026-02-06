import { test, expect } from '@playwright/test';
import { ADMIN, toast } from './helpers/selectors';

test.describe('Authentication', () => {
  // Use fresh context with no stored auth state
  test.use({ storageState: { cookies: [], origins: [] } });

  test('redirects unauthenticated user to login page', async ({ page }) => {
    await page.goto('/settings');
    await page.waitForURL(/\/login/, { timeout: 15000 });
    expect(page.url()).toContain('/login');
  });

  test('login with valid credentials', async ({ page }) => {
    await page.goto('/login');
    await expect(page.locator('#username')).toBeVisible({ timeout: 10000 });

    await page.locator('#username').fill(ADMIN.username);
    await page.locator('#password').fill(ADMIN.password);
    await page.getByRole('button', { name: 'Login' }).click();

    await expect(page).toHaveURL('/', { timeout: 15000 });
    await expect(page.getByRole('link', { name: 'Dashboard' })).toBeVisible();
  });

  test('login with invalid credentials shows error', async ({ page }) => {
    await page.goto('/login');
    await expect(page.locator('#username')).toBeVisible({ timeout: 10000 });

    await page.locator('#username').fill('wronguser');
    await page.locator('#password').fill('WrongPass!1');
    await page.getByRole('button', { name: 'Login' }).click();

    // Should stay on login page with error toast
    await expect(page).toHaveURL(/\/login/, { timeout: 5000 });
    await expect(toast.error(page)).toBeVisible({ timeout: 5000 });
  });

  test('login preserves returnUrl redirect', async ({ page }) => {
    // Access settings while unauthenticated
    await page.goto('/settings');
    await page.waitForURL(/\/login/, { timeout: 15000 });
    expect(page.url()).toContain('returnUrl');

    // Login
    await expect(page.locator('#username')).toBeVisible({ timeout: 10000 });
    await page.locator('#username').fill(ADMIN.username);
    await page.locator('#password').fill(ADMIN.password);
    await page.getByRole('button', { name: 'Login' }).click();

    // Should redirect to settings (the original destination)
    await expect(page).toHaveURL('/settings', { timeout: 15000 });
  });
});
