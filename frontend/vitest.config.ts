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
import { readdirSync, readFileSync } from 'fs';
import { join, relative, resolve } from 'path';

const EXCLUDE = ['node_modules', 'build', '.react-router', 'tests/nc', 'tests/integration'];

// A test file with no DOM that changes nothing outside itself (no mocks, spies,
// stubs, fake timers, environment, globals or registrations) runs in a worker
// that keeps the modules earlier files loaded: each file of the rest loads its
// imports afresh. Both groups pass in any order (checked with shuffled runs).
const CHANGES_SHARED_STATE =
  /@vitest-environment|\bvi\.(mock|doMock|unmock|spyOn|stub\w*|useFakeTimers|setSystemTime|resetModules)\b|import\.meta\.env|process\.env|globalThis|\bregister[A-Z]\w*\(/;
const shared: string[] = [];
const isolated: string[] = [];
const collect = (dir: string) => {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    const rel = relative(__dirname, path);
    if (EXCLUDE.includes(rel) || entry.name === 'node_modules') continue;
    if (entry.isDirectory()) collect(path);
    else if (/\.(test|spec)\.tsx?$/.test(entry.name)) {
      (CHANGES_SHARED_STATE.test(readFileSync(path, 'utf8')) ? isolated : shared).push(rel);
    }
  }
};
collect(__dirname);

// Vitest leaves a CPU to its main process, so a two-CPU CI runner would get one
// worker; two finish the suite there about a tenth sooner. The pool keeps both:
// a worker that keeps its modules is stopped mid-file when the pool shrinks.
const workers = availableParallelism() <= 2 ? 2 : undefined;

export default defineConfig({
  test: {
    environment: 'node',
    include: ['**/*.test.ts', '**/*.test.tsx', '**/*.spec.ts', '**/*.spec.tsx'],
    exclude: EXCLUDE,
    testTimeout: 10000,
    maxWorkers: workers,
    minWorkers: workers,
    // Vitest isolates per pool, not per project: the shared files get the threads pool.
    poolOptions: { threads: { isolate: false } },
    projects: [
      { extends: true, test: { name: 'shared', exclude: isolated, pool: 'threads', sequence: { groupOrder: 0 } } },
      { extends: true, test: { name: 'isolated', exclude: shared, sequence: { groupOrder: 1 } } },
    ],
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
