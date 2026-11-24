// A run of the open app's tests leaves no node_modules inside it: here it uses the frontend's packages through
// open/node_modules, and the frontend's config refuses to load once open/app/node_modules exists (an install inside the
// open app). A vitest or vite started without its cache folders writes node_modules/.vitest-cache or .vite there.
import { existsSync } from 'node:fs';
import { join } from 'node:path';

const own = join(import.meta.dirname, '../node_modules');

export default function setup(): () => void {
    const before = existsSync(own);
    return () => {
        if (!before && existsSync(own)) {
            throw new Error(`The run wrote ${own}: a vite or vitest it started keeps its caches there. Give it ` +
                "cacheDir (and fsModuleCachePath) under the open app's .vite, as vitest.config.ts does.");
        }
    };
}
