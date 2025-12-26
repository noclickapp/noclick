/**
 * Vitest configuration for frontend unit tests.
 * - Default: 'node' environment for pure TypeScript logic (faster)
 * - React tests: Add `// @vitest-environment jsdom` at top of file
 */

import { defineConfig } from 'vitest/config';
import { resolve } from 'path';

export default defineConfig({
  test: {
    // Default to node environment for pure logic tests (faster)
    // React hook tests opt-in to jsdom via file-level directive
    environment: 'node',
    // Include test files
    include: ['**/*.test.ts', '**/*.spec.ts'],
    // Exclude node_modules and build artifacts
    exclude: ['node_modules', 'build', '.react-router'],
    // Global test timeout
    testTimeout: 10000,
  },
  resolve: {
    alias: {
      // Match the path alias from tsconfig.json
      '~': resolve(__dirname, './app'),
    },
  },
});
