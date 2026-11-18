import { reactRouter } from '@react-router/dev/vite';
import { resolve } from 'node:path';
import { defineConfig } from 'vite';

/** `@/…` is `src/…`. `noclick` is the TypeScript SDK's source beside the app (`sdk/typescript`), so the app always
 *  runs on the SDK as this repository has it, with no build step between them. vitest.config.ts reads these too. */
export const alias = [
    { find: '@', replacement: resolve(import.meta.dirname, 'src') },
    { find: /^noclick$/, replacement: resolve(import.meta.dirname, '../sdk/typescript/src/index.ts') },
];

/** Where Vite and Vitest keep their caches (vitest.config.ts puts its module cache here too): beside the app, never in
 *  node_modules, which may be another project's install lent to the app. */
export const cacheDir = '.vite';

export default defineConfig({
    plugins: [reactRouter()],
    resolve: { alias },
    cacheDir,
    // The SDK's source is outside the app's folder.
    server: { fs: { allow: [resolve(import.meta.dirname, '..')] } },
});
