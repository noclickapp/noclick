// Playwright configuration for performance testing.
// Focused on measuring React Flow drag performance in headless Chromium.
// Run with: pnpm test:perf

import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  // Look for .perf.ts files in the tests/performance directory
  testDir: './tests/performance',
  testMatch: '**/*.perf.ts',

  // Run tests sequentially for consistent performance measurements
  fullyParallel: false,
  workers: 1,

  // Fail the build on CI if you accidentally left test.only in the source code
  forbidOnly: !!process.env.CI,

  // Retry on CI only
  retries: process.env.CI ? 2 : 0,

  // Reporter - use list for local, json for CI
  reporter: process.env.CI ? 'json' : 'list',

  // Shared settings for all projects
  use: {
    // Base URL for the dev server
    baseURL: 'http://localhost:5173',

    // Collect trace on failure for debugging
    trace: 'on-first-retry',

    // Capture screenshots on failure
    screenshot: 'only-on-failure',
  },

  // Configure project for Chromium only (best performance APIs)
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        // Use headless mode for CI, headed for local debugging
        headless: !process.env.HEADED,
        // Disable animations for consistent measurements
        launchOptions: {
          args: ['--disable-animations'],
        },
      },
    },
  ],

  // Run local dev server before tests if not already running
  webServer: {
    command: 'pnpm dev',
    url: 'http://localhost:5173',
    reuseExistingServer: !process.env.CI,
    timeout: 120 * 1000,
  },

  // Increase timeout for performance tests (they simulate many operations)
  timeout: 60 * 1000,
  expect: {
    timeout: 10 * 1000,
  },
});
