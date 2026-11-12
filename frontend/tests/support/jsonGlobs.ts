// An eager glob of small JSON files as one module, for unit tests only. Vite turns
// `import.meta.glob('*.json', { eager: true, import: 'default' })` into an import per
// file, and a test file run in its own worker fetches and evaluates each one: 1,193
// for integrationMetadata, a quarter second of every test file that imports it. The
// module served in its place holds the same keys (as Vite names them) and the same
// values. A glob of large files stays as Vite serves it: nodeSchemas.server's 77 MB
// of schemas took four times as long to load as one string.
import { readdirSync, readFileSync, statSync } from 'fs';
import { dirname, join, relative, resolve } from 'path';
import type { Plugin } from 'vite';

// Only a directory's own `*.json`, the one shape these globs take.
const EAGER_JSON_GLOB =
    /import\.meta\.glob(?:<(?:[^<>]|<[^<>]*>)*>)?\(\s*(['"])(\.{1,2}\/(?:[^'"*]+\/)?)\*\.json\1\s*,\s*\{\s*eager:\s*true,\s*import:\s*(['"])default\3\s*,?\s*\}\s*\)/g;
const PREFIX = 'virtual:json-glob:';
const MAX_BYTES = 10 * 1024 * 1024;

function jsonFiles(where: string): string[] {
    return readdirSync(where)
        .filter((name) => name.endsWith('.json') && !name.startsWith('.'))
        .map((name) => join(where, name))
        .sort();
}

export function jsonGlobs(): Plugin {
    return {
        name: 'noclick:json-globs',
        enforce: 'pre',
        transform(code, id) {
            if (!code.includes('import.meta.glob') || id.includes('node_modules')) return null;
            const imports: string[] = [];
            const dir = dirname(id.split('?')[0]);
            const out = code.replace(EAGER_JSON_GLOB, (glob, _q, folder: string) => {
                const bytes = jsonFiles(resolve(dir, folder)).reduce((sum, file) => sum + statSync(file).size, 0);
                if (bytes > MAX_BYTES) return glob;
                const name = `__jsonGlob${imports.length}`;
                imports.push(`import ${name} from ${JSON.stringify(`${PREFIX}${dir}|${folder}`)};`);
                return name;
            });
            return imports.length ? { code: `${imports.join('\n')}\n${out}`, map: null } : null;
        },
        resolveId(id) {
            return id.startsWith(PREFIX) ? `\0${id}` : null;
        },
        load(id) {
            if (!id.startsWith(`\0${PREFIX}`)) return null;
            const [dir, folder] = id.slice(PREFIX.length + 1).split('|');
            const values: Record<string, unknown> = {};
            for (const file of jsonFiles(resolve(dir, folder))) {
                this.addWatchFile(file);
                const key = relative(dir, file);
                values[key.startsWith('.') ? key : `./${key}`] = JSON.parse(readFileSync(file, 'utf8'));
            }
            // A literal this large parses faster as JSON than as JavaScript.
            return `export default JSON.parse(${JSON.stringify(JSON.stringify(values))});`;
        },
    };
}
