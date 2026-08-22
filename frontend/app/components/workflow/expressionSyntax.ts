// Shared classification + scanning for `{{ }}` blocks in config fields. Mirrors the
// backend classifier in backend/utils/expression_evaluator.py so the canvas renders
// the same three kinds the runtime evaluates:
//   - JS expression: uses a `$`-accessor (`$('node')`, `$json`, `$vars`, `$if`, ...).
//     Rendered as a ƒ expression chip; evaluated server-side in the QuickJS sandbox.
//   - reference: a legacy dotted path (`node-1.field`). Rendered as a reference chip.
//   - text / literal: anything else. Rendered as plain text and passed through.
// Added for inline expressions in config fields.

// A `$`-accessor signals an intended NoClick expression; deliberately does not match
// a bare `$5`, so `{{ price is $5 }}` stays a literal passthrough (matches backend).
const ACCESSOR_RE = /\$\(|\$(?:ifEmpty|vars|json|now|if)\b/;

export function isJsExpression(inner: string): boolean {
    return ACCESSOR_RE.test(inner);
}

// A "pure accessor" — `$('id')` or `$vars` followed only by a property / numeric-index
// chain, with no transform (no calls, operators, etc.). It's semantically a reference,
// just written in `$()` syntax, so it renders and validates as a reference (not a
// violet expression chip). `$json` is excluded (it has no node to validate against).
const PURE_ACCESSOR_RE = /^\$(?:\(\s*['"]([^'"]+)['"]\s*\)|vars)((?:\.[A-Za-z0-9_$]+|\[\d+\])*)$/;

export function parsePureAccessor(inner: string): { nodeId: string; path: string } | null {
    const m = inner.trim().match(PURE_ACCESSOR_RE);
    if (!m) return null;
    const nodeId = m[1] !== undefined ? m[1] : 'vars';
    return { nodeId, path: (m[2] || '').replace(/^\./, '') };
}

// Convert a pure `$()`/`$vars` accessor to the legacy `nodeId.path` form so the
// existing reference validator can check it; other strings pass through trimmed.
export function normalizeAccessorRef(ref: string): string {
    const pure = parsePureAccessor(ref);
    if (!pure) return ref.trim();
    return pure.path ? `${pure.nodeId}.${pure.path}` : pure.nodeId;
}

export interface ScannedBlock {
    start: number; // index of the opening `{{`
    end: number; // index just past the closing `}}`
    inner: string; // text between the braces
}

// Brace/string-aware scan for top-level `{{ ... }}` blocks. The inner JS may contain
// `}` (object literals, arrow bodies) and brace-bearing string literals, which the
// naive /\{\{[^}]+\}\}/ regex cannot handle (it stops at the first `}`).
export function scanBlocks(value: string): ScannedBlock[] {
    if (typeof value !== 'string') return [];
    const blocks: ScannedBlock[] = [];
    const n = value.length;
    let i = 0;
    while (i < n - 1) {
        if (value[i] === '{' && value[i + 1] === '{') {
            const innerStart = i + 2;
            let j = innerStart;
            let depth = 0;
            let quote = '';
            let closed = false;
            while (j < n) {
                const c = value[j];
                if (quote) {
                    if (c === '\\') {
                        j += 2;
                        continue;
                    }
                    if (c === quote) quote = '';
                    j += 1;
                    continue;
                }
                if (c === "'" || c === '"' || c === '`') {
                    quote = c;
                } else if (c === '{') {
                    depth += 1;
                } else if (c === '}') {
                    if (depth > 0) {
                        depth -= 1;
                    } else if (j + 1 < n && value[j + 1] === '}') {
                        blocks.push({ start: i, end: j + 2, inner: value.slice(innerStart, j) });
                        closed = true;
                        break;
                    }
                }
                j += 1;
            }
            i = closed ? j + 2 : n;
        } else {
            i += 1;
        }
    }
    return blocks;
}

// The `{{ ... }}` expression block the cursor sits inside, or null. Matches an
// expression block (a `$()` expression or an in-progress `$('')`) AND an empty
// `{{ }}` the user just opened — the builder's node picker is how an empty block
// gets filled in. A non-empty legacy/literal block (e.g. `{{node.field}}` or
// `{{ some text }}`) is deliberately skipped so the builder doesn't hijack those.
// Lets the builder attach to a reference embedded in text too — e.g. the cursor
// inside `You are {{ $('x').role }}` — not just whole-field expressions.
export function blockAtCursor(value: string, cursor: number): ScannedBlock | null {
    for (const b of scanBlocks(value)) {
        if (cursor < b.start || cursor > b.end) continue;
        if (isJsExpression(b.inner) || b.inner.trim() === '') return b;
    }
    return null;
}

// The node reference at the cursor's `{{ }}` block, as { nodeId, path }, or null.
// Resolves a pure accessor (`$('node').field` / `$vars.path`) and a legacy dotted
// path precisely; for a transform expression it points at the first node the
// expression reads. Used to reveal/highlight the matching field in the Input panel
// when the caret lands inside a reference.
export function referenceAtCursor(value: string, cursor: number): { nodeId: string; path: string } | null {
    for (const b of scanBlocks(value)) {
        if (cursor < b.start || cursor > b.end) continue;
        const inner = b.inner.trim();
        const pure = parsePureAccessor(inner);
        if (pure) return pure;
        if (isJsExpression(inner)) {
            const m = inner.match(/\$\(\s*['"]([^'"]+)['"]\s*\)/);
            return m ? { nodeId: m[1], path: '' } : null;
        }
        const dot = inner.indexOf('.');
        if (dot > 0) return { nodeId: inner.slice(0, dot), path: inner.slice(dot + 1) };
        if (/^[\w-]+$/.test(inner)) return { nodeId: inner, path: '' };
        return null;
    }
    return null;
}

// If the whole field value is exactly one JS-expression block (`{{ ... }}`), return
// its inner expression; otherwise null. Used to show the live-preview editor only for
// fields that ARE an expression (mixed text/legacy refs are edited inline).
export function getFullMatchExpression(value: string): string | null {
    if (typeof value !== 'string' || !value.includes('{{')) return null;
    const trimmed = value.trim();
    const blocks = scanBlocks(trimmed);
    if (blocks.length !== 1) return null;
    const [b] = blocks;
    if (b.start !== 0 || b.end !== trimmed.length) return null;
    return isJsExpression(b.inner) ? b.inner.trim() : null;
}

// What the cursor is inside, within an unclosed `{{ ... }}` block. Drives which
// autocomplete suggestions to show and how to insert them. The legacy `{{node.field}}`
// path autocomplete is deliberately NOT a context here — typing `{{` scaffolds the
// `$()` accessor form, so the picker only operates on that form.
export type AutocompleteCtx =
    | { kind: 'node'; partial: string; quoteStart: number } // $('<partial>
    | { kind: 'field'; partial: string; nodeId: string; partialStart: number }; // $('id').<partial>

// Detect the autocomplete context at `cursorPos` inside an unclosed `{{ ... }}`:
//  - node:  typing inside $('<partial>     -> suggest upstream nodes
//  - field: typing inside $('nodeId').<p>  -> suggest fields of nodeId
export function detectAccessorContext(value: string, cursorPos: number): AutocompleteCtx | null {
    const before = value.slice(0, cursorPos);
    const open = before.lastIndexOf('{{');
    if (open === -1) return null;
    const inner = before.slice(open + 2);
    if (inner.includes('}}')) return null; // already closed before the cursor

    const nodeM = /\$\(\s*'([^']*)$/.exec(inner);
    if (nodeM) {
        return { kind: 'node', partial: nodeM[1], quoteStart: cursorPos - nodeM[1].length };
    }
    const fieldM = /\$\(\s*'([^']+)'\s*\)\.([\w$.[\]]*)$/.exec(inner);
    if (fieldM) {
        return { kind: 'field', nodeId: fieldM[1], partial: fieldM[2], partialStart: cursorPos - fieldM[2].length };
    }
    return null; // legacy {{node.field}} or a richer expression — no autocomplete
}

// Build the `$()` accessor form drag-drop inserts, so a dragged value is immediately
// ready for transforms (`.split(',')` etc.). Non-identifier path keys (e.g. "First
// Name") use bracket notation; `[n]` indices are preserved.
export function pathToExpression(nodeId: string, path: string): string {
    const esc = (s: string) => s
        .replace(/\\/g, '\\\\')
        .replace(/'/g, "\\'")
        .replace(/\r/g, '\\r')
        .replace(/\n/g, '\\n')
        .replace(/\u2028/g, '\\u2028')
        .replace(/\u2029/g, '\\u2029');
    let expr = `$('${esc(nodeId)}')`;
    if (!path) return expr;
    for (const seg of path.split('.')) {
        const m = seg.match(/^([^[]*)((?:\[\d+\])*)$/);
        if (!m) {
            expr += `['${esc(seg)}']`;
            continue;
        }
        const [, key, idx] = m;
        if (key) {
            expr += /^[A-Za-z_$][A-Za-z0-9_$]*$/.test(key) ? `.${key}` : `['${esc(key)}']`;
        }
        expr += idx || '';
    }
    return expr;
}
