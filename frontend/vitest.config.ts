/**
 * Vitest configuration for unit tests.
 *
 * Default 'node' environment for pure TS logic. Tests that need a DOM opt
 * in at the top of the file with `// @vitest-environment happy-dom`, which
 * sets up in a fraction of jsdom's time; the few files that fail under it
 * keep `jsdom`.
 *
 * Integration tests use a separate config — see vitest.integration.config.ts.
 */

import { defineConfig } from 'vitest/config';
import { availableParallelism } from 'os';
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
    // Vitest leaves a CPU to its main process, so a two-CPU CI runner would get one
    // worker; two finish the suite there about a tenth sooner.
    maxWorkers: availableParallelism() <= 2 ? 2 : undefined,
  },
  resolve: {
    alias: [
      { find: '~', replacement: resolve(__dirname, './app') },
      { find: /^@lobehub\/icons\/es\/\w+$/, replacement: resolve(__dirname, './tests/support/lobehubIcon.tsx') },
    ],
  },
  // As in vite.config.ts: modules may read files beside frontend/ (the docs import the SDK READMEs).
  server: {
    fs: {
      allow: [resolve(__dirname, '..')],
    },
  },
});
