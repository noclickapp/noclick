import { reactRouter } from '@react-router/dev/vite';
import { existsSync, realpathSync } from 'node:fs';
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

/**
 * What the development server may serve files from. This repository: the SDK's source is outside the app's folder.
 * And, where the app's packages are another project's install lent through a link beside the app (`../node_modules`),
 * the folder that link leads to: the server serves a file a package's stylesheet names (a font) by its real path, and
 * refuses a path outside what it's told, so the page would fall back to the system's fonts.
 */
export function served(): string[] {
    const repository = resolve(import.meta.dirname, '..');
    const lent = resolve(repository, 'node_modules');
    return existsSync(lent) ? [repository, realpathSync(lent)] : [repository];
}

export default defineConfig({
    plugins: [reactRouter()],
    resolve: { alias },
    cacheDir,
    server: { fs: { allow: served() } },
    // The development server bundles the packages the app imports before it serves a page, and finds them by reading
    // these files. Left to find them as pages open (the console loads each of its pages on demand), it bundles again
    // mid-visit and reloads the page, and a page caught in between draws with two copies of React and crashes once.
    optimizeDeps: { entries: ['src/**/*.{ts,tsx}', '!src/**/*.test.{ts,tsx}', '!src/**/*.server.ts'] },
});
