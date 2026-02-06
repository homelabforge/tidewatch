import { test as setup, expect } from '@playwright/test';

const AUTH_FILE = './e2e/.auth/user.json';
const API_BASE = 'http://localhost:8788/api/v1';

const ADMIN = {
  username: 'e2e-admin',
  email: 'e2e@tidewatch.dev',
  password: 'E2eTest!ng123',
  full_name: 'E2E Test Admin',
};

setup('create admin account and authenticate', async ({ page, request }) => {
  // Step 1: Create admin account via API (also sets auth_mode to "local")
  const statusResp = await request.get(`${API_BASE}/auth/status`);
  const status = await statusResp.json();

  if (!status.setup_complete || status.auth_mode === 'none') {
    const setupResp = await request.post(`${API_BASE}/auth/setup`, {
      data: {
        username: ADMIN.username,
        email: ADMIN.email,
        password: ADMIN.password,
        full_name: ADMIN.full_name,
      },
    });
    expect(setupResp.ok(), `Setup failed: ${setupResp.status()}`).toBeTruthy();
  }

  // Step 2: Login via API to get JWT token
  const loginResp = await request.post(`${API_BASE}/auth/login`, {
    data: {
      username: ADMIN.username,
      password: ADMIN.password,
    },
  });
  expect(loginResp.ok(), `Login failed: ${loginResp.status()}`).toBeTruthy();
  const loginData = await loginResp.json();

  // Step 3: Set JWT cookie on browser context for frontend auth
  await page.context().addCookies([
    {
      name: 'tidewatch_token',
      value: loginData.access_token,
      domain: 'localhost',
      path: '/',
      httpOnly: true,
      secure: false,
      sameSite: 'Lax',
    },
  ]);

  // Step 4: Navigate to dashboard and verify authentication works
  await page.goto('/');
  await expect(page.getByRole('link', { name: 'Dashboard' })).toBeVisible({
    timeout: 15000,
  });

  // Save authentication state (cookies + localStorage)
  await page.context().storageState({ path: AUTH_FILE });
});
