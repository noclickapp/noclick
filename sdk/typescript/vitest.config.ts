import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    // Default to node; DOM-dependent specs opt in with `// @vitest-environment jsdom`.
    environment: 'node',
    // The bridge's suite; the client's runs under node --test (npm run test:client).
    include: ['test/embed/**/*.test.ts'],
  },
});
