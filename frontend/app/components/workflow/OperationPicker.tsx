// Spotlight/Raycast-style operation picker for discriminated-union nodes.
//
// Two states:
//   - Closed (an op is selected): a one-line `Action: <Display Name>  [Change]`
//     row. The corresponding fields render below in NodeConfig.
//   - Open (no op selected, or user clicked Change): full-bleed picker that
//     replaces the entire field area. Search input at top; below it, a
//     triggers section followed by ops grouped by `x-category`. Each section
//     renders its ops as a responsive multi-column grid of clickable tiles.
//     Keyboard nav: ↑↓ ← → ↵ Esc.
//
// Reads display label, object category, trigger flag, and tier label from
// callbacks the parent provides — same shape as the earlier operation picker so
// NodeConfig.tsx can swap one for the other without rewriting the helpers.

import { ComponentType, useEffect, useMemo, useRef, useState } from 'react';
import { Pencil, Search, Star, X, Zap } from 'lucide-react';
import { BrandIcon } from '~/components/shared/BrandIcon';
import { usePickerKeyboardNav, type PickerNavDirection } from '~/hooks/usePickerKeyboardNav';
import { scoreFields, type SearchField } from '~/utils/fuzzySearch';
import { valueToText } from './valueText';

function TierLabel({ label }: { label: string }) {
    const starCount = (label.match(/⭐/g) || []).length;
    if (starCount > 0) {
        return (
            <span className="flex items-center gap-0.5">
                {Array.from({ length: starCount }).map((_, i) => (
                    <Star key={i} className="h-2.5 w-2.5 fill-muted-foreground dark:fill-zinc-500 text-muted-foreground dark:text-zinc-500" />
                ))}
            </span>
        );
    }
    // Non-star tiers name a requirement the stars can't express — Slack's
    // Enterprise Grid admin methods, which need a bot token from the user's
    // own Grid app. Returning null here would hide the requirement until the
    // operation failed at runtime.
    return (
        <span className="px-1 py-px rounded text-[9px] font-medium uppercase tracking-wide bg-secondary text-muted-foreground">
            {label}
        </span>
    );
}

interface OperationPickerProps {
    options: any[];
    selectedIndex: number;
    onSelect: (index: number) => void;
    getOptionLabel: (index: number) => string;
    getOptionCategory: (index: number) => string | null;
    getOptionIsTrigger: (index: number) => boolean;
    getOptionTierLabel?: (index: number) => string | null;
    /** Extra identity text for search ranking (e.g. the raw operation value
     *  "send_message", the schema title). Fuzzy-matched alongside the label so
     *  abbreviations and synonyms still surface the right action. */
    getOptionKeywords?: (index: number) => string;
    /** Operation description, searched (substring only) so a query can match
     *  synonyms that live in prose (e.g. "remove" finding a "Delete" action). */
    getOptionDescription?: (index: number) => string;
    /** Indices to hide (e.g. credential-incompatible). */
    hiddenIndices?: Set<number>;
    /** Whether the picker is in its open/expanded state. */
    isOpen: boolean;
    /** Auto-focus the search input when the picker opens. False while a node is
     *  reached via keyboard arrow-traversal, so the picker doesn't steal focus
     *  and trap node navigation. Defaults to true (click/Enter into config). */
    autoFocusOnOpen?: boolean;
    /** Open the picker (e.g. user clicked the Change button). */
    onOpen: () => void;
    /** Close the picker (e.g. Esc, or after a successful selection). */
    onClose: () => void;
    /** Inline slot rendered next to the closed-state label (e.g. AI autofill button). */
    headerAction?: React.ReactNode;
    /** True when any operation has been explicitly chosen (vs. defaulted). When false,
     *  the closed state's "Change" button is the only way to leave the picker — Esc
     *  is a no-op. */
    hasExplicitSelection: boolean;
    /** Optional node-type icon rendered as a small leading glyph on every op
     *  tile and on the closed-state badge. Provides quick visual identification
     *  of which integration the action belongs to. */
    NodeIcon?: ComponentType<{ className?: string; style?: React.CSSProperties }>;
    /** Tailwind color class for `NodeIcon` (e.g. `text-blue-600 dark:text-blue-400`). May be
     *  empty for icons that paint themselves (e.g. inline SVG with built-in
     *  fills like the Telegram glyph). */
    nodeIconColor?: string;
}

