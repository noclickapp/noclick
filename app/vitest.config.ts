// Tests run in Node; a test that needs a DOM says so on its first line (`// @vitest-environment happy-dom`). The React
// Router plugin builds the app, not its tests, so this config takes only vite.config.ts's aliases.
import { defineConfig } from 'vitest/config';
import { alias, cacheDir } from './vite.config.ts';

export default defineConfig({
    resolve: { alias },
    cacheDir,
    test: {
        environment: 'node',
        // A run that writes the open app's node_modules fails (test/ownCaches.ts).
        globalSetup: ['./test/ownCaches.ts'],
        fsModuleCachePath: `${cacheDir}/vitest-modules`,
        include: ['src/**/*.test.{ts,tsx}', 'test/**/*.test.ts'],
        // A timer a DOM test leaves behind fails the run by name (test/pendingTimers.ts).
        // DOM tests wait up to five seconds (test/domWaits.ts).
        setupFiles: ['./test/domWaits.ts', './test/pendingTimers.ts'],
    },
});
