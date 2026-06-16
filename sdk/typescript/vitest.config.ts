import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    // Default to node; DOM-dependent specs opt in with `// @vitest-environment jsdom`.
    environment: 'node',
    include: ['test/**/*.test.ts'],
  },
});
