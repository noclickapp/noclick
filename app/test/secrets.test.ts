// A guard against accidents, not a proof: it keeps the app's secrets (the NoClick key, the password, the session
// secret) in the few modules written to hold them, so a change can't quietly hand them to code that might reach a page.
// It reads every module under src/ with the TypeScript compiler and reports the plain ways out. Code set on getting
// around it can (a string built at run time, an object passed along); review is what catches that. The rules:
//   - only src/server/config.server.ts reads the environment (`process`, `globalThis`, another runtime's env, or
//     `import.meta` beyond the build's own flags DEV, PROD, SSR, MODE and BASE_URL), and no module runs code from a
//     string (`eval`, `Function`) or reaches around names (`Reflect`);
//   - a module may import others by pattern (`import.meta.glob(…)`: the console finds its pages so, and the root
//     route whatever a fork puts under src/custom/) only with patterns written out as strings, none of which takes in
//     a module that holds a secret;
//   - only the modules that need them import what hands out a secret from config.server.ts (`noclickApiKey`: the key
//     proxy and the server client; `appConfigContext`, which holds the password and session secret: the gate, the
//     proxy, sign-in, the session, and the module that hands a page the API's address and nothing else;
//     `checkConfig`: the gate), nothing imports config.server.ts whole, and nothing passes any of them on;
//   - only the browser's client (src/sdk/proxied.ts), the server client and the console lab's client (which answers
//     from canned data and holds no key) make an SDK client, under any name; nothing uses the SDK's default client
//     (`configure`, `defaultClient`), which reads the key from the environment by itself, nothing imports the SDK
//     whole, and nothing reads a client's `apiKey`;
//   - no route, and no module, is a test file (which this guard doesn't read).
import { readdirSync, readFileSync } from 'node:fs';
import { dirname, join, relative, resolve } from 'node:path';
import ts from 'typescript';
import { describe, expect, it } from 'vitest';

const APP = resolve(import.meta.dirname, '..');
const SRC = join(APP, 'src');
const CONFIG = 'src/server/config.server';
const ENV_READER = 'src/server/config.server.ts';
/** Who may import each thing config.server.ts hands a secret out with. */
const SECRET_HOLDERS: Record<string, ReadonlySet<string>> = {
    noclickApiKey: new Set(['src/server/proxy.server.ts', 'src/server/client.server.ts']),
    appConfigContext: new Set([
        'src/server/gate.server.ts',
        'src/server/proxy.server.ts',
        'src/server/signIn.server.ts',
        'src/server/session.server.ts',
        'src/server/apiUrl.server.ts',
    ]),
    checkConfig: new Set(['src/server/gate.server.ts']),
};
const CLIENT_MAKERS = new Set(['src/sdk/proxied.ts', 'src/server/client.server.ts', 'src/screens/console/fixtures/client.ts', 'src/screens/work/fixtures/client.ts']);
const BUILD_FLAGS = new Set(['DEV', 'PROD', 'SSR', 'MODE', 'BASE_URL']);
const TEST_FILE = /\.test\.[cm]?[jt]sx?$/;
/** Every module that reads or is handed a secret: what no pattern of imports may take in. */
const SECRET_MODULES = [ENV_READER, ...new Set(Object.values(SECRET_HOLDERS).flatMap((holders) => [...holders]))];

/**
 * Whether a pattern of `import.meta.glob` in `file` takes in `module` (both paths from the app), reading the pattern
 * as Vite does: from the file's folder, the app (`/…`) or src (`@/…`), with `*`, `**`, `?` and `{a,b}`. Null for a
 * pattern written with anything else, which the guard can't read.
 */
function globTakesIn(pattern: string, file: string, module: string): boolean | null {
    if (!/^[\w@./*?{},-]+$/.test(pattern)) return null;
    const from = pattern.startsWith('@/') ? join('src', pattern.slice(2)) : pattern.startsWith('/') ? pattern.slice(1) : join(dirname(file), pattern);
    let test = '';
    for (let i = 0; i < from.length; i++) {
        const char = from[i];
        if (char === '*' && from[i + 1] === '*') {
            const whole = from[i + 2] === '/';
            test += whole ? '(?:.*/)?' : '.*';
            i += whole ? 2 : 1;
        } else if (char === '*') test += '[^/]*';
        else if (char === '?') test += '[^/]';
        else if (char === '{') test += '(?:';
        else if (char === '}') test += ')';
        else if (char === ',') test += '|';
        else test += char === '.' ? '\\.' : char;
    }
    return new RegExp(`^${test}$`).test(module);
}

