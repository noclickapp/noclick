// Every call to isLocalEdition() must import it. The cloud and open copies of
// a gated component drift independently, the frontend typecheck does not run
// in CI, and a missing import is a ReferenceError the first time the branch
// renders — in production this took down every OAuth node's credentials tab
// (2026-08-30). Cheap to pin; expensive to find in a bundle.
import { describe, expect, it } from 'vitest';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';

function walk(dir: string, out: string[] = []): string[] {
    for (const name of readdirSync(dir)) {
        const full = join(dir, name);
        if (statSync(full).isDirectory()) walk(full, out);
        else if (/\.(tsx?|jsx?)$/.test(name)) out.push(full);
    }
    return out;
}

describe('edition gates', () => {
    it('every file that calls isLocalEdition() imports it', () => {
        const root = join(__dirname, '..', '..', 'app');
        const offenders = walk(root).filter((file) => {
            // Comments may mention the call; only code counts.
            const src = readFileSync(file, 'utf8').replace(/^\s*\/\/.*$/gm, '').replace(/\/\*[\s\S]*?\*\//g, '');
            if (!/\bisLocalEdition\(/.test(src)) return false;
            return !/import\s*\{[^}]*\bisLocalEdition\b[^}]*\}\s*from|export function isLocalEdition/.test(src);
        });
        expect(offenders).toEqual([]);
    });
});
