// The fixtures test/pendingTimers.test.ts runs, each file on a fresh worker whose environment outlives its window.
import { join } from 'node:path';
import { defineConfig } from 'vitest/config';

// Caches under the open app's own .vite, as its config keeps them (test/caches.test.ts): left to their defaults they
// went to the open app's node_modules/.vitest-cache, which the frontend's config takes for an install inside it.
const cacheDir = join(import.meta.dirname, '../../../.vite/left-timer');

export default defineConfig({
    cacheDir,
    test: {
        root: import.meta.dirname,
        include: ['*.fixture.ts'],
        environment: './slowTeardown.ts',
        globalSetup: ['../../pendingTimersReport.ts'],
        setupFiles: ['../../pendingTimers.ts'],
        fsModuleCachePath: join(cacheDir, 'vitest-modules'),
    },
});
