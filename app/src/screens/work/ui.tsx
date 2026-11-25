// The small pieces Work's views share: a list's rows and counts, its top (an action row, then a search), a section's
// header, the two resizable columns (the list, and the panel beside the main pane, each dragged from its edge and
// remembered on this device), a close button, and a choice's mark. A page's head is the shell's (`PageHead`).
import { useEffect, useRef, useState, type ComponentType, type CSSProperties, type HTMLAttributes, type KeyboardEvent as ReactKeyboardEvent, type ReactNode, type RefObject } from 'react';
import { AtSign, Check, Plus, Search, X } from 'lucide-react';
import { HAIRLINE } from '@/ui/primitives';
import { SearchClearButton } from '@/ui/SearchClearButton';
import { createPanelWidth } from '@/ui/panelWidth';
import { ResizeEdge } from '@/ui/ResizeEdge';
import { TAP_ROW } from '@/ui/sidebarParts';
import { cn } from '@/ui/utils';
import { Tip } from './tooltip';

export const LIST_ROW = `flex w-full items-center gap-2.5 rounded-lg pl-2 pr-2 text-left transition-colors [@media(hover:hover)]:hover:bg-foreground/[0.04] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring ${TAP_ROW}`;
export const LIST_CURRENT = 'bg-foreground/[0.07] hover:bg-foreground/[0.07]';
/** A round icon button; on a phone a finger's 40px, whatever size it's drawn at on a laptop. */
export const ICON_BUTTON =
    'grid h-8 w-8 shrink-0 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-foreground/[0.05] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring max-md:h-10 max-md:w-10';

/** The list column (channels, agents, DMs) and the panel beside the main pane (a thread, a profile, the members). */
export const LIST_COLUMN = createPanelWidth({ key: 'nc-work-list', initial: 280, min: 220, max: 420 });
export const SIDE_PANEL = createPanelWidth({ key: 'nc-work-panel', initial: 420, min: 340, max: 760 });

export function Count({ n }: { n: number }) {
    return <span data-count className="grid h-[18px] min-w-[18px] place-items-center rounded-full bg-foreground px-1.5 text-[11px] font-semibold tabular-nums leading-none text-background">{n}</span>;
}

/** How many messages @-mention you: an @ before the count, so it reads apart from the unread count beside it. */
export function MentionCount({ n }: { n: number }) {
    return (
        <span aria-label={`${n} mention${n === 1 ? '' : 's'} of you`} data-count className="inline-flex h-[18px] shrink-0 items-center gap-px rounded-full bg-foreground pl-1 pr-1.5 text-[11px] font-semibold tabular-nums leading-none text-background">
            <AtSign aria-hidden className="h-3 w-3" strokeWidth={2.5} />
            {n}
        </span>
    );
}

/** The top of a column's list: its action row held at the top while the list scrolls, 8px above its search. On a phone
 *  its card, like the search, keeps the screen's 16px edge, where the space's mark and the rows' faces are. */
export const LIST_TOP = 'sticky top-0 z-10 -mx-2 bg-background px-2 pb-2 max-md:px-4';

/** A column's search pill (a field, or Home's button to the palette). On a phone it keeps the 16px edge and grows to a
 *  finger's height; on a laptop its glyph centres on the rows' faces below it. */
export const FIND_PILL = cn(
    'mb-2 flex h-9 w-full items-center gap-2 rounded-full border pl-3 text-muted-foreground transition-colors hover:bg-foreground/[0.03] sm:pl-[15px] max-md:mx-2 max-md:h-10 max-md:w-[calc(100%-16px)]',
    HAIRLINE
);

/** A list's action (New agent, Invite people): a soft card, a round tile holding its glyph, then its label. The glyph's
 *  ink is softened as a whole, never stroke by stroke, so where its strokes cross reads as one line. On a laptop its tile
 *  centres on the rows' faces below it (8px in, as a row's face is), so the folded list's column is one line. */
