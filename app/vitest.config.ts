// Tests run in Node; a test that needs a DOM says so on its first line (`// @vitest-environment happy-dom`). The React
// Router plugin builds the app, not its tests, so this config takes only vite.config.ts's aliases.
import { availableParallelism } from 'node:os';
import { defineConfig } from 'vitest/config';
import { alias, cacheDir } from './vite.config.ts';

export default defineConfig({
    resolve: { alias },
    cacheDir,
    test: {
        environment: 'node',
        // Vitest leaves a CPU to its main process, so a two-CPU CI runner would get one worker.
        maxWorkers: availableParallelism() <= 2 ? 2 : undefined,
        // A run that writes the open app's node_modules fails (test/ownCaches.ts).
        globalSetup: ['./test/ownCaches.ts', './test/pendingTimersReport.ts'],
        fsModuleCachePath: `${cacheDir}/vitest-modules`,
        include: ['src/**/*.test.{ts,tsx}', 'test/**/*.test.ts'],
        // A timer a DOM test leaves behind fails the run by name (test/pendingTimers.ts).
        // DOM tests wait on state for up to thirty seconds (test/domWaits.ts).
        setupFiles: ['./test/domWaits.ts', './test/pendingTimers.ts'],
        // A test's deadline catches a hang, never a slow machine: a test waits on state, and a loaded machine
        // (several suites at once) took a page's first draw past vitest's five seconds.
        testTimeout: 120_000,
        hookTimeout: 120_000,
    },
});
