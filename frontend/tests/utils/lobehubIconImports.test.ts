// @lobehub/icons' index re-exports every one of its icons, its model and provider
// features and @lobehub/ui beside them, about 2,000 modules. Vitest runs each of
// them through Vite for every test file that reaches the index (it took two of the
// three seconds such a file spent importing), so the app imports each icon by its
// own path: `import OpenAI from '@lobehub/icons/es/OpenAI'`.
import { readdirSync, readFileSync } from 'node:fs';
import { dirname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

describe('no module imports the @lobehub/icons index', () => {
    it('every icon is imported by its own path', () => {
        const frontend = join(dirname(fileURLToPath(import.meta.url)), '../..');
        const offenders: string[] = [];
        const walk = (dir: string) => {
            for (const entry of readdirSync(dir, { withFileTypes: true })) {
                const path = join(dir, entry.name);
                if (entry.isDirectory()) {
                    if (entry.name !== 'node_modules') walk(path);
                    continue;
                }
                if (!/\.[jt]sx?$/.test(entry.name)) continue;
                if (
                    /from\s+['"]@lobehub\/icons['"]|import\(\s*['"]@lobehub\/icons['"]/.test(
                        readFileSync(path, 'utf8')
                    )
                ) {
                    offenders.push(relative(frontend, path));
                }
            }
        };
        walk(join(frontend, 'app'));
        expect(offenders).toEqual([]);
    });
});
