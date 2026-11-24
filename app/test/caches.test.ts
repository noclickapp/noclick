// Every vite and vitest config in the open app keeps its caches where it says (test/ownCaches.ts says why): one that
// names none caches in the open app's node_modules.
import { readdirSync, readFileSync } from 'node:fs';
import { join, relative } from 'node:path';
import { expect, it } from 'vitest';

const app = join(import.meta.dirname, '..');

function configs(dir: string): string[] {
    return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
        if (entry.name === 'node_modules' || entry.name.startsWith('.')) return [];
        const path = join(dir, entry.name);
        if (entry.isDirectory()) return configs(path);
        return /^vite(st)?\.config\.[cm]?[jt]s$/.test(entry.name) ? [path] : [];
    });
}

it('names its cache folders in every config', () => {
    const found = configs(app);
    expect(found.map((path) => relative(app, path))).toContain('test/fixtures/leftTimer/vitest.config.ts');
    for (const path of found) {
        const text = readFileSync(path, 'utf8');
        expect(text, relative(app, path)).toMatch(/\bcacheDir\b/);
        if (path.includes('vitest.config')) expect(text, relative(app, path)).toMatch(/\bfsModuleCachePath\b/);
    }
});
