// The app builds from this repository alone. No file under app/ imports a path outside the repository (the SDK's
// source beside it is inside), `@/…` is the app's only alias for its own files, and every package a file imports is
// one app/package.json names, so a fresh clone installs all the app needs. Imports are read with the TypeScript
// compiler: type-only ones too (the typecheck needs them), `import()`, `typeof import()`, `import.meta.glob` patterns
// and `/// <reference>` comments.
import { readdirSync, readFileSync } from 'node:fs';
import { builtinModules } from 'node:module';
import { dirname, join, relative, resolve, sep } from 'node:path';
import ts from 'typescript';
import { describe, expect, it } from 'vitest';
import { SCAN_S } from './limits';

const APP = resolve(import.meta.dirname, '..');
const REPOSITORY = resolve(APP, '..');
const SOURCE = /\.(?:[cm]?[jt]s|[jt]sx)$/;
const SKIPPED = new Set(['node_modules', 'build', '.react-router', '.vite']);
const KINDS: Record<string, ts.ScriptKind> = { '.tsx': ts.ScriptKind.TSX, '.jsx': ts.ScriptKind.JSX, '.js': ts.ScriptKind.JS, '.mjs': ts.ScriptKind.JS, '.cjs': ts.ScriptKind.JS };

/** Every place a module names another: [specifier, how it names it]. */
function specifiers(path: string, text: string): Array<[string, string]> {
    const source = ts.createSourceFile(path, text, ts.ScriptTarget.Latest, true, KINDS[path.slice(path.lastIndexOf('.'))] ?? ts.ScriptKind.TS);
    const found: Array<[string, string]> = [];
    const literal = (node: ts.Node | undefined): string | null =>
        node && (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) ? node.text : null;
    const add = (node: ts.Node | undefined, how: string) => {
        found.push([literal(node) ?? '', how]);
    };
    for (const reference of source.referencedFiles) found.push([reference.fileName.startsWith('.') ? reference.fileName : `./${reference.fileName}`, '/// <reference path>']);
    for (const reference of source.typeReferenceDirectives) found.push([reference.fileName, '/// <reference types>']);
    const visit = (node: ts.Node) => {
        if (ts.isImportDeclaration(node) || (ts.isExportDeclaration(node) && node.moduleSpecifier)) add(node.moduleSpecifier, 'import');
        else if (ts.isImportEqualsDeclaration(node) && ts.isExternalModuleReference(node.moduleReference)) add(node.moduleReference.expression, 'import = require()');
        else if (ts.isImportTypeNode(node) && ts.isLiteralTypeNode(node.argument)) add(node.argument.literal, 'import() type');
        else if (ts.isCallExpression(node)) {
            const callee = node.expression;
            if (callee.kind === ts.SyntaxKind.ImportKeyword) add(node.arguments[0], 'import()');
            else if (ts.isIdentifier(callee) && callee.text === 'require') add(node.arguments[0], 'require()');
            else if (
                ts.isPropertyAccessExpression(callee) &&
                callee.name.text === 'glob' &&
                ts.isMetaProperty(callee.expression) &&
                callee.expression.keywordToken === ts.SyntaxKind.ImportKeyword
            ) {
                const argument = node.arguments[0];
                for (const pattern of argument && ts.isArrayLiteralExpression(argument) ? argument.elements : [argument]) {
                    const text = literal(pattern);
                    // A negated pattern only leaves files out.
                    if (text === null) found.push(['', 'import.meta.glob']);
                    else if (!text.startsWith('!')) found.push([text, 'import.meta.glob']);
                }
            }
        }
        ts.forEachChild(node, visit);
    };
    visit(source);
    return found;
}

const inside = (root: string, path: string): boolean => path === root || path.startsWith(root + sep);

