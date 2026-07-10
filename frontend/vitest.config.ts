/**
 * Vitest configuration for unit tests.
 *
 * Default 'node' environment for pure TS logic. React-hook tests opt
 * into jsdom via `// @vitest-environment jsdom` at the top of the file.
 *
 * Integration tests use a separate config — see vitest.integration.config.ts.
 */

import { defineConfig } from 'vitest/config';
import { resolve } from 'path';

export default defineConfig({
  test: {
    environment: 'node',
    include: ['**/*.test.ts', '**/*.test.tsx', '**/*.spec.ts', '**/*.spec.tsx'],
    exclude: [
      'node_modules',
      'build',
      '.react-router',
      'tests/nc',
      'tests/integration',
    ],
    testTimeout: 10000,
  },
  resolve: {
    alias: {
      '~': resolve(__dirname, './app'),
    },
  },
});
