// Always-on reference + transformation builder for a config field whose value is a
// single `{{ ... }}` JS expression. Guides the user end to end: pick a node → drill
// into its data fields → apply JS transforms → see a live preview of the result. The
// chips are context-aware off the live evaluation (object → fields, string/array/number
// → type-appropriate transforms). Neutral-themed to match the rest of the editor.
// Added for inline expressions.

import { useMemo } from 'react';
import { useReferenceAutocomplete } from './ReferenceAutocompleteContext';
import { useExpressionPreview } from '~/hooks/useExpressionPreview';
import type { ScannedBlock } from './expressionSyntax';
import { SerializedIcon } from '~/components/shared/SerializedIcon';
import { getNodeIconMeta } from '~/lib/nodeIconRegistry';

interface ExpressionPanelProps {
    block: ScannedBlock; // the {{ ... }} block the cursor is in (may be embedded in text)
    value: string; // the full field value
    onChange: (value: string) => void;
}

type Transform = { label: string; apply: (expr: string) => string };

// JS transforms offered per value kind. `apply` either appends (`.method()`, `[0]`,
// ` + 1`) or wraps (`Math.round(expr)`) the current expression. Each produces an
// editable starting point (placeholder args like 'old'/'new' are meant to be tweaked).
// Methods are limited to what the QuickJS runtime actually supports — notably NOT
// `.at()` (unsupported), so "last" uses `.slice(-1)[0]`.
const TRANSFORMS: Record<string, Transform[]> = {
    string: [
        { label: 'uppercase', apply: (e) => `${e}.toUpperCase()` },
        { label: 'lowercase', apply: (e) => `${e}.toLowerCase()` },
        { label: 'capitalize', apply: (e) => `${e}.replace(/^./, c => c.toUpperCase())` },
        { label: 'trim', apply: (e) => `${e}.trim()` },
        { label: 'length', apply: (e) => `${e}.length` },
        { label: 'split by comma', apply: (e) => `${e}.split(',')` },
        { label: 'split by line', apply: (e) => `${e}.split('\\n')` },
        { label: 'first word', apply: (e) => `${e}.split(' ')[0]` },
        { label: 'slice', apply: (e) => `${e}.slice(0, 10)` },
        { label: 'replace', apply: (e) => `${e}.replaceAll('old', 'new')` },
        { label: 'contains', apply: (e) => `${e}.includes('text')` },
        { label: 'pad start', apply: (e) => `${e}.padStart(5, '0')` },
        { label: 'to number', apply: (e) => `Number(${e})` },
        { label: 'parse JSON', apply: (e) => `JSON.parse(${e})` },
        { label: 'URL encode', apply: (e) => `encodeURIComponent(${e})` },
        { label: 'default', apply: (e) => `$ifEmpty(${e}, 'fallback')` },
    ],
    array: [
        { label: 'length', apply: (e) => `${e}.length` },
        { label: 'first', apply: (e) => `${e}[0]` },
        { label: 'last', apply: (e) => `${e}.slice(-1)[0]` },
        { label: 'join by comma', apply: (e) => `${e}.join(', ')` },
        { label: 'join by line', apply: (e) => `${e}.join('\\n')` },
        { label: 'map field', apply: (e) => `${e}.map(x => x)` },
        { label: 'filter empty', apply: (e) => `${e}.filter(Boolean)` },
        { label: 'find', apply: (e) => `${e}.find(x => x)` },
        { label: 'sort', apply: (e) => `${e}.slice().sort()` },
        { label: 'reverse', apply: (e) => `${e}.slice().reverse()` },
        { label: 'unique', apply: (e) => `[...new Set(${e})]` },
        { label: 'sum', apply: (e) => `${e}.reduce((a, b) => a + b, 0)` },
        { label: 'flatten', apply: (e) => `${e}.flat()` },
        { label: 'slice', apply: (e) => `${e}.slice(0, 5)` },
        { label: 'to JSON', apply: (e) => `JSON.stringify(${e})` },
    ],
    number: [
        { label: '+1', apply: (e) => `${e} + 1` },
        { label: '−1', apply: (e) => `${e} - 1` },
        { label: '×2', apply: (e) => `${e} * 2` },
        { label: '÷2', apply: (e) => `${e} / 2` },
        { label: 'round', apply: (e) => `Math.round(${e})` },
        { label: 'floor', apply: (e) => `Math.floor(${e})` },
        { label: 'ceil', apply: (e) => `Math.ceil(${e})` },
        { label: 'absolute', apply: (e) => `Math.abs(${e})` },
        { label: '2 decimals', apply: (e) => `${e}.toFixed(2)` },
        { label: 'to text', apply: (e) => `String(${e})` },
    ],
    boolean: [
        { label: 'negate', apply: (e) => `!${e}` },
        { label: 'yes / no', apply: (e) => `${e} ? 'Yes' : 'No'` },
        { label: 'true / false', apply: (e) => `${e} ? 'true' : 'false'` },
    ],
    object: [
        { label: 'keys', apply: (e) => `Object.keys(${e})` },
        { label: 'values', apply: (e) => `Object.values(${e})` },
        { label: 'entries', apply: (e) => `Object.entries(${e})` },
        { label: 'to JSON', apply: (e) => `JSON.stringify(${e})` },
    ],
};