export function ActionRow({
    icon: Icon,
    iconSize = 16,
    label,
    onClick,
    pressed,
    keys,
}: {
    icon: ComponentType<{ className?: string; strokeWidth?: number; style?: CSSProperties }>;
    iconSize?: 16 | 20;
    label: string;
    onClick: () => void;
    pressed?: boolean;
    /** Its keyboard shortcut, for assistive tech (never shown). */
    keys?: string;
}) {
    return (
        <button
            type="button"
            onClick={onClick}
            aria-pressed={pressed}
            aria-keyshortcuts={keys}
            className={cn(
                'group flex h-10 w-full items-center gap-3 rounded-lg bg-foreground/[0.04] pl-1 pr-2 text-left sm:pl-2 text-[14px] text-foreground/85 transition-colors hover:bg-foreground/[0.07] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring',
                pressed && 'bg-foreground/[0.08] text-foreground'
            )}
        >
            <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-foreground/[0.06] text-foreground opacity-85 transition-opacity group-hover:opacity-100">
                <Icon className="shrink-0" style={{ width: iconSize, height: iconSize }} strokeWidth={1.75} />
            </span>
            {label}
        </button>
    );
}

/** A column's search (Find an agent, Find a person): a pill with its glyph, clearing with ×; 8px above the list. */
export function FindField({
    value,
    onChange,
    placeholder,
    inputRef,
    onKeyDown,
    keys,
}: {
    value: string;
    onChange: (value: string) => void;
    placeholder: string;
    inputRef?: RefObject<HTMLInputElement | null>;
    onKeyDown?: (e: ReactKeyboardEvent<HTMLInputElement>) => void;
    /** Its keyboard shortcut, for assistive tech (never shown). */
    keys?: string;
}) {
    const ownRef = useRef<HTMLInputElement>(null);
    const ref = inputRef ?? ownRef;
    return (
        <label className={cn(FIND_PILL, 'pr-1 focus-within:border-foreground/25 focus-within:bg-foreground/[0.03]')}>
            <Search className="h-4 w-4 shrink-0" strokeWidth={1.8} />
            <input
                ref={ref}
                value={value}
                onChange={(e) => onChange(e.target.value)}
                onKeyDown={onKeyDown}
                placeholder={placeholder}
                aria-label={placeholder}
                aria-keyshortcuts={keys}
                autoComplete="off"
                spellCheck={false}
                enterKeyHint="search"
                className="min-w-0 flex-1 bg-transparent text-[13.5px] text-foreground outline-none placeholder:text-muted-foreground max-md:text-[16px]"
            />
            <SearchClearButton value={value} onClear={() => onChange('')} inputRef={ref} />
        </label>
    );
}

/** A row that scrolls sideways inside itself (`SidewaysRow` draws it, with its soft edges). */
const SIDEWAYS = 'overflow-x-auto scrollbar-hide';

/** Which edges of a sideways scroller hide something past them, followed as it scrolls and as it or its items resize;
 *  `deps` say when to look again (what's in it changed). */
