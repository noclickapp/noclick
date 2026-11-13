// Chrome 157's scrollTo, scrollBy, scroll and scrollIntoView answer with a promise, though TypeScript's DOM types still
// say void. An effect whose value is one of those calls hands React the promise as its cleanup, and React calls it when
// the deps change or the component goes: the root ErrorBoundary took Work as an agent's Add a trigger panel closed
// ("y is not a function", 2026-11-13). Such an effect scrolls in a braced body instead.

import { readdirSync, readFileSync } from 'node:fs';
import { join, relative } from 'node:path';
import ts from 'typescript';
import { describe, expect, it } from 'vitest';

const APP = join(__dirname, '../../app');
const EFFECTS = new Set(['useEffect', 'useLayoutEffect', 'useInsertionEffect']);
const SCROLLS = new Set(['scrollTo', 'scrollBy', 'scroll', 'scrollIntoView']);

function sources(dir: string): string[] {
    return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
        const path = join(dir, entry.name);
        if (entry.isDirectory()) return sources(path);
        return /\.tsx?$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name) ? [path] : [];
    });
}

/** What an effect's function returns: its expression body, or each `return` of its own body. */
function returned(fn: ts.ArrowFunction | ts.FunctionExpression): ts.Expression[] {
    if (!ts.isBlock(fn.body)) return [fn.body];
    const out: ts.Expression[] = [];
    const walk = (node: ts.Node) => {
        if (ts.isFunctionLike(node)) return;
        if (ts.isReturnStatement(node) && node.expression) out.push(node.expression);
        ts.forEachChild(node, walk);
    };
    ts.forEachChild(fn.body, walk);
    return out;
}

/** Whether `value` can be what a scroll call answered (a function it builds is a cleanup, never that). */
function scrolls(value: ts.Node): boolean {
    if (ts.isFunctionLike(value)) return false;
    if (ts.isCallExpression(value)) {
        const callee = value.expression;
        const name = ts.isPropertyAccessExpression(callee) ? callee.name.text : ts.isIdentifier(callee) ? callee.text : '';
        if (SCROLLS.has(name)) return true;
    }
    return ts.forEachChild(value, scrolls) ?? false;
}

/** The lines of `text` where an effect hands React what a scroll call answered. */
function offendingLines(name: string, text: string): number[] {
    if (!/Effect\(/.test(text) || !/\bscroll(To|By|IntoView)?\(/.test(text)) return [];
    const source = ts.createSourceFile(name, text, ts.ScriptTarget.Latest, true, name.endsWith('x') ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
    const found: number[] = [];
    const visit = (node: ts.Node) => {
        if (ts.isCallExpression(node)) {
            const callee = node.expression;
            const effect = ts.isIdentifier(callee) ? callee.text : ts.isPropertyAccessExpression(callee) ? callee.name.text : '';
            const fn = node.arguments[0];
            if (EFFECTS.has(effect) && fn && (ts.isArrowFunction(fn) || ts.isFunctionExpression(fn)))
                for (const value of returned(fn)) if (scrolls(value)) found.push(source.getLineAndCharacterOfPosition(value.getStart()).line + 1);
        }
        ts.forEachChild(node, visit);
    };
    visit(source);
    return found;
}

describe('effects in app source', () => {
    it('never hand React what a scroll call answered', () => {
        const offenders = sources(APP).flatMap((file) => offendingLines(file, readFileSync(file, 'utf8')).map((line) => `${relative(APP, file)}:${line}`));
        expect(offenders).toEqual([]);
    });

    it('finds an effect whose value is a scroll, and passes one that scrolls in a braced body', () => {
        const text = [
            'useEffect(() => ref.current?.scrollTo({ top: 0 }), [k]);',
            'useEffect(() => { ref.current?.scrollTo({ top: 0 }); }, [k]);',
            'React.useLayoutEffect(() => { if (a) return el.scrollIntoView(); }, []);',
            'useEffect(() => { el.scrollBy(0, 1); return () => el.scrollTo(0, 0); }, []);',
        ].join('\n');
        expect(offendingLines('probe.tsx', text)).toEqual([1, 3]);
    });
});