// Shown when a node is picked but its type isn't known yet (it hasn't run, so there's
// no sample output to infer from). Only universally-safe ops that won't throw on any
// value, so the user always has somewhere to start.
const GENERIC_TRANSFORMS: Transform[] = [
    { label: 'to text', apply: (e) => `String(${e})` },
    { label: 'to JSON', apply: (e) => `JSON.stringify(${e})` },
    { label: 'length', apply: (e) => `${e}.length` },
    { label: 'default', apply: (e) => `$ifEmpty(${e}, 'fallback')` },
];

// Append a field access, bracketing keys that aren't valid identifiers.
function appendField(expr: string, key: string): string {
    return /^[A-Za-z_$][\w$]*$/.test(key) ? `${expr}.${key}` : `${expr}[${JSON.stringify(key)}]`;
}

// A workflow variable accessor, bracketing names that aren't valid identifiers.
function varExpr(key: string): string {
    return /^[A-Za-z_$][\w$]*$/.test(key) ? `$vars.${key}` : `$vars[${JSON.stringify(key)}]`;
}

// Built-in accessors/helpers (defined in the backend evaluator preamble), offered as
// expression starters. `$if(...)`/`$ifEmpty(...)` are editable templates — raw JS
// ternaries (`cond ? a : b`) work too, this is just the discoverable form.
const HELPERS: { label: string; expr: string; title: string }[] = [
    { label: '$now', expr: '$now', title: 'Current date and time' },
    { label: '$json', expr: '$json', title: "This step's input data" },
    { label: '$if', expr: "$if(true, 'a', 'b')", title: 'If condition then a, else b' },
    { label: '$ifEmpty', expr: "$ifEmpty('value', 'fallback')", title: 'Use a fallback when empty' },
];

const PREVIEW_MAX_CHARS = 280;

// The backend already returns a compact, clipped preview string; this is just a final
// backstop so an unusually wide clipped object can't flood the panel.
function previewText(text: string | undefined): string {
    const s = text ?? '';
    return s.length > PREVIEW_MAX_CHARS ? `${s.slice(0, PREVIEW_MAX_CHARS)}… (clipped)` : s;
}

const CHIP =
    'inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[11px] bg-foreground/[0.06] border border-foreground/10 text-muted-foreground dark:text-zinc-300 hover:bg-foreground/[0.12] hover:text-foreground transition-colors';

