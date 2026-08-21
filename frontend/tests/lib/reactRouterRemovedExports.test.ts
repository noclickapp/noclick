/**
 * React Router 7 removed `json` and `defer`. The 7.18 migration replaced the
 * static imports with ~/lib/routerResponse, but a DYNAMIC destructure —
 * `const { json } = await import('react-router')` — is invisible to that
 * sweep and to the type-checker at the import site: the property is simply
 * undefined and every caller 500s at runtime. That took down all five payment
 * routes (authedJsonRoute) and the public template/share/invite loaders
 * (createPublicLoaderData) on 2026-08-21. This scan pins the rule for both
 * import forms.
 */
import { readdirSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const APP_DIR = path.resolve(__dirname, '../../app');
const REMOVED = ['json', 'defer'];

function sourceFiles(dir: string): string[] {
    return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
        const full = path.join(dir, entry.name);
        if (entry.isDirectory()) return sourceFiles(full);
        return /\.(ts|tsx)$/.test(entry.name) && !entry.name.includes('.test.')
            ? [full]
            : [];
    });
}

describe('react-router removed exports', () => {
    it('no source destructures json/defer from react-router (static or dynamic)', () => {
        const offenders: string[] = [];
        const dynamicUse = new RegExp(
            `\\{[^}]*\\b(${REMOVED.join('|')})\\b[^}]*\\}\\s*=\\s*await\\s+import\\(\\s*['"]react-router['"]`
        );
        const staticUse = new RegExp(
            `import\\s*(?:type\\s*)?\\{[^}]*\\b(${REMOVED.join('|')})\\b[^}]*\\}\\s*from\\s*['"]react-router['"]`
        );
        for (const file of sourceFiles(APP_DIR)) {
            const src = readFileSync(file, 'utf8');
            if (dynamicUse.test(src) || staticUse.test(src)) {
                offenders.push(path.relative(APP_DIR, file));
            }
        }
        expect(
            offenders,
            `these files pull a removed react-router export (json/defer) — ` +
                `import { json } from '~/lib/routerResponse' instead`
        ).toEqual([]);
    });
});
