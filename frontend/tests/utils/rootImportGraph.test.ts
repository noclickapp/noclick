// What root.tsx imports statically, every page loads before it draws: the landing page and the marketing pages too.
// The integration metadata (a fact sheet per integration, growing with each one) and the credential icon resolvers
// belong to the app's own pages, which load them with their routes; root reached them once through a class name.
import { existsSync, readFileSync, statSync } from 'node:fs';
import { dirname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';
import { expect, it } from 'vitest';

const app = join(dirname(fileURLToPath(import.meta.url)), '../../app');

function resolve(from: string, spec: string): string | null {
    const base = spec.startsWith('~/') ? join(app, spec.slice(2)) : spec.startsWith('.') ? join(dirname(from), spec) : null;
    if (!base) return null;
    for (const ext of ['.ts', '.tsx', '/index.ts', '/index.tsx', '']) {
        const file = base + ext;
        if (existsSync(file) && statSync(file).isFile()) return file;
    }
    return null;
}

/** The chain from `entry` to `goal` along static, non-type imports the browser loads (none of a .server module), or
 *  null when there is none. */
function importChain(entry: string, goal: string): string[] | null {
    const seen = new Set<string>();
    const visit = (file: string): string[] | null => {
        if (file === goal) return [file];
        if (seen.has(file) || !/\.tsx?$/.test(file)) return null;
        seen.add(file);
        const source = readFileSync(file, 'utf8');
        for (const match of source.matchAll(/^\s*(?:import|export)\s+(?!type\b)(?:[^'";]*?\sfrom\s+)?['"]([^'"]+)['"]/gm)) {
            const next = resolve(file, match[1]);
            if (!next || /\.server\./.test(next)) continue;
            const chain = visit(next);
            if (chain) return [file, ...chain];
        }
        return null;
    };
    return visit(entry);
}

it.each(['utils/integrationMetadata.ts', 'utils/credentialIcons.tsx', 'lib/nodeIconRegistry.ts'])('root does not load %s for every page', (module) => {
    const chain = importChain(join(app, 'root.tsx'), join(app, module));
    expect(chain?.map((file) => relative(app, file)).join(' > ') ?? null).toBeNull();
});