export function ExpressionPanel({ block, value, onChange }: ExpressionPanelProps) {
    const inner = block.inner.trim();
    const ctx = useReferenceAutocomplete();

    // No node chosen yet (empty, or an empty `$('')` placeholder) — show the node picker
    // and don't evaluate (there's nothing to resolve).
    const needsNode = inner === '' || /\$\(\s*''\s*\)/.test(inner);
    const preview = useExpressionPreview(needsNode ? '' : inner);

    // Replace just this `{{ ... }}` block in the field value, leaving surrounding text.
    const setExpr = (expr: string) => {
        const replacement = expr.trim() ? `{{ ${expr} }}` : '';
        onChange(value.slice(0, block.start) + replacement + value.slice(block.end));
    };

    // Node "References": start (or restart) the expression from a node's output.
    const nodes = useMemo(() => {
        return (ctx?.inputNodes ?? []).map((n) => {
            const meta = getNodeIconMeta(n.type as string);
            return {
                id: n.id,
                label: (n.data?.label as string) || meta?.label || n.id,
                iconHtml: meta?.iconHtml,
                iconColor: meta?.iconColor,
            };
        });
    }, [ctx?.inputNodes]);

    // Workflow variables (Set Variable values), surfaced as `$vars.<name>` starters.
    const variables = useMemo(() => Object.keys(ctx?.workflowVariables ?? {}), [ctx?.workflowVariables]);

    // Kind + object keys come from the backend (the clipped preview is display-only).
    // With a known kind show its tailored transforms; with a node picked but no type
    // yet (not run), fall back to the safe generic set so options are always present.
    const kind = preview.hasResult ? preview.kind : undefined;
    const fieldKeys = preview.keys ?? [];
    const transforms = needsNode ? [] : kind ? TRANSFORMS[kind] ?? GENERIC_TRANSFORMS : GENERIC_TRANSFORMS;

    return (
        <div
            className="mt-1 rounded-lg border border-foreground/10 bg-foreground/[0.03] overflow-hidden"
            data-expression-panel
        >
            <div className="px-2 py-1 border-b border-foreground/[0.08] text-[11px] font-medium text-muted-foreground">
                <span className="text-muted-foreground/70 dark:text-zinc-500">ƒ</span> Expression
            </div>

            <div className="max-h-56 overflow-y-auto scrollbar-subtle">
                {/* References — always available so you can start or switch the source node. */}
                {(nodes.length > 0 || variables.length > 0) && (
                    <Section label={needsNode ? 'Pick a reference' : 'References'}>
                        {nodes.map((n) => (
                            <button key={n.id} type="button" onMouseDown={(e) => e.preventDefault()} onClick={() => setExpr(`$('${n.id}')`)} title={`$('${n.id}')`} className={CHIP}>
                                {n.iconHtml && <SerializedIcon html={n.iconHtml} iconColor={n.iconColor} className="w-3.5 h-3.5 shrink-0" />}
                                {n.label}
                            </button>
                        ))}
                        {variables.map((k) => (
                            <button key={`var-${k}`} type="button" onMouseDown={(e) => e.preventDefault()} onClick={() => setExpr(varExpr(k))} title={varExpr(k)} className={`${CHIP} font-mono`}>
                                {varExpr(k)}
                            </button>
                        ))}
                    </Section>
                )}

                {/* Built-in helpers / accessors — expression starters. Shown while starting
                    (an empty block); once a node is picked, Fields/Transform take over. */}
                {needsNode && (
                    <Section label="Helpers">
                        {HELPERS.map((h) => (
                            <button key={h.label} type="button" onMouseDown={(e) => e.preventDefault()} onClick={() => setExpr(h.expr)} title={h.title} className={`${CHIP} font-mono`}>
                                {h.label}
                            </button>
                        ))}
                    </Section>
                )}

                {/* Data fields inside the selected node/object. */}
                {fieldKeys.length > 0 && (
                    <Section label="Fields">
                        {fieldKeys.map((k) => (
                            <button key={k} type="button" onMouseDown={(e) => e.preventDefault()} onClick={() => setExpr(appendField(inner, k))} className={`${CHIP} font-mono`}>
                                .{k}
                            </button>
                        ))}
                    </Section>
                )}

                {/* JS transforms appropriate to the current value's type. */}
                {transforms.length > 0 && (
                    <Section label="Transform">
                        {transforms.map((t) => (
                            <button key={t.label} type="button" onMouseDown={(e) => e.preventDefault()} onClick={() => setExpr(t.apply(inner))} className={CHIP}>
                                {t.label}
                            </button>
                        ))}
                    </Section>
                )}
            </div>

            {/* Live preview of the (transformed) output value. */}
            <div className="px-2 py-1.5 border-t border-foreground/[0.08] bg-foreground/[0.03] dark:bg-black/20" data-expression-preview>
                <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wide text-muted-foreground/70 dark:text-zinc-500 mb-0.5">
                    <span>Output preview</span>
                    {!needsNode && preview.loading && <span className="text-muted-foreground/60 dark:text-zinc-600 normal-case tracking-normal">evaluating…</span>}
                </div>
                <div className="text-[12px] font-mono break-all">
                    {needsNode ? (
                        <span className="text-muted-foreground/70 dark:text-zinc-500">Pick a reference to start</span>
                    ) : preview.error ? (
                        <span className="text-red-600 dark:text-red-400">⚠ {preview.error}</span>
                    ) : preview.hasResult && preview.previewTokens ? (
                        <PreviewTokens tokens={preview.previewTokens} />
                    ) : preview.hasResult ? (
                        <span className="text-foreground">{previewText(preview.preview)}</span>
                    ) : (
                        <span className="text-muted-foreground/70 dark:text-zinc-500">—</span>
                    )}
                </div>
            </div>
        </div>
    );
}

// Output-preview token colors — keys stand out (sky), values lightly tinted, structure muted.
const TOKEN_CLASS: Record<string, string> = {
    key: 'text-sky-700 dark:text-sky-300',
    str: 'text-muted-foreground dark:text-zinc-300',
    num: 'text-amber-600 dark:text-amber-300/90',
    bool: 'text-amber-600 dark:text-amber-300/90',
    null: 'text-muted-foreground/70 dark:text-zinc-500',
    punct: 'text-muted-foreground/70 dark:text-zinc-500',
    meta: 'text-muted-foreground/70 dark:text-zinc-500',
};

// Render the typed preview tokens (keys highlighted), capped so a wide object can't flood.
function PreviewTokens({ tokens }: { tokens: Array<{ t: string; v: string }> }) {
    const out: React.ReactNode[] = [];
    let used = 0;
    for (let i = 0; i < tokens.length; i++) {
        if (used >= PREVIEW_MAX_CHARS) {
            out.push(<span key="cap" className="text-muted-foreground/70 dark:text-zinc-500"> … (clipped)</span>);
            break;
        }
        let v = tokens[i].v;
        if (used + v.length > PREVIEW_MAX_CHARS) v = v.slice(0, PREVIEW_MAX_CHARS - used) + '…';
        used += v.length;
        out.push(<span key={i} className={TOKEN_CLASS[tokens[i].t] ?? 'text-muted-foreground dark:text-zinc-300'}>{v}</span>);
    }
    return <>{out}</>;
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
    return (
        <div className="px-2 py-1.5 border-b border-foreground/[0.05] last:border-b-0">
            <div className="text-[10px] uppercase tracking-wide text-muted-foreground/70 dark:text-zinc-500 mb-1">{label}</div>
            <div className="flex flex-wrap gap-1">{children}</div>
        </div>
    );
}
