// The `key:value` query bar. Committed words render as removable chips in
// canonical form (an invalid one in red with its reason below); the draft
// offers keys first, then values from the schema and the page's loaded lists.
import { useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
import { Search, X } from 'lucide-react';
import { searchFieldClass } from '@/ui/SearchField';
import { cn } from '@/ui/utils';
import { canonicalQuery, parseQuery, type QueryError, type QuerySchema } from '@/screens/console/lib/query';
import { useSlashFocus } from '@/screens/console/hooks/useSlashFocus';

export interface QuerySuggestion {
    /** What the draft becomes. */
    value: string;
    /** Commit at once (a value) or keep typing (a key). */
    commit: boolean;
}

/** Autocomplete for a draft: keys first, then that key's values. */
export function querySuggestions(draft: string, schema: QuerySchema, extra: Readonly<Record<string, readonly string[]>> = {}): QuerySuggestion[] {
    const colon = draft.indexOf(':');
    if (colon < 0) {
        const negated = draft.startsWith('-');
        const prefix = (negated ? draft.slice(1) : draft).toLowerCase();
        const out: QuerySuggestion[] = [];
        for (const [key, spec] of Object.entries(schema)) {
            if (!key.startsWith(prefix)) continue;
            if (!negated) out.push({ value: `${key}:`, commit: false });
            if (spec.negate && (negated || prefix)) out.push({ value: `-${key}:`, commit: false });
        }
        return out;
    }
    const head = draft.slice(0, colon);
    const key = head.replace(/^-/, '');
    const spec = schema[key];
    if (!spec) return [];
    const typed = draft.slice(colon + 1);
    const cut = typed.lastIndexOf(',');
    const chosen = cut >= 0 ? typed.slice(0, cut + 1) : '';
    const partial = (cut >= 0 ? typed.slice(cut + 1) : typed).toLowerCase();
    const values = Array.from(new Set([...(spec.values ?? []), ...(extra[key] ?? [])]));
    return values
        .filter((v) => v.toLowerCase().startsWith(partial) && v.toLowerCase() !== partial)
        .slice(0, 8)
        .map((v) => ({ value: `${head}:${chosen}${v}`, commit: true }));
}

function words(q: string): string[] {
    return q.split(/\s+/).filter(Boolean);
}

/**
 * Whether the controls beside the bar already show a committed word, so the bar
 * leaves its chip out (a filter is shown once): the time range always, one
 * user when the user facet is there, a status the segmented shortcut names.
 */
export function shownBeside(word: string, { user, statuses = [] }: { user: boolean; statuses?: readonly string[] }): boolean {
    if (/^(since|until):/.test(word)) return true;
    if (user && /^user:[^,]+$/.test(word)) return true;
    const status = /^status:([^,]+)$/.exec(word)?.[1];
    return !!status && statuses.includes(status);
}

export function QueryBar({
    schema,
    value,
    onChange,
    suggestions = {},
    count,
    errors = [],
    placeholder = 'Filter: key:value',
    label = 'Filter',
    beside,
    className,
}: {
    schema: QuerySchema;
    value: string;
    onChange: (q: string) => void;
    /** Values from the page's loaded lists (kinds, users, agents, key prefixes), by key. */
    suggestions?: Readonly<Record<string, readonly string[]>>;
    /** The live count from the page's summary endpoint. */
    count?: ReactNode;
    /** Errors found while mapping to the API (an unknown agent name). */
    errors?: readonly QueryError[];
    placeholder?: string;
    label?: string;
    /** Words the controls beside the bar show, left out of its chips (`shownBeside`). */
    beside?: (word: string) => boolean;
    className?: string;
}) {
    const inputRef = useRef<HTMLInputElement>(null);
    useSlashFocus(inputRef);
    const [draft, setDraft] = useState('');
    const [open, setOpen] = useState(false);
    const [highlight, setHighlight] = useState(0);
    // Chips and error tokens share the canonical form (`status:failed,,expired` → `status:failed,expired`).
    const committed = useMemo(() => words(canonicalQuery(value, schema)), [value, schema]);
    const parsed = useMemo(() => parseQuery(value, schema), [value, schema]);
    const allErrors = [...parsed.errors, ...errors];
    const bad = new Set(allErrors.map((e) => e.token));
    const options = useMemo(() => querySuggestions(draft, schema, suggestions), [draft, schema, suggestions]);

    const commit = (text: string) => {
        const t = text.trim();
        if (!t) return;
        onChange(canonicalQuery([...committed, t].join(' '), schema));
        setDraft('');
        setHighlight(0);
    };
    const accept = (s: QuerySuggestion) => {
        if (s.commit) commit(s.value);
        else {
            setDraft(s.value);
            setHighlight(0);
        }
        inputRef.current?.focus();
    };
    const remove = (index: number) => onChange(committed.filter((_, i) => i !== index).join(' '));
    // An invalid word always shows, so its reason has something to point at.
    const chips = committed.map((word, i) => ({ word, i })).filter(({ word }) => bad.has(word) || !beside?.(word));

    const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
        if (e.key === 'ArrowDown' && options.length) {
            e.preventDefault();
            setOpen(true);
            setHighlight((h) => (h + 1) % options.length);
        } else if (e.key === 'ArrowUp' && options.length) {
            e.preventDefault();
            setHighlight((h) => (h - 1 + options.length) % options.length);
        } else if ((e.key === 'Enter' || e.key === 'Tab') && open && options[highlight] && draft) {
            e.preventDefault();
            accept(options[highlight]);
        } else if (e.key === 'Enter' || (e.key === ' ' && draft.includes(':'))) {
            e.preventDefault();
            commit(draft);
        } else if (e.key === 'Backspace' && !draft && chips.length) {
            e.preventDefault();
            const last = chips[chips.length - 1];
            setDraft(last.word);
            remove(last.i);
        } else if (e.key === 'Escape') {
            setOpen(false);
        }
    };

    return (
        <div className={cn('relative min-w-0 flex-1', className)}>
            {/* A click anywhere on the chip row focuses the input, which is itself keyboard-reachable. */}
            {/* eslint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/no-static-element-interactions */}
            <div
                className={cn(searchFieldClass('md'), 'h-auto min-h-9 w-full flex-wrap gap-1 rounded-[18px] px-3 py-1 max-md:h-auto max-md:min-h-10')}
                onClick={() => inputRef.current?.focus()}
            >
                <Search className="h-4 w-4 shrink-0" strokeWidth={1.8} />
                {chips.map(({ word, i }) => (
                    <span
                        key={`${word}-${i}`}
                        className={cn(
                            'inline-flex max-w-full items-center gap-0.5 rounded px-1.5 py-[1px] font-mono text-[12px]',
                            bad.has(word) ? 'bg-red-500/10 text-red-600 dark:text-red-400' : 'bg-foreground/[0.06] text-foreground'
                        )}
                    >
                        <span className="truncate">{word}</span>
                        <button
                            type="button"
                            aria-label={`Remove ${word}`}
                            onClick={(e) => {
                                e.stopPropagation();
                                remove(i);
                            }}
                            className="rounded text-muted-foreground hover:text-foreground"
                        >
                            <X className="h-3 w-3" />
                        </button>
                    </span>
                ))}
                <input
                    ref={inputRef}
                    value={draft}
                    aria-label={label}
                    placeholder={chips.length ? '' : placeholder}
                    onChange={(e) => {
                        setDraft(e.target.value);
                        setOpen(true);
                        setHighlight(0);
                    }}
                    onFocus={() => setOpen(true)}
                    onBlur={() => window.setTimeout(() => setOpen(false), 120)}
                    onKeyDown={onKeyDown}
                    className="h-7 min-w-[8rem] flex-1 bg-transparent font-mono text-[12px] text-foreground outline-none placeholder:font-sans placeholder:text-[13px] placeholder:text-muted-foreground max-md:text-[16px] max-md:placeholder:text-[16px]"
                />
                {count !== undefined && <span className="shrink-0 whitespace-nowrap text-[12px] tabular-nums text-muted-foreground">{count}</span>}
            </div>
            {open && draft && options.length > 0 && (
                <ul role="listbox" className="absolute left-0 top-full z-30 mt-1 w-72 max-w-full overflow-hidden rounded-lg border border-border bg-popover p-1 text-popover-foreground shadow-lg">
                    {options.map((opt, i) => (
                        <li key={opt.value} role="option" aria-selected={i === highlight}>
                            <button
                                type="button"
                                onMouseDown={(e) => e.preventDefault()}
                                onClick={() => accept(opt)}
                                className={cn('w-full rounded-md px-2 py-1 text-left font-mono text-[12px]', i === highlight ? 'bg-foreground/[0.07]' : 'hover:bg-foreground/[0.05]')}
                            >
                                {opt.value}
                            </button>
                        </li>
                    ))}
                </ul>
            )}
            {allErrors.length > 0 && (
                <ul className="m-0 mt-1 list-none p-0">
                    {allErrors.map((err) => (
                        <li key={`${err.token}:${err.message}`} className="text-[12px] text-red-600 dark:text-red-400">
                            {err.message.replace(/`([^`]+)`/g, '$1')}
                        </li>
                    ))}
                </ul>
            )}
        </div>
    );
}