/** The module a specifier in `file` names, as a path from the app without its extension; null for a package. */
function target(specifier: string, file: string): string | null {
    let path: string;
    if (specifier.startsWith('@/')) path = join(SRC, specifier.slice(2));
    else if (specifier.startsWith('.')) path = resolve(dirname(join(APP, file)), specifier);
    else return null;
    return relative(APP, path).replace(/\.(?:[cm]?[jt]sx?)$/, '');
}

/** Every breach of the rules above in `files` (path from the app → source), as `file: what`. */
function breaches(files: Record<string, string>): string[] {
    const found: string[] = [];
    for (const [file, text] of Object.entries(files)) {
        const source = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, file.endsWith('x') ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
        const breach = (what: string) => found.push(`${file}: ${what}`);
        const envReader = file === ENV_READER;
        /** The names this module gave the SDK's client class and its default client. */
        const clientNames = new Set<string>();
        const visit = (node: ts.Node) => {
            if (ts.isIdentifier(node) && !envReader && ['process', 'globalThis', 'Bun', 'Deno'].includes(node.text)) breach(`reads \`${node.text}\``);
            if (ts.isStringLiteral(node) && !envReader && (node.text === 'process' || node.text === 'node:process')) breach(`names '${node.text}'`);
            if (ts.isIdentifier(node) && ['eval', 'Function'].includes(node.text)) breach(`runs code from a string (\`${node.text}\`)`);
            if (ts.isIdentifier(node) && node.text === 'Reflect') breach('reaches around names (`Reflect`)');
            if (ts.isMetaProperty(node) && node.keywordToken === ts.SyntaxKind.ImportKeyword) {
                const env = node.parent;
                const flag = ts.isPropertyAccessExpression(env) && env.name.text === 'env' && ts.isPropertyAccessExpression(env.parent) && env.parent.expression === env ? env.parent.name.text : null;
                const glob = ts.isPropertyAccessExpression(env) && env.name.text === 'glob' && ts.isCallExpression(env.parent) && env.parent.expression === env ? env.parent : null;
                if (glob) {
                    // Imports by pattern: each pattern a string, none taking in a module that holds a secret.
                    const first = glob.arguments[0];
                    const written = first && ts.isArrayLiteralExpression(first) ? [...first.elements] : first ? [first] : [];
                    const patterns = written.filter(ts.isStringLiteral).map((literal) => literal.text);
                    if (!written.length || patterns.length !== written.length) breach('imports by a pattern it doesn’t write out');
                    for (const pattern of patterns.filter((p) => !p.startsWith('!'))) {
                        const taken = SECRET_MODULES.map((module) => globTakesIn(pattern, file, module));
                        if (taken.includes(null)) breach(`imports by a pattern the guard can’t read ('${pattern}')`);
                        else if (taken.includes(true)) breach(`imports by a pattern that takes in a module holding a secret ('${pattern}')`);
                    }
                } else if (flag === null || !BUILD_FLAGS.has(flag)) breach(`reads import.meta${flag ? `.env.${flag}` : ts.isPropertyAccessExpression(env) ? `.${env.name.text}` : ''}`);
            }
            if ((ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) && node.moduleSpecifier && ts.isStringLiteral(node.moduleSpecifier)) {
                const specifier = node.moduleSpecifier.text;
                const bindings = ts.isImportDeclaration(node) ? node.importClause?.namedBindings : node.exportClause;
                const typeOnly = ts.isImportDeclaration(node) ? Boolean(node.importClause?.isTypeOnly) : node.isTypeOnly;
                const elements = bindings && (ts.isNamedImports(bindings) || ts.isNamedExports(bindings)) ? [...bindings.elements] : null;
                const resolved = target(specifier, file);
                if (resolved !== null && /\.test$/.test(resolved)) breach('imports a test file');
                if (resolved === CONFIG && elements === null && !typeOnly) breach('imports config.server whole');
                for (const element of elements ?? []) {
                    const name = (element.propertyName ?? element.name).text;
                    if (element.isTypeOnly || typeOnly) continue;
                    if (resolved === CONFIG && SECRET_HOLDERS[name] && !SECRET_HOLDERS[name].has(file)) breach(`imports ${name}`);
                    if (ts.isExportDeclaration(node) && SECRET_HOLDERS[name]) breach(`passes ${name} on`);
                    if (specifier === 'noclick' && (name === 'configure' || name === 'defaultClient')) breach('uses the SDK’s default client');
                    if (specifier === 'noclick' && name === 'NoClick') clientNames.add(element.name.text);
                }
                if (specifier === 'noclick' && elements === null && !typeOnly) breach('imports the SDK whole');
            }
            // `export { noclickApiKey }` of an imported name (one with a module specifier is judged above).
            if (ts.isExportSpecifier(node) && !node.parent.parent.moduleSpecifier && SECRET_HOLDERS[(node.propertyName ?? node.name).text]) {
                breach(`passes ${(node.propertyName ?? node.name).text} on`);
            }
            if (ts.isCallExpression(node) && node.expression.kind === ts.SyntaxKind.ImportKeyword) {
                const argument = node.arguments[0];
                if (!argument || !ts.isStringLiteral(argument) || target(argument.text, file) === CONFIG || argument.text === 'noclick') breach('imports at run time a module it can’t name, config.server or the SDK');
            }
            if (ts.isPropertyAccessExpression(node) && node.name.text === 'apiKey') breach('reads a client’s apiKey');
            ts.forEachChild(node, visit);
        };
        // The SDK's names are bound by imports, which come first: collect them before judging their uses.
        visit(source);
        const makes = (node: ts.Node): void => {
            const made =
                (ts.isNewExpression(node) && ts.isIdentifier(node.expression) && clientNames.has(node.expression.text)) ||
                (ts.isPropertyAccessExpression(node) && ts.isIdentifier(node.expression) && clientNames.has(node.expression.text) && node.name.text === 'forSession');
            if (made && !CLIENT_MAKERS.has(file)) breach('makes an SDK client');
            ts.forEachChild(node, makes);
        };
        makes(source);
    }
    return found;
}