const TRIGGER_SECTION_KEY = '__triggers__';

export function OperationPicker({
    options,
    selectedIndex,
    onSelect,
    getOptionLabel,
    getOptionCategory,
    getOptionIsTrigger,
    getOptionTierLabel,
    getOptionKeywords,
    getOptionDescription,
    hiddenIndices,
    isOpen,
    autoFocusOnOpen = true,
    onOpen,
    onClose,
    headerAction,
    hasExplicitSelection,
    NodeIcon,
    nodeIconColor,
}: OperationPickerProps) {
    const [query, setQuery] = useState('');
    const inputRef = useRef<HTMLInputElement>(null);
    const gridContainerRef = useRef<HTMLDivElement>(null);

    const optionLabels = useMemo(
        () => options.map((_, idx) => valueToText(getOptionLabel(idx))),
        [options, getOptionLabel],
    );

    const visibleIndices = useMemo(() => {
        const indices = options.map((_, idx) => idx);
        return hiddenIndices && hiddenIndices.size > 0
            ? indices.filter((idx) => !hiddenIndices.has(idx))
            : indices;
    }, [options, hiddenIndices]);

    /** Group visible indices by category, with triggers in a special bucket. */
    const grouped = useMemo(() => {
        const triggerIndices: number[] = [];
        const byCategory = new Map<string, number[]>();
        for (const idx of visibleIndices) {
            if (getOptionIsTrigger(idx)) {
                triggerIndices.push(idx);
                continue;
            }
            const cat = getOptionCategory(idx) || 'Other';
            const arr = byCategory.get(cat);
            if (arr) arr.push(idx);
            else byCategory.set(cat, [idx]);
        }
        const sortByLabel = (a: number, b: number) =>
            optionLabels[a].localeCompare(optionLabels[b]);
        triggerIndices.sort(sortByLabel);
        for (const arr of byCategory.values()) arr.sort(sortByLabel);

        const sections: { key: string; label: string; indices: number[] }[] = [];
        if (triggerIndices.length > 0) {
            sections.push({
                key: TRIGGER_SECTION_KEY,
                label: 'Triggers',
                indices: triggerIndices,
            });
        }
        const catNames = Array.from(byCategory.keys()).sort((a, b) => {
            if (a === 'Misc') return 1;
            if (b === 'Misc') return -1;
            return a.localeCompare(b);
        });
        for (const cat of catNames) {
            sections.push({ key: cat, label: cat, indices: byCategory.get(cat)! });
        }
        return sections;
    }, [visibleIndices, getOptionIsTrigger, getOptionCategory, optionLabels]);

    /** Weighted search fields per option: label is the strongest signal, then
     *  identity keywords (operation value/title), category, and the trigger
     *  marker; the description is searched at low weight for synonym recall. */
    const searchFieldsFor = (idx: number): SearchField[] => {
        const fields: SearchField[] = [
            { text: optionLabels[idx].toLowerCase(), weight: 1, fuzzy: true },
        ];
        const keywords = getOptionKeywords?.(idx);
        if (keywords) fields.push({ text: keywords.toLowerCase(), weight: 0.6, fuzzy: true });
        const category = getOptionCategory(idx);
        if (category) fields.push({ text: category.toLowerCase(), weight: 0.4 });
        if (getOptionIsTrigger(idx)) fields.push({ text: 'trigger', weight: 0.3 });
        const description = getOptionDescription?.(idx);
        if (description) fields.push({ text: description.toLowerCase(), weight: 0.25 });
        return fields;
    };

    /** Relevance score per visible option for the current query, or null while
     *  the query is empty (the picker shows the full browse-by-category view). */
    const optionScores = useMemo(() => {
        const q = query.trim();
        if (!q) return null;
        const scores = new Map<number, number>();
        for (const idx of visibleIndices) {
            const score = scoreFields(searchFieldsFor(idx), q);
            if (score !== null) scores.set(idx, score);
        }
        return scores;
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [query, visibleIndices, optionLabels]);

    /** Apply the search ranking: keep only matching options, sort each section
     *  best-first, then float the highest-scoring sections to the top so the
     *  flat reading order leads with the single best match (auto-highlighted,
     *  committed on Enter). Empty query → the untouched `grouped` browse view. */
    const filteredSections = useMemo(() => {
        if (!optionScores) return grouped;
        const sectionBest = (indices: number[]) =>
            indices.reduce((max, idx) => Math.max(max, optionScores.get(idx) ?? 0), 0);
        return grouped
            .map((sec) => ({
                ...sec,
                indices: sec.indices
                    .filter((idx) => optionScores.has(idx))
                    .sort(
                        (a, b) =>
                            optionScores.get(b)! - optionScores.get(a)! ||
                            optionLabels[a].localeCompare(optionLabels[b]),
                    ),
            }))
            .filter((sec) => sec.indices.length > 0)
            .sort((a, b) => sectionBest(b.indices) - sectionBest(a.indices));
    }, [grouped, optionScores, optionLabels]);

    /** Flat reading-order list of indices (top-to-bottom, left-to-right inside each
     *  section). Used as the canonical order for keyboard navigation. */
    const flatIndices = useMemo(
        () => filteredSections.flatMap((sec) => sec.indices),
        [filteredSections],
    );

    /** Width (px) of the widest op label across all categories, including the
     *  per-button padding and the slack we reserve for the selected dot + tier
     *  stars. Used as the uniform column width so categories line up vertically
     *  no matter how long their longest op happens to be. */
    const columnWidth = useMemo(() => {
        if (typeof document === 'undefined') return 140;
        const canvas = document.createElement('canvas');
        const ctx = canvas.getContext('2d');
        if (!ctx) return 140;
        // Match the op-button typography (text-[12px], system-ui font stack).
        ctx.font = "12px ui-sans-serif, -apple-system, system-ui, 'Segoe UI', sans-serif";
        let widest = 0;
        for (const label of optionLabels) {
            const w = ctx.measureText(label).width;
            if (w > widest) widest = w;
        }
        // px-2 padding (16px) + ~22px slack for the selected dot and tier
        // stars, plus 20px when we're rendering a leading node icon.
        const iconSlack = NodeIcon ? 20 : 0;
        const measured = Math.ceil(widest) + 16 + 22 + iconSlack;
        // Floor at 120px so very-short-op nodes still feel like column tiles
        // rather than tiny chips.
        return Math.max(measured, 120);
    }, [optionLabels, NodeIcon]);

    // Highlight state, navigation-gated scrollIntoView, and arrow/Enter key
    // capture live in the shared picker hook (also used by the agent-tool
    // allowlist picker). The 2D nearest-in-direction strategy stays here.
    const {
        highlightedIndex,
        setHighlightedIndex,
        resetNavigation,
        handleKeyDown: handleNavKeyDown,
    } = usePickerKeyboardNav({
        itemCount: flatIndices.length,
        containerRef: gridContainerRef,
        resolveNext: (direction, current) => findNearestInDirection(direction, current),
        onCommit: (index) => {
            onSelect(flatIndices[index]);
            onClose();
        },
    });

    // Esc fallback: intercept at window-capture so we beat ReactFlow's native
    // deselect handler (and any other native listener registered with
    // useCapture=true). React's onKeyDown alone fires in bubble phase, after
    // those have already run.
    useEffect(() => {
        if (!isOpen || !hasExplicitSelection) return;
        const handler = (e: KeyboardEvent) => {
            if (e.key !== 'Escape') return;
            e.preventDefault();
            e.stopPropagation();
            e.stopImmediatePropagation();
            onClose();
        };
        window.addEventListener('keydown', handler, { capture: true });
        return () => window.removeEventListener('keydown', handler, { capture: true });
    }, [isOpen, hasExplicitSelection, onClose]);

    // Autofocus the search input + reset query when the picker opens. Also
    // park the picker scroll at the top so the user can see the search bar
    // and instructional heading right away — even if the previously-chosen
    // op is mid-list.
    useEffect(() => {
        if (!isOpen) {
            // Reset the navigation gate so the next open also starts fresh.
            resetNavigation();
            return;
        }
        setQuery('');
        const pos = flatIndices.indexOf(selectedIndex);
        setHighlightedIndex(pos >= 0 ? pos : 0);
        const t = setTimeout(() => {
            // preventScroll keeps the autofocus from yanking the page on
            // overflow-y containers further up the tree. Skipped during keyboard
            // node-traversal so the picker doesn't trap arrow navigation.
            if (autoFocusOnOpen) inputRef.current?.focus({ preventScroll: true });
            gridContainerRef.current?.scrollTo({ top: 0 });
        }, 0);
        return () => clearTimeout(t);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [isOpen]);

    // While typing, keep the highlight on the top-ranked result so Enter
    // commits the best match. Guarded on a non-empty query so reopening with a
    // cleared query still highlights the current selection (the open effect).
    useEffect(() => {
        if (isOpen && query.trim()) setHighlightedIndex(0);
    }, [query, isOpen, setHighlightedIndex]);

    /** Walk all rendered op buttons and pick the one whose visual center is
     *  the nearest in `direction` from the currently-highlighted button. We
     *  measure live via getBoundingClientRect rather than tracking category
     *  membership, so multi-column flow (multiple categories stacked in one
     *  visual column) still navigates by what the user actually sees.
     *
     *  Distance metric weights the perpendicular axis 3× so e.g. → strongly
     *  prefers items in the same horizontal band over items further down.
     */
    const findNearestInDirection = (
        direction: PickerNavDirection,
        current: number,
    ): number | null => {
        const container = gridContainerRef.current;
        if (!container) return null;
        const buttons = container.querySelectorAll<HTMLElement>('[data-flat-index]');
        if (!buttons.length) return null;

        let fromBtn: HTMLElement | null = null;
        for (const b of buttons) {
            if (b.dataset.flatIndex === String(current)) fromBtn = b;
        }
        if (!fromBtn) return null;

        const fromRect = fromBtn.getBoundingClientRect();
        const fromCx = fromRect.left + fromRect.width / 2;
        const fromCy = fromRect.top + fromRect.height / 2;

        // Tolerance — a couple px of slop so subpixel rendering doesn't
        // disqualify items that are visually in the right direction.
        const TOL = 1;
        let best: { idx: number; dist: number } | null = null;

        for (const btn of buttons) {
            const idx = Number(btn.dataset.flatIndex);
            if (idx === current) continue;
            const r = btn.getBoundingClientRect();
            const cx = r.left + r.width / 2;
            const cy = r.top + r.height / 2;
            const dx = cx - fromCx;
            const dy = cy - fromCy;
            if (direction === 'right' && dx <= TOL) continue;
            if (direction === 'left' && dx >= -TOL) continue;
            if (direction === 'down' && dy <= TOL) continue;
            if (direction === 'up' && dy >= -TOL) continue;
            const dist =
                direction === 'left' || direction === 'right'
                    ? Math.abs(dx) + Math.abs(dy) * 3
                    : Math.abs(dy) + Math.abs(dx) * 3;
            if (!best || dist < best.dist) best = { idx, dist };
        }

        return best?.idx ?? null;
    };

    const handleKeyDown = (e: React.KeyboardEvent) => {
        if (!isOpen) return;
        // Esc is picker-specific (gated on hasExplicitSelection); arrows and
        // Enter delegate to the shared nav hook, which triple-stops captured
        // keys so ReactFlow's native listeners never see them.
        if (e.key === 'Escape') {
            if (hasExplicitSelection) {
                // only swallow Esc when we actually consume it
                e.preventDefault();
                e.stopPropagation();
                e.nativeEvent.stopImmediatePropagation();
                onClose();
            }
            return;
        }
        handleNavKeyDown(e);
    };

    // -------- Closed state: clickable badge + explicit Change button --------
    // Two interactive surfaces: the badge itself (the user already knows
    // they can click the name they're trying to change) AND a clearly-styled
    // Change button next to it (telegraphs "open the picker" with text +
    // chevron, in case the badge's clickability isn't obvious).
    if (!isOpen) {
        const tierLabel = getOptionTierLabel?.(selectedIndex);
        const totalOps = visibleIndices.length;
        return (
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <label className="text-xs text-muted-foreground uppercase tracking-wider flex-shrink-0">
                    Action
                </label>
                <button
                    type="button"
                    onClick={onOpen}
                    title="Click to change action"
                    className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-card shadow-sm dark:shadow-none dark:bg-foreground/[0.06] border border-border dark:border-white/[0.12] hover:bg-muted dark:hover:bg-foreground/[0.10] hover:border-muted-foreground/40 dark:hover:border-white/[0.25] text-sm text-foreground font-medium min-w-0 cursor-pointer"
                >
                    {NodeIcon && (
                        <BrandIcon Icon={NodeIcon} iconColor={nodeIconColor} className="h-4 w-4 flex-shrink-0" />
                    )}
                    {getOptionIsTrigger(selectedIndex) && (
                        <Zap className="h-3.5 w-3.5 text-amber-600 dark:text-amber-400 flex-shrink-0" />
                    )}
                    <span className="truncate">{optionLabels[selectedIndex]}</span>
                    {tierLabel && <TierLabel label={tierLabel} />}
                </button>
                <button
                    type="button"
                    onClick={onOpen}
                    title={`Browse all ${totalOps} action${totalOps === 1 ? '' : 's'}`}
                    className="flex items-center gap-1.5 text-xs text-foreground/80 hover:text-foreground px-2 py-1 rounded hover:bg-foreground/[0.06] flex-shrink-0"
                >
                    <Pencil className="h-3 w-3" />
                    <span>Change Action</span>
                    <span className="text-muted-foreground dark:text-zinc-500">·</span>
                    <span className="text-muted-foreground dark:text-zinc-500">
                        {totalOps} {totalOps === 1 ? 'action' : 'actions'} available
                    </span>
                </button>
                {/* `headerAction` (the AI Fill button) is intentionally NOT
                    rendered here — operation-only autofill competes with the
                    user's intent to change action manually, and the field-level
                    AI Fill controls cover the per-field autofill case. */}
            </div>
        );
    }

    // -------- Open state: full-bleed multi-column tile picker --------
    // Detect whether this node has any triggers so we can phrase the prompt
    // appropriately.
    const hasTriggers = grouped.some((sec) => sec.key === TRIGGER_SECTION_KEY);

    return (
        <div className="flex flex-col">
            {/* Top chrome: a large search input that doubles as the prompt — the
                descriptive placeholder replaces the old instructional banner so
                the picker reads as one clear "pick an action" affordance. */}
            <div className="flex items-center gap-2.5 px-2 py-1">
                <Search className="h-5 w-5 text-muted-foreground flex-shrink-0" />
                <input
                    ref={inputRef}
                    data-operation-search
                    type="text"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    /* Handle keyboard nav directly on the input — wrapper
                       onKeyDown fires too late when the input has focus, and
                       we need stopPropagation so Esc doesn't bubble to the
                       sidebar's close-on-Esc handler. */
                    onKeyDown={handleKeyDown}
                    placeholder={hasTriggers
                        ? 'Search for an action or trigger this node should run…'
                        : 'Search for an action this node should perform…'}
                    className="flex-1 bg-transparent text-base text-foreground placeholder:text-[hsl(var(--placeholder))] focus:outline-none py-1"
                />
                {/* Intentionally NOT rendering `headerAction` (the AI Fill
                    button) here — picking an operation manually is the entire
                    point of the open state, and the AI button competes with
                    the search input for attention. It still appears in the
                    closed state, where the user has already chosen and might
                    want to delegate the field-fill step. */}
                {hasExplicitSelection && (
                    <button
                        type="button"
                        onClick={onClose}
                        className="flex items-center gap-1 px-2 py-1 rounded text-xs text-foreground/80 hover:text-foreground bg-card dark:bg-foreground/[0.04] hover:bg-muted dark:hover:bg-foreground/[0.08] border border-border dark:border-white/[0.08] hover:border-muted-foreground/40 dark:hover:border-white/[0.15] flex-shrink-0"
                        title="Cancel (Esc)"
                    >
                        <X className="h-3 w-3" />
                        <span>Cancel</span>
                    </button>
                )}
            </div>

            {/* Keyboard hints — at the top so they stay visible on long lists */}
            <div className="px-1 mt-2 pb-2 border-b border-border dark:border-white/[0.06] text-[10px] text-muted-foreground dark:text-zinc-500 flex items-center gap-3 flex-shrink-0">
                <span>
                    <kbd className="px-1 py-0.5 bg-foreground/[0.06] rounded">↑↓←→</kbd> navigate
                </span>
                <span>
                    <kbd className="px-1 py-0.5 bg-foreground/[0.06] rounded">↵</kbd> select
                </span>
                {hasExplicitSelection && (
                    <span>
                        <kbd className="px-1 py-0.5 bg-foreground/[0.06] rounded">esc</kbd> cancel
                    </span>
                )}
            </div>

            {/* Categories laid out as fixed-width columns in a CSS grid so the
                column boundaries line up vertically across rows. The column
                width is the widest op label across all categories (measured
                in JS — see `columnWidth` above), so no op text needs to wrap.
                Columns wrap onto new rows when the panel can't fit them all. */}
            <div
                ref={gridContainerRef}
                className="flex-1 overflow-y-auto scrollbar-subtle py-2"
            >
                {filteredSections.length === 0 ? (
                    <div className="px-2 py-12 text-center text-sm text-muted-foreground dark:text-zinc-500">
                        No actions match "{query}"
                    </div>
                ) : (
                    /* CSS multi-column flow: sections cascade top-to-bottom
                       within a column, then continue at the top of the next.
                       `column-width` makes the browser auto-pack as many
                       fixed-width columns as fit. `break-inside-avoid` on
                       each section keeps a category from splitting across
                       columns. */
                    <div
                        style={{
                            columnWidth: `${columnWidth}px`,
                            columnGap: '16px',
                        }}
                    >
                        {filteredSections.map((sec) => {
                            const isTriggers = sec.key === TRIGGER_SECTION_KEY;
                            return (
                                <section
                                    key={sec.key}
                                    className="mb-3 break-inside-avoid"
                                >
                                    <div
                                        className={`px-1 mb-1.5 text-[11px] font-semibold uppercase tracking-wider flex items-center gap-1.5 ${
                                            isTriggers ? 'text-amber-600 dark:text-amber-400' : 'text-muted-foreground'
                                        }`}
                                    >
                                        {isTriggers && <Zap className="h-3 w-3" />}
                                        <span>{sec.label}</span>
                                        <span className="text-muted-foreground dark:text-zinc-500 font-normal normal-case tracking-normal">
                                            {sec.indices.length}
                                        </span>
                                    </div>
                                    <div className="flex flex-col gap-px">
                                        {sec.indices.map((idx) => {
                                            const flatPos = flatIndices.indexOf(idx);
                                            const isHighlighted = flatPos === highlightedIndex;
                                            const isSelected = idx === selectedIndex;
                                            const tierLabel = getOptionTierLabel?.(idx);
                                            return (
                                                <button
                                                    key={idx}
                                                    type="button"
                                                    data-flat-index={flatPos}
                                                    onClick={() => {
                                                        onSelect(idx);
                                                        onClose();
                                                    }}
                                                    onMouseEnter={() => setHighlightedIndex(flatPos)}
                                                    onMouseDown={(e) => e.preventDefault()}
                                                    className={`relative px-2 py-1 rounded text-left text-[12px] leading-tight whitespace-nowrap ${
                                                        isHighlighted
                                                            ? 'bg-foreground/[0.10] text-foreground'
                                                            : isSelected
                                                              ? 'bg-foreground/[0.05] text-foreground'
                                                              : 'text-muted-foreground hover:bg-foreground/[0.04] hover:text-foreground'
                                                    }`}
                                                >
                                                    <span className="flex items-center gap-1.5">
                                                        {isSelected && (
                                                            <span className="h-1 w-1 rounded-full bg-foreground/80 flex-shrink-0" />
                                                        )}
                                                        {NodeIcon && (
                                                            <BrandIcon
                                                                Icon={NodeIcon}
                                                                iconColor={nodeIconColor}
                                                                className="h-3.5 w-3.5 flex-shrink-0"
                                                            />
                                                        )}
                                                        <span>{optionLabels[idx]}</span>
                                                        {tierLabel && (
                                                            <span className="flex-shrink-0">
                                                                <TierLabel label={tierLabel} />
                                                            </span>
                                                        )}
                                                    </span>
                                                </button>
                                            );
                                        })}
                                    </div>
                                </section>
                            );
                        })}
                    </div>
                )}
            </div>

        </div>
    );
}