/** Why `specifier`, named in the file at `from`, would need something outside the repository; null when it doesn't. */
function problem(specifier: string, from: string, packages: ReadonlySet<string>): string | null {
    const bare = specifier.replace(/[?#].*$/, '');
    if (bare === '') return 'a computed path, which nothing can check';
    if (bare === '@' || bare.startsWith('@/') || bare === 'noclick') return null;
    if (bare.startsWith('~/')) return "`~/` isn't an alias of this app: its own files are `@/…`";
    if (bare.startsWith('.') || bare.startsWith('/')) {
        // Vite reads a leading `/` as the app's folder.
        const target = bare.startsWith('/') ? join(APP, bare) : resolve(dirname(from), bare);
        return inside(REPOSITORY, target) ? null : `leaves the repository (${relative(REPOSITORY, target)})`;
    }
    if (bare.startsWith('node:') || builtinModules.includes(bare)) return null;
    const segments = bare.split('/');
    const name = (bare.startsWith('@') ? segments.slice(0, 2) : segments.slice(0, 1)).join('/');
    return packages.has(name) ? null : `${name} isn't in app/package.json`;
}

/** Each import under `files` that needs something outside the repository, as `file: specifier (how): why`. */
function outsideImports(files: Record<string, string>, packages: ReadonlySet<string>): string[] {
    return Object.entries(files).flatMap(([path, text]) =>
        specifiers(path, text).flatMap(([specifier, how]) => {
            const why = problem(specifier, path, packages);
            return why === null ? [] : [`${relative(APP, path)}: '${specifier}' (${how}): ${why}`];
        }),
    );
}

function appFiles(): Record<string, string> {
    const files: Record<string, string> = {};
    const collect = (dir: string) => {
        for (const entry of readdirSync(dir, { withFileTypes: true })) {
            const path = join(dir, entry.name);
            if (entry.isDirectory()) {
                if (!SKIPPED.has(entry.name)) collect(path);
            } else if (SOURCE.test(entry.name)) files[path] = readFileSync(path, 'utf8');
        }
    };
    collect(APP);
    return files;
}

describe('reading imports', () => {
    const packages = new Set(['react', '@scope/kit']);
    const at = (name: string) => join(APP, 'src', name);
    const check = (text: string, name = 'page.tsx') => outsideImports({ [at(name)]: text }, packages);

    it('passes the app’s own files, the SDK, declared packages and Node’s built-ins', () => {
        expect(
            check(
                [
                    "import { a } from './a';",
                    "import { b } from '@/ui/b';",
                    "import { Agent } from 'noclick';",
                    "import { useRef } from 'react';",
                    "import { Kit } from '@scope/kit/parts';",
                    "import { join } from 'node:path';",
                    "import { readFile } from 'fs/promises';",
                    "import { VERSION } from '../../sdk/typescript/src/version.ts';",
                ].join('\n'),
            ),
        ).toEqual([]);
    });

    it('catches every way of naming a module, type-only ones included', () => {
        const text = [
            // Read only where TypeScript reads them: above the first statement.
            "/// <reference path=\"../../../h.d.ts\" />",
            "/// <reference types=\"undeclared\" />",
            "import type { A } from '~/a';",
            "export { type B } from '../../../b';",
            "export * from '~/c';",
            "type D = typeof import('~/d');",
            "const e = () => import('~/e');",
            "const f = import.meta.glob(['./pages/*.tsx', '../../../pages/*.tsx', '!../../../skip/*.tsx']);",
            "import g = require('~/g');",
            "import 'other-kit/style.css';",
        ].join('\n');
        expect(check(text, 'page.ts')).toEqual([
            "src/page.ts: '../../../h.d.ts' (/// <reference path>): leaves the repository (../h.d.ts)",
            "src/page.ts: 'undeclared' (/// <reference types>): undeclared isn't in app/package.json",
            "src/page.ts: '~/a' (import): `~/` isn't an alias of this app: its own files are `@/…`",
            "src/page.ts: '../../../b' (import): leaves the repository (../b)",
            "src/page.ts: '~/c' (import): `~/` isn't an alias of this app: its own files are `@/…`",
            "src/page.ts: '~/d' (import() type): `~/` isn't an alias of this app: its own files are `@/…`",
            "src/page.ts: '~/e' (import()): `~/` isn't an alias of this app: its own files are `@/…`",
            "src/page.ts: '../../../pages/*.tsx' (import.meta.glob): leaves the repository (../pages/*.tsx)",
            "src/page.ts: '~/g' (import = require()): `~/` isn't an alias of this app: its own files are `@/…`",
            "src/page.ts: 'other-kit/style.css' (import): other-kit isn't in app/package.json",
        ]);
    });

    it('refuses a path it can’t read', () => {
        expect(check("const name = 'x';\nawait import(name);")).toEqual(["src/page.tsx: '' (import()): a computed path, which nothing can check"]);
    });
});

describe('the app', () => {
    const manifest = JSON.parse(readFileSync(join(APP, 'package.json'), 'utf8'));
    // A types package declares the module it types, as TypeScript reads it: `@types/mdast` is `mdast`.
    const typed = (name: string) => (name.startsWith('@types/') ? [name, name.slice('@types/'.length).replace(/^(.+)__(.+)$/, '@$1/$2')] : [name]);
    const packages = new Set([...Object.keys(manifest.dependencies ?? {}), ...Object.keys(manifest.devDependencies ?? {})].flatMap(typed));

    it('imports nothing from outside this repository, and only packages it declares', () => {
        const files = appFiles();
        // What it reads is the app's own source and configs (122 files on 2026-11-19), so a move can't leave it none.
        expect(Object.keys(files).length).toBeGreaterThan(50);
        expect(Object.keys(files).map((path) => relative(APP, path).split(sep).join('/'))).toEqual(
            expect.arrayContaining(['src/root.tsx', 'src/routes.ts', 'vite.config.ts']),
        );
        expect(outsideImports(files, packages).join('\n')).toBe('');
    }, SCAN_S);
});