/** The route modules routes.ts names. */
function routeModules(text: string): string[] {
    const source = ts.createSourceFile('routes.ts', text, ts.ScriptTarget.Latest, true);
    const modules: string[] = [];
    const visit = (node: ts.Node) => {
        if (ts.isStringLiteral(node) && /\.[cm]?[jt]sx?$/.test(node.text)) modules.push(node.text);
        ts.forEachChild(node, visit);
    };
    visit(source);
    return modules;
}

function appModules(): Record<string, string> {
    const files: Record<string, string> = {};
    const collect = (dir: string) => {
        for (const entry of readdirSync(dir, { withFileTypes: true })) {
            const path = join(dir, entry.name);
            if (entry.isDirectory()) collect(path);
            else if (/\.(?:[cm]?[jt]sx?)$/.test(entry.name) && !TEST_FILE.test(entry.name)) files[relative(APP, path)] = readFileSync(path, 'utf8');
        }
    };
    collect(SRC);
    return files;
}

describe('the guard', () => {
    it('passes what the app is meant to do', () => {
        expect(
            breaches({
                [ENV_READER]: 'export const env = () => (globalThis as any).process?.env;',
                'src/server/proxy.server.ts': "import { appConfigContext, noclickApiKey } from './config.server';",
                'src/server/client.server.ts': "import { noclickApiKey } from './config.server';\nimport { NoClick } from 'noclick';\nnew NoClick({});",
                'src/sdk/proxied.ts': "import { NoClick, type ClientOptions } from 'noclick';\nnew NoClick({ apiKey: 'x' });",
                'src/routes/login.tsx': "import type { AppConfig } from '@/server/config.server';\nimport type * as Config from '@/server/config.server';\nif (import.meta.env.DEV) {}",
                'src/screens/page.tsx': "import { APIConnectionError, type NoClick } from 'noclick';",
                'src/server/apiUrl.server.ts': "import { appConfigContext } from './config.server';",
                'src/screens/console/fixtures/client.ts': "import { NoClick } from 'noclick';\nnew NoClick({});",
                'src/screens/console/sections.ts': "const pages = import.meta.glob(['./pages/*.tsx', '!./pages/*.test.tsx']);",
                'src/root.tsx': "import.meta.glob('./custom/*.{ts,tsx}', { eager: true });\nimport.meta.glob('./server/*.md');",
            }),
        ).toEqual([]);
    });

    it('catches the plain ways out', () => {
        expect(
            breaches({
                'src/routes/page.tsx': [
                    "import { noclickApiKey } from '@/server/config.server';",
                    "import { noclickApiKey as key, appConfigContext, checkConfig } from '../server/config.server.ts';",
                    "import * as config from '@/server/config.server';",
                    "export { noclickApiKey } from '@/server/config.server';",
                    "export * from '@/server/config.server';",
                    "const later = await import('@/server/config.server');",
                    "const sdk = await import('noclick');",
                    'const k = process.env.NOCLICK_API_KEY;',
                    "const g = (globalThis as any)['pro' + 'cess'];",
                    "import { env } from 'node:process';",
                    'const b = Bun.env.NOCLICK_API_KEY ?? Deno.env.get("NOCLICK_API_KEY");',
                    "const f = new Function('return 1');",
                    "const e = eval('1');",
                    'const r = Reflect.get(Object, "keys");',
                    'const v = import.meta.env.VITE_NOCLICK_API_KEY;',
                    'const all = import.meta.env;',
                    'const { env: meta } = import.meta as any;',
                    "import { configure, NoClick as Client, defaultClient as fallback } from 'noclick';",
                    "import * as whole from 'noclick';",
                    'const c = new Client({ apiKey: k });',
                    "const s = Client.forSession('nk_sess_x');",
                    'const leaked = c.apiKey;',
                    "import { helper } from './helper.test';",
                    'const find = import.meta.glob;',
                    "const named = './pages/*.tsx';",
                    'import.meta.glob(named);',
                    'import.meta.glob();',
                    "import.meta.glob(['./pages/*.tsx', named]);",
                    "import.meta.glob('../server/*.ts');",
                    "import.meta.glob('@/**/*.server.ts', { eager: true });",
                    "import.meta.glob('/src/server/{config,gate}.server.ts');",
                    "import.meta.glob(['./pages/[a-c]*.ts']);",
                    "import.meta.glob(['../ui/*.tsx', '!../server/*.ts']);",
                ].join('\n'),
                'src/server/proxy.server.ts': "import { noclickApiKey } from './config.server';\nexport { noclickApiKey };",
            }),
        ).toEqual([
            'src/routes/page.tsx: imports noclickApiKey',
            'src/routes/page.tsx: imports noclickApiKey',
            'src/routes/page.tsx: imports appConfigContext',
            'src/routes/page.tsx: imports checkConfig',
            'src/routes/page.tsx: imports config.server whole',
            'src/routes/page.tsx: imports noclickApiKey',
            'src/routes/page.tsx: passes noclickApiKey on',
            'src/routes/page.tsx: imports config.server whole',
            'src/routes/page.tsx: imports at run time a module it can’t name, config.server or the SDK',
            'src/routes/page.tsx: imports at run time a module it can’t name, config.server or the SDK',
            'src/routes/page.tsx: reads `process`',
            'src/routes/page.tsx: reads `globalThis`',
            "src/routes/page.tsx: names 'node:process'",
            'src/routes/page.tsx: reads `Bun`',
            'src/routes/page.tsx: reads `Deno`',
            'src/routes/page.tsx: runs code from a string (`Function`)',
            'src/routes/page.tsx: runs code from a string (`eval`)',
            'src/routes/page.tsx: reaches around names (`Reflect`)',
            'src/routes/page.tsx: reads import.meta.env.VITE_NOCLICK_API_KEY',
            'src/routes/page.tsx: reads import.meta.env',
            'src/routes/page.tsx: reads import.meta',
            'src/routes/page.tsx: uses the SDK’s default client',
            'src/routes/page.tsx: uses the SDK’s default client',
            'src/routes/page.tsx: imports the SDK whole',
            'src/routes/page.tsx: reads a client’s apiKey',
            'src/routes/page.tsx: imports a test file',
            'src/routes/page.tsx: reads import.meta.glob',
            'src/routes/page.tsx: imports by a pattern it doesn’t write out',
            'src/routes/page.tsx: imports by a pattern it doesn’t write out',
            'src/routes/page.tsx: imports by a pattern it doesn’t write out',
            "src/routes/page.tsx: imports by a pattern that takes in a module holding a secret ('../server/*.ts')",
            "src/routes/page.tsx: imports by a pattern that takes in a module holding a secret ('@/**/*.server.ts')",
            "src/routes/page.tsx: imports by a pattern that takes in a module holding a secret ('/src/server/{config,gate}.server.ts')",
            "src/routes/page.tsx: imports by a pattern the guard can’t read ('./pages/[a-c]*.ts')",
            'src/routes/page.tsx: makes an SDK client',
            'src/routes/page.tsx: makes an SDK client',
            'src/server/proxy.server.ts: passes noclickApiKey on',
        ]);
    });

    it('finds the route modules routes.ts names', () => {
        expect(routeModules("export default [index('routes/home.tsx'), route('x', 'routes/x.test.tsx')];")).toEqual(['routes/home.tsx', 'routes/x.test.tsx']);
    });
});

describe('the app', () => {
    it('keeps its secrets where they are meant to be', () => {
        const modules = appModules();
        expect(Object.keys(modules)).toEqual(expect.arrayContaining([ENV_READER, ...CLIENT_MAKERS, ...Object.values(SECRET_HOLDERS).flatMap((holders) => [...holders])]));
        expect(breaches(modules).join('\n')).toBe('');
    });

    it('names no test file as a route, so the guard reads every route', () => {
        const routes = routeModules(readFileSync(join(SRC, 'routes.ts'), 'utf8'));
        expect(routes.length).toBeGreaterThan(3);
        expect(routes.filter((route) => TEST_FILE.test(route))).toEqual([]);
    });

    it('keeps every module that holds a secret server-only, which the build refuses to send to a browser', () => {
        for (const file of [ENV_READER, ...Object.values(SECRET_HOLDERS).flatMap((holders) => [...holders])]) expect(file).toMatch(/\.server\.ts$/);
    });
});
