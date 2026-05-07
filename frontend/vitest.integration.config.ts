/**
 * Vitest browser-mode configuration for integration tests.
 *
 * Mounts real React trees in a real Chromium window via Playwright,
 * with a MockSocket plugged into socketReceiver so tests can drive the
 * "BE" deterministically. See `tests/integration/helpers/` for the
 * mock-socket + render harness.
 *
 * Run headed (default) for local dev so you can SEE the UI step
 * through; run headless via `--browser.headless` for CI. Scripts
 * already wired in package.json:
 *   pnpm test:integration         — headed watch mode
 *   pnpm test:integration:run     — headless single run
 */

import { defineConfig } from 'vitest/config';
import { resolve } from 'path';

export default defineConfig({
  test: {
    include: [
      'tests/integration/**/*.test.ts',
      'tests/integration/**/*.test.tsx',
    ],
    exclude: ['node_modules', 'build', '.react-router'],
    testTimeout: 15000,
    browser: {
      enabled: true,
      provider: 'playwright',
      name: 'chromium',
      headless: false,
      viewport: { width: 1440, height: 900 },
    },
    // Loaded into the browser before each test file so Tailwind / global
    // styles apply and the rendered UI looks like the real app.
    setupFiles: ['./tests/integration/helpers/setup.ts'],
  },
  resolve: {
    alias: {
      '~': resolve(__dirname, './app'),
    },
  },
});
