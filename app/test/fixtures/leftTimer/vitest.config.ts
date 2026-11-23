// The fixtures test/pendingTimers.test.ts runs, each file on a fresh worker whose environment outlives its window.
import { defineConfig } from 'vitest/config';

export default defineConfig({
    test: {
        root: import.meta.dirname,
        include: ['*.fixture.ts'],
        environment: './slowTeardown.ts',
        setupFiles: ['../../pendingTimers.ts'],
    },
});
