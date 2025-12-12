// Vitest configuration for frontend unit tests
import { defineConfig } from 'vitest/config';
import path from 'path';

export default defineConfig({
    resolve: {
        alias: {
            '~': path.resolve(__dirname, './app'),
        },
    },
    test: {
        globals: true,
        environment: 'jsdom',
        setupFiles: ['./vitest.setup.ts'],
        include: ['tests/**/*.test.{ts,tsx}', 'tests/**/*.spec.{ts,tsx}'],
        exclude: ['node_modules', 'dist', 'tests/performance'],
    },
});
