// The command palette, mounted once beside the app's frame so it opens on ⌘K / Ctrl+K (and the sidebar's search) from
// every page. What it offers is its host's (the shell's `shell.palette` slot: the places, the person's own things, the
// commands), with what pages handed over (sources.ts) and what registered sources add; the palette itself is the search,
// the ranking (layout.ts), what someone ran lately (history.ts), one category narrowed to ("O W") and the keyboard
// shortcuts. A row is found by its name, the other words people use for it and where it lives (`scoreNamed`); what
// someone runs often floats up, and the latest are offered before anything is typed. Nothing is read per keystroke.
import { Suspense, useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { ArrowRight, ChevronLeft, CornerDownLeft, KeyRound, Search, Workflow as WorkflowIcon } from 'lucide-react';
import { useSlot } from '@/slots';
import { fuzzyFilter } from '@/lib/fuzzySearch';
import { isTextEntryTarget } from '@/lib/keyboard';
import { BrandIcon } from '@/ui/BrandIcon';
import { KeyHint, SequenceKeyHint } from '@/ui/KeyHint';
import { MENU_SURFACE } from '@/ui/menus';
import { useListKeyboardNav } from '@/ui/useListKeyboardNav';
import { cn } from '@/ui/utils';
import { PALETTE, type PaletteContext, type ShortcutGroup, type ShortcutItem } from '../slots';
import { readUses, recordUse, type Use } from './history';
import { layoutCommands, PLACES, type Cmd, type Section } from './layout';
import { OPEN_COMMAND_PALETTE_EVENT, type OpenCommandPaletteDetail, type PaletteScope } from './open';
import { paletteSources, useRememberedPaletteEntries, type PaletteEntry } from './sources';

// The shell's menu language (the composer's "+", Connect): its surface, a roomy search, sentence-case sections.
const SEARCH_ROW = 'flex h-14 items-center gap-3 border-b border-border px-5 dark:border-foreground/[0.07]';
const SEARCH_ICON = 'h-[18px] w-[18px] shrink-0 text-muted-foreground';
const SEARCH_INPUT = 'h-full w-full bg-transparent text-[15px] text-foreground placeholder:text-[hsl(var(--placeholder))] focus:outline-none';
const LIST = 'max-h-[min(52vh,460px)] overflow-y-auto scrollbar-subtle p-2';
const SECTION = 'px-3 pb-1.5 pt-3 text-[12.5px] font-medium text-muted-foreground first:pt-1.5';
const EMPTY = 'px-3 py-10 text-center text-[14px] text-muted-foreground';

// The app shell's words for its sections.
const SECTION_TITLES: Partial<Record<Section | 'Recent', string>> = {
    Workflows: 'Automations',
    Credentials: 'Accounts',
};

type Row = { type: 'header'; title: string } | { type: 'item'; cmd: Cmd; index: number };

export function CommandPalette() {
    const host = useSlot(PALETTE);
    const [open, setOpen] = useState(false);
    const [query, setQuery] = useState('');
    const [page, setPage] = useState<'root' | 'shortcuts'>('root');
    // Non-null when opened via an "O <key>" shortcut — restricts results to one
    // section (e.g. Workflows) and swaps the placeholder ("Open workflow…").
    const [scope, setScope] = useState<PaletteScope | null>(null);
    const inputRef = useRef<HTMLInputElement>(null);
    const listRef = useRef<HTMLDivElement>(null);
    const held = useRememberedPaletteEntries();
    const [uses, setUses] = useState<Record<string, Use>>({});

    // What registered sources add, by source.
    const [added, setAdded] = useState<Record<number, readonly PaletteEntry[]>>({});
    const reporters = useMemo(
        () => paletteSources().map((_, i) => (entries: readonly PaletteEntry[]) => setAdded((prev) => ({ ...prev, [i]: entries }))),
        []
    );
    const registered = useMemo(() => Object.values(added).flat(), [added]);
    const scopeTo = useCallback((next: PaletteScope) => {
        setQuery('');
        setScope(next);
    }, []);
    const showShortcuts = useCallback(() => setPage('shortcuts'), []);
    const context: PaletteContext = { open, page, registered, held, scopeTo, showShortcuts };
    const { commands, beside } = host.useCommands(context);

    // ── Global shortcuts: ⌘K toggles the palette; ⌘/ (or a bare "?") opens it
    // straight to the keyboard-shortcuts panel. ───────────────────────────────
    useEffect(() => {
        const onKey = (e: KeyboardEvent) => {
            const mod = e.metaKey || e.ctrlKey;
            if (mod && e.key.toLowerCase() === 'k') {
                e.preventDefault();
                setOpen((o) => !o);
                return;
            }
            // ⌘/ or Ctrl+/ anywhere, or "?" when not typing in a field.
            const slashCombo = mod && e.key === '/';
            const questionKey = e.key === '?' && !mod && !e.altKey && !isTextEntryTarget(e.target);
            if (slashCombo || questionKey) {
                e.preventDefault();
                setPage('shortcuts');
                setOpen(true);
                return;
            }
        };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, []);

    // Open pre-scoped to a category via an "O <key>" shortcut (see open.ts).
    useEffect(() => {
        const onScopedOpen = (e: Event) => {
            const detail = (e as CustomEvent<OpenCommandPaletteDetail>).detail;
            setScope(detail?.scope ?? null);
            setPage(detail?.page ?? 'root');
            setQuery('');
            setOpen(true);
        };
        window.addEventListener(OPEN_COMMAND_PALETTE_EVENT, onScopedOpen);
        return () => window.removeEventListener(OPEN_COMMAND_PALETTE_EVENT, onScopedOpen);
    }, []);

    // Reset transient state when closed; on open, read what was run here before.
    const readThisOpenRef = useRef(false);
    useEffect(() => {
        if (!open) {
            setQuery('');
            setPage('root');
            setScope(null);
            readThisOpenRef.current = false;
        } else if (!readThisOpenRef.current) {
            readThisOpenRef.current = true;
            setUses(readUses());
        }
    }, [open]);

    // Escape closes ONLY the palette. A capture-phase document listener (active
    // while open) intercepts Escape before any bubble-phase handler (a page's own
    // Escape, Radix's dismiss) and closes the palette, wherever focus sits.
    useEffect(() => {
        if (!open) return;
        const onEscapeCapture = (e: KeyboardEvent) => {
            if (e.key !== 'Escape') return;
            e.preventDefault();
            e.stopImmediatePropagation();
            setOpen(false);
        };
        document.addEventListener('keydown', onEscapeCapture, true);
        return () => document.removeEventListener('keydown', onEscapeCapture, true);
    }, [open]);

    const close = useCallback(() => setOpen(false), []);
    const run = useCallback(
        (cmd: Cmd) => {
            if (!cmd.keepOpen) {
                close();
                recordUse(cmd.id);
            }
            cmd.run();
        },
        [close]
    );

    // A page may hand over something a host's row already holds (a number): the first one stays.
    const allCommands = useMemo(() => {
        const seen = new Set<string>();
        return commands.filter((c) => {
            if (seen.has(c.id)) return false;
            seen.add(c.id);
            return true;
        });
    }, [commands]);

    // ── Filter + group ─────────────────────────────────────────────────────
    const { rows, flat } = useMemo(() => {
        const builtRows: Row[] = [];
        const flatList: Cmd[] = [];
        for (const section of layoutCommands(allCommands, query, scope, uses)) {
            // A scope ("O W") is one section, so its header would only repeat the placeholder.
            if (!scope) builtRows.push({ type: 'header', title: SECTION_TITLES[section.title] ?? section.title });
            for (const cmd of section.items) {
                builtRows.push({ type: 'item', cmd, index: flatList.length });
                flatList.push(cmd);
            }
        }
        return { rows: builtRows, flat: flatList };
    }, [allCommands, query, scope, uses]);

    const {
        index: highlighted,
        setIndex: setHighlighted,
        handleKeyDown,
    } = useListKeyboardNav({
        count: page === 'root' ? flat.length : 0,
        active: open && page === 'root',
        wrap: true,
        onSelect: (i) => {
            const cmd = flat[i];
            if (cmd) run(cmd);
        },
        // Escape is owned by the capture-phase document listener above.
    });

    // Delegate the navigation keys (↑/↓/↵) to the list-nav handler.
    const onContentKeyDown = useCallback(
        (e: ReactKeyboardEvent) => {
            if (e.key === 'Escape') return;
            // Backspace on an empty query in a scoped ("O W") palette steps back
            // out to the full command palette instead of doing nothing.
            if (e.key === 'Backspace' && scope && query === '') {
                e.preventDefault();
                setScope(null);
                return;
            }
            handleKeyDown(e);
        },
        [handleKeyDown, scope, query]
    );

    // Reset highlight whenever the result set / page changes.
    useEffect(() => {
        setHighlighted(0);
    }, [query, page, open, setHighlighted]);

    // Keep the highlighted row in view as you arrow through.
    useEffect(() => {
        if (!open) return;
        const el = listRef.current?.querySelector<HTMLElement>(`[data-cmd-index="${highlighted}"]`);
        el?.scrollIntoView({ block: 'nearest' });
    }, [highlighted, open]);

    return (
        <>
            {paletteSources().map((Source, i) => (
                <Suspense key={i} fallback={null}>
                    <Source onEntries={reporters[i]} />
                </Suspense>
            ))}
            <Dialog.Root open={open} onOpenChange={setOpen}>
                <Dialog.Portal>
                    <Dialog.Overlay className="fixed inset-0 z-[100] bg-foreground/[0.08] dark:bg-background/60" />
                    <Dialog.Content
                        data-testid="command-palette"
                        aria-describedby={undefined}
                        onOpenAutoFocus={(e) => {
                            e.preventDefault();
                            inputRef.current?.focus();
                        }}
                        onKeyDown={onContentKeyDown}
                        // No enter/exit animation — it pops in (and out) instantly.
                        // Without any CSS animation, Radix also unmounts immediately on
                        // close instead of waiting for animationend. Centered with
                        // -translate-x-1/2 (a static transform, not animated). In the shell's menu surface.
                        className={cn('fixed left-1/2 top-[14vh] z-[101] w-[calc(100vw-32px)] max-w-[640px] -translate-x-1/2 overflow-hidden rounded-[26px] focus:outline-none', MENU_SURFACE)}
                    >
                        <Dialog.Title className="sr-only">Command palette</Dialog.Title>

                        {page === 'root' ? (
                            <>
                                {/* Search — in a scope ("O W") the leading glyph becomes
                                    the scope's icon (workflow) instead of the magnifier. */}
                                <div className={SEARCH_ROW}>
                                    {scope === 'Workflows' ? (
                                        <WorkflowIcon className={SEARCH_ICON} />
                                    ) : scope === 'Credentials' ? (
                                        <KeyRound className={SEARCH_ICON} />
                                    ) : (
                                        <Search className={SEARCH_ICON} />
                                    )}
                                    <input
                                        ref={inputRef}
                                        value={query}
                                        onChange={(e) => setQuery(e.target.value)}
                                        placeholder={scope ? (host.scopes.find((s) => s.scope === scope)?.label ?? 'Search…') : 'Search or go anywhere…'}
                                        className={SEARCH_INPUT}
                                    />
                                </div>

                                {/* Results */}
                                <div ref={listRef} className={LIST}>
                                    {rows.length === 0 ? (
                                        <div className={EMPTY}>
                                            {query
                                                ? `No results for “${query}”`
                                                : scope === 'Credentials'
                                                  ? `No ${(SECTION_TITLES.Credentials ?? 'credentials').toLowerCase()} yet`
                                                  : scope === 'Workflows'
                                                    ? `No ${(SECTION_TITLES.Workflows ?? 'workflows').toLowerCase()} yet`
                                                    : 'No results'}
                                        </div>
                                    ) : (
                                        rows.map((row, i) =>
                                            row.type === 'header' ? (
                                                <div key={`h:${row.title}:${i}`} data-cmd-section className={SECTION}>
                                                    {row.title}
                                                </div>
                                            ) : (
                                                <CommandRow
                                                    key={row.cmd.id}
                                                    cmd={row.cmd}
                                                    active={row.index === highlighted}
                                                    index={row.index}
                                                    onHover={() => setHighlighted(row.index)}
                                                    onSelect={() => run(row.cmd)}
                                                />
                                            )
                                        )
                                    )}
                                </div>
                            </>
                        ) : (
                            <ShortcutsPage groups={host.shortcuts} onBack={() => setPage('root')} />
                        )}
                    </Dialog.Content>
                </Dialog.Portal>
                {beside}
            </Dialog.Root>
        </>
    );
}

function CommandRow({ cmd, active, index, onHover, onSelect }: { cmd: Cmd; active: boolean; index: number; onHover: () => void; onSelect: () => void }) {
    const Icon = cmd.icon;
    return (
        <button
            type="button"
            data-cmd-index={index}
            data-active={active || undefined}
            onMouseMove={onHover}
            onClick={onSelect}
            className={cn('group flex h-11 w-full items-center gap-3.5 rounded-[16px] px-3 text-left outline-none transition-colors', active && 'bg-foreground/[0.07]')}
        >
            {cmd.iconColor !== undefined ? (
                // Brand/service rows keep their brand color via BrandIcon.
                <BrandIcon Icon={Icon} iconColor={cmd.iconColor} className="h-[18px] w-[18px] shrink-0" />
            ) : (
                <Icon className="h-[18px] w-[18px] shrink-0 text-foreground/85 [stroke-width:1.75]" />
            )}
            {/* Its name, then where it lives; the place gives way first on a narrow screen. */}
            <span className="flex min-w-0 flex-1 items-baseline gap-2">
                <span className="truncate text-[14.5px] text-foreground">{cmd.label}</span>
                {cmd.context && (
                    <span data-cmd-context className="shrink-[3] truncate text-[13px] text-muted-foreground">
                        {cmd.context}
                    </span>
                )}
            </span>
            {cmd.trailing}
            {cmd.meta && <span className="shrink-0 whitespace-nowrap text-[12.5px] text-muted-foreground max-sm:hidden">{cmd.meta}</span>}
            {PLACES.has(cmd.section) ? (
                <ArrowRight className={cn('h-4 w-4 shrink-0', active ? 'text-muted-foreground' : 'text-muted-foreground/60')} />
            ) : (
                active && <CornerDownLeft className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
            )}
        </button>
    );
}

// Sequence shortcuts render with "then"; simultaneous combos (⌘K) render as adjacent keycaps.
function ShortcutKeys({ item }: { item: ShortcutItem }) {
    return item.sequence ? <SequenceKeyHint keys={item.keys} /> : <KeyHint keys={item.keys} />;
}

function ShortcutsPage({ groups: all, onBack }: { groups: readonly ShortcutGroup[]; onBack: () => void }) {
    const [filter, setFilter] = useState('');
    const searchRef = useRef<HTMLInputElement>(null);
    useEffect(() => {
        searchRef.current?.focus();
    }, []);
    const groups = all
        .map((g) => ({
            title: g.title,
            items: fuzzyFilter(g.items, filter, (s) => [
                { text: s.label.toLowerCase(), weight: 1, fuzzy: true },
                { text: s.keys.join(' ').toLowerCase(), weight: 0.6, fuzzy: true },
            ]),
        }))
        .filter((g) => g.items.length > 0);

    return (
        <div>
            {/* Single top row: a Back affordance and the search input, as the root palette has it, so the panel
                has just one divider. */}
            <div className={cn(SEARCH_ROW, 'pl-3')}>
                <button
                    type="button"
                    data-testid="command-palette-back"
                    onClick={onBack}
                    aria-label="Back"
                    className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-foreground/[0.06] text-foreground/80 transition-colors hover:bg-foreground/[0.1] hover:text-foreground"
                >
                    <ChevronLeft className="h-[18px] w-[18px]" />
                </button>
                <input ref={searchRef} value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Search shortcuts…" className={SEARCH_INPUT} />
            </div>
            <div className={LIST}>
                {groups.length === 0 ? (
                    <div className={EMPTY}>No shortcuts for “{filter}”</div>
                ) : (
                    groups.map((g) => (
                        <div key={g.title}>
                            <div data-cmd-section className={SECTION}>
                                {g.title}
                            </div>
                            {g.items.map((s) => (
                                <div key={s.label} className="flex h-10 items-center justify-between rounded-[14px] px-3">
                                    <span className="text-[14.5px] text-foreground/90">{s.label}</span>
                                    <ShortcutKeys item={s} />
                                </div>
                            ))}
                        </div>
                    ))
                )}
            </div>
        </div>
    );
}