export function useHiddenSides(ref: RefObject<HTMLElement | null>, enabled = true, deps: readonly unknown[] = []): { left: boolean; right: boolean } {
    const [sides, setSides] = useState({ left: false, right: false });
    useEffect(() => {
        const el = ref.current;
        if (!el || !enabled) return setSides({ left: false, right: false });
        const look = () => {
            const left = el.scrollLeft > 2;
            const right = el.scrollLeft + el.clientWidth < el.scrollWidth - 2;
            setSides((was) => (was.left === left && was.right === right ? was : { left, right }));
        };
        look();
        el.addEventListener('scroll', look, { passive: true });
        const sizes = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(look);
        sizes?.observe(el);
        if (el.firstElementChild) sizes?.observe(el.firstElementChild);
        return () => {
            el.removeEventListener('scroll', look);
            sizes?.disconnect();
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps -- `deps` name what's in it
    }, [ref, enabled, ...deps]);
    return sides;
}

// The row's own pills fade into the page at an edge hiding more; a light frost over that edge's last 24px.
const FADE = {
    left: '[mask-image:linear-gradient(to_right,transparent,black_40px)]',
    right: '[mask-image:linear-gradient(to_right,black_calc(100%-40px),transparent)]',
    both: '[mask-image:linear-gradient(to_right,transparent,black_40px,black_calc(100%-40px),transparent)]',
};
const FROST = 'pointer-events-none absolute inset-y-0 z-[1] w-6 backdrop-blur-[3px] transition-opacity duration-200 ease-out motion-reduce:transition-none';

/** A row of pills or tabs that scrolls sideways inside itself where it can't fit (a phone): each edge softens while
 *  something's hidden past it, the pills fading into the page under a light frost, so a person can tell there's more
 *  that way; the soft edges never take a tap. `enabled` false draws the plain row, nothing scrolling or fading (a
 *  laptop's, which folds its pills instead). `scrollRef`: the scroller, for a caller that measures it too. */
export function SidewaysRow({
    enabled = true,
    deps = [],
    scrollRef,
    className,
    children,
    ...rest
}: { enabled?: boolean; deps?: readonly unknown[]; scrollRef?: RefObject<HTMLDivElement | null>; className?: string; children: ReactNode } & Omit<HTMLAttributes<HTMLDivElement>, 'className' | 'children'>) {
    const own = useRef<HTMLDivElement>(null);
    const ref = scrollRef ?? own;
    const { left, right } = useHiddenSides(ref, enabled, deps);
    if (!enabled)
        return (
            <div ref={ref} className={className} {...rest}>
                {children}
            </div>
        );
    return (
        <div className="relative min-w-0">
            <div ref={ref} data-more-left={left || undefined} data-more-right={right || undefined} className={cn(className, SIDEWAYS, left && right ? FADE.both : left ? FADE.left : right && FADE.right)} {...rest}>
                {children}
            </div>
            <span aria-hidden data-edge="left" className={cn(FROST, 'left-0 [mask-image:linear-gradient(to_right,black,transparent)]', left ? 'opacity-100' : 'opacity-0')} />
            <span aria-hidden data-edge="right" className={cn(FROST, 'right-0 [mask-image:linear-gradient(to_left,black,transparent)]', right ? 'opacity-100' : 'opacity-0')} />
        </div>
    );
}

/** A section's name over its rows, its add button's edge on the rows' right edge, the button named by its tooltip. */
export function SectionHeader({ label, onAdd, addLabel }: { label: string; onAdd?: () => void; addLabel?: string }) {
    return (
        <div className="flex h-8 items-center gap-1.5 pl-2.5 pt-1 max-md:pl-2">
            <span data-rail-text className="min-w-0 flex-1 truncate text-[13px] font-medium text-muted-foreground">{label}</span>
            {onAdd && (
                <Tip label={addLabel}>
                    <button type="button" onClick={onAdd} aria-label={addLabel} className="grid h-6 w-6 shrink-0 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground max-md:-m-2 max-md:h-10 max-md:w-10">
                        <Plus className="h-4 w-4" strokeWidth={2} />
                    </button>
                </Tip>
            )}
        </div>
    );
}

/** The panel beside the main pane: its width shared by every panel, dragged from its left edge. On a phone it's the
 *  whole screen. */
export function PanelFrame({ children, phone, label = 'Resize the panel' }: { children: ReactNode; phone?: boolean; label?: string }) {
    const width = SIDE_PANEL.useWidth();
    if (phone) return <aside className="flex min-h-0 w-full flex-1 flex-col">{children}</aside>;
    return (
        <aside className={cn('relative flex shrink-0 flex-col border-l', HAIRLINE)} style={{ width }}>
            <ResizeEdge panel={SIDE_PANEL} side="left" label={label} />
            {children}
        </aside>
    );
}

/** A choice's mark: a rounded square, checked, for a yes or no or one of several (a checkbox); a dot for one of a set
 *  (a radio). */
export function ChoiceMark({ on, radio, className }: { on: boolean; radio?: boolean; className?: string }) {
    return (
        <span
            aria-hidden
            className={cn('grid h-4 w-4 shrink-0 place-items-center border transition-colors', radio ? 'rounded-full' : 'rounded', on ? 'border-foreground bg-foreground text-background' : 'border-foreground/25 bg-foreground/[0.04]', className)}
        >
            {on && (radio ? <span className="h-1.5 w-1.5 rounded-full bg-background" /> : <Check className="h-3 w-3" strokeWidth={3} />)}
        </span>
    );
}

export function CloseButton({ onClose, label = 'Close' }: { onClose: () => void; label?: string }) {
    return (
        <button type="button" aria-label={label} onClick={onClose} className={cn(ICON_BUTTON, 'ml-auto h-7 w-7')}>
            <X className="h-4 w-4" />
        </button>
    );
}
