// Work's list column on a laptop, and the rail it folds to where the conversation needs the room. One element in every
// state: docked (the full list beside what's open), folded (that same list laid out at its full width and clipped to
// its faces, the actions and search as circles), and open over the conversation (the folded list widening in place),
// so no state change moves a face. Whether there's room is measured on Work's own pane, never the window: the full list
// stays while the pane it leaves keeps LIST_ROOM, and comes back from LIST_OPENS. Folding it by choice ("Hide agents")
// gives the rail at any width, remembered on this device.
//
// What each gesture on the rail means, and what it does:
// - passing over it on the way elsewhere means nothing: it opens only once the pointer rests on it (useRestToOpen), and
//   leaving closes it after a grace, so a diagonal move onto a name keeps it;
// - clicking a face means "go there": its conversation opens and the rail stays folded, that face current; a row of
//   the open list does the same and the list folds;
// - "Show agents" docks the list again where there's room (clearing a fold by choice), else opens it over the
//   conversation until Esc or a click away, as the search does (with the search focused);
// - Esc, or a click anywhere else (which still does what it would have), closes the open list.
// It has no shortcut: ⌘\ stays the app sidebar's.
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent, type ReactNode, type RefObject } from 'react';
import { PanelLeftClose, PanelLeftOpen } from 'lucide-react';
import { HAIRLINE } from '@/ui/primitives';
import { ResizeEdge } from '@/ui/ResizeEdge';
import { cn } from '@/ui/utils';
import { RailTip, tipBeside, useRailTips } from './railTip';
import { LIST_COLUMN } from './ui';

/** The pane the full list leaves must keep this much: the subagents card beside a readable text column. */
export const LIST_ROOM = 924;
/** Folded for want of room, it opens again only from here, so a width at the edge never flickers. */
export const LIST_OPENS = 948;
/** The folded rail's width: its faces' column. */
export const RAIL_WIDTH = 64;
/** How long the pointer rests on the rail before it opens, and the grace after it leaves. */
export const REST_MS = 200;
export const GRACE_MS = 300;

/** Whether the full list has room, given whether it had (`room`) and the pane it would leave (`withList`; 0 before
 *  it's measured, which changes nothing). */
export function nextRoom(room: boolean, withList: number): boolean {
    if (!withList) return room;
    return room ? withList >= LIST_ROOM : withList >= LIST_OPENS;
}

/** An element's width as it changes; 0 until it's measured (and where nothing lays out). */
export function useMeasuredWidth<T extends HTMLElement>(): [RefObject<T | null>, number] {
    const ref = useRef<T>(null);
    const [width, setWidth] = useState(0);
    useLayoutEffect(() => {
        const el = ref.current;
        if (!el || typeof ResizeObserver === 'undefined') return;
        setWidth(el.getBoundingClientRect().width);
        const watch = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
        watch.observe(el);
        return () => watch.disconnect();
    }, []);
    return [ref, width];
}

/** The room rule, live: whether the full list has room beside the pane (`pane`, measured), and so whether a list that
 *  `folds` shows the rail (also when `chosen`: folded by choice). */
export function useListRoom(pane: number, listWidth: number, folds: boolean, chosen: boolean): { room: boolean; railed: boolean } {
    const [room, setRoom] = useState(true);
    const railed = folds && (!room || chosen);
    useLayoutEffect(() => {
        // The pane the full list would leave: today's pane, give or take the list's width over the rail's.
        const next = nextRoom(room, pane ? pane + (railed ? RAIL_WIDTH : listWidth) - listWidth : 0);
        if (next !== room) setRoom(next);
    }, [pane, railed, listWidth, room]);
    return { room, railed };
}

const FOLDED_KEY = 'nc-work-list-folded';

/** Whether the list was folded by choice, remembered on this device. Without storage (a private window, blocked) it
 *  starts unfolded each visit and still folds for the visit. */
export function useFoldedByChoice(): [boolean, (folded: boolean) => void] {
    const [folded, setFolded] = useState(false);
    useEffect(() => {
        try {
            setFolded(window.localStorage.getItem(FOLDED_KEY) === '1');
        } catch {
            // No storage: the room rule alone decides.
        }
    }, []);
    const choose = (next: boolean) => {
        setFolded(next);
        try {
            if (next) window.localStorage.setItem(FOLDED_KEY, '1');
            else window.localStorage.removeItem(FOLDED_KEY);
        } catch {
            // Chosen for this visit only.
        }
    };
    return [folded, choose];
}

/** How the folded rail reads a pointer. Passing over it opens nothing: it opens once the pointer has rested on it (REST_MS
 *  with no move past a few pixels). Leaving closes what resting opened after GRACE_MS. `hush` closes it and stays quiet
 *  while the pointer is still on it, for a click or Esc that meant "not now". Only a mouse rests. */
export function useRestToOpen() {
    const [open, setOpen] = useState<null | 'rest' | 'click'>(null);
    const state = useRef({ open, timer: undefined as number | undefined, at: null as { x: number; y: number } | null, quiet: false, inside: false });
    state.current.open = open;
    // The handlers read `open` through the ref, so they stay the same functions from render to render.
    const actions = useMemo(() => {
        const s = state.current;
        const clear = () => window.clearTimeout(s.timer);
        const arm = () => {
            clear();
            s.timer = window.setTimeout(() => setOpen((o) => o ?? 'rest'), REST_MS);
        };
        // Only the rail's own elements count: React bubbles a portal's events (a tooltip's, a menu's) to it.
        const mouse = (e: ReactPointerEvent) => e.pointerType === 'mouse' && (e.currentTarget as Node).contains(e.target as Node);
        return {
            show: (by: 'rest' | 'click') => {
                clear();
                s.quiet = false;
                setOpen(by);
            },
            hide: () => {
                clear();
                setOpen(null);
            },
            hush: () => {
                clear();
                s.quiet = s.inside;
                setOpen(null);
            },
            quiet: () => s.quiet,
            handlers: {
                onPointerEnter: (e: ReactPointerEvent) => {
                    if (!mouse(e)) return;
                    s.inside = true;
                    clear();
                    s.at = { x: e.clientX, y: e.clientY };
                    if (!s.open && !s.quiet) arm();
                },
                onPointerMove: (e: ReactPointerEvent) => {
                    if (!mouse(e) || s.open || s.quiet) return;
                    if (!s.at || Math.hypot(e.clientX - s.at.x, e.clientY - s.at.y) > 3) {
                        s.at = { x: e.clientX, y: e.clientY };
                        arm();
                    }
                },
                onPointerLeave: (e: ReactPointerEvent) => {
                    if (!mouse(e)) return;
                    s.inside = false;
                    clear();
                    s.quiet = false;
                    if (s.open === 'rest') s.timer = window.setTimeout(() => setOpen(null), GRACE_MS);
                },
            },
        };
    }, []);
    useEffect(() => () => window.clearTimeout(state.current.timer), []);
    return { open, ...actions };
}

/** The rail's panel glyphs (Show, Hide), sized as the app sidebar's own toggle: a 20px glyph at 1.6 in a 36px hit
 *  area, hovering as a 32px circle. Muted: chrome, not an action. */
const GLYPH = 'work-rail-glyph grid h-9 w-9 shrink-0 place-items-center rounded-full text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none';

/** What it names a row by, for its tip: its name, then what it's doing. */
function tipText(row: HTMLElement): [string, string | undefined] {
    const own = row.getAttribute('data-rail-tip');
    if (own) return [own, undefined];
    const text = row.querySelector('[data-rail-text]');
    const name = text?.querySelector('[data-rail-name], [data-name]')?.textContent ?? text?.children[0]?.textContent ?? row.textContent ?? '';
    return [name, text?.children[1]?.textContent ?? undefined];
}

export function ListColumn({
    rail,
    docked,
    head,
    children,
    showLabel,
    hideLabel,
    onShow,
    onFold,
}: {
    /** Whether this view's list can fold (DMs, Agents; never Home or Resources). */
    rail: boolean;
    /** The full list beside what's open; else the folded rail. */
    docked: boolean;
    /** Its header, given the fold glyph for its row's end where it has one. */
    head: (end: ReactNode) => ReactNode;
    children: ReactNode;
    showLabel: string;
    hideLabel: string;
    /** Folded by choice where there's room: showing it docks it again. */
    onShow?: () => void;
    onFold: () => void;
}) {
    const width = LIST_COLUMN.useWidth();
    const resizing = LIST_COLUMN.useResizing();
    const intent = useRestToOpen();
    const { hide, hush, show, quiet } = intent;
    const panel = useRef<HTMLElement>(null);
    const tips = useRailTips();
    const { hide: hideTip } = tips;
    const tipRow = useRef<HTMLElement | null>(null);
    const folded = rail && !docked;
    const floating = folded && !!intent.open;
    const expanded = !folded || floating;
    // Folded under a resting pointer, it stays folded until the pointer leaves.
    const wasDocked = useRef(docked);
    useLayoutEffect(() => {
        if (wasDocked.current === docked) return;
        wasDocked.current = docked;
        if (!docked) hush();
    }, [docked, hush]);
    useEffect(() => {
        if (!floating) return;
        const down = (e: PointerEvent) => {
            const target = e.target as Element;
            // Not a backdrop: the click that closes it still lands where it was aimed. A menu the list opened is its own.
            if (panel.current?.contains(target) || target.closest?.('[data-radix-popper-content-wrapper]')) return;
            hide();
        };
        const key = (e: KeyboardEvent) => {
            // An Esc a menu the list opened already took (Radix prevents it) closes that menu alone.
            if (e.key !== 'Escape' || e.defaultPrevented) return;
            if (document.activeElement instanceof HTMLElement && panel.current?.contains(document.activeElement)) document.activeElement.blur();
            hush();
        };
        document.addEventListener('pointerdown', down, true);
        window.addEventListener('keydown', key);
        return () => {
            document.removeEventListener('pointerdown', down, true);
            window.removeEventListener('keydown', key);
        };
    }, [floating, hide, hush]);
    useEffect(() => {
        if (expanded) hideTip();
    }, [expanded, hideTip]);

    const rowOf = (target: EventTarget | null) => (target instanceof Element ? target.closest<HTMLElement>('li > button:first-child, [data-rail-tip]') : null);
    const edge = () => panel.current!.getBoundingClientRect().right;
    const tipOf = (row: HTMLElement) => {
        const [text, state] = tipText(row);
        return tipBeside(row, edge(), 'right', text, state);
    };
    // Up and down, Home and End, between the rows of a list that doesn't move them itself (Agents does, first).
    useEffect(() => {
        const el = panel.current;
        if (!el) return;
        const onKey = (e: KeyboardEvent) => {
            if (e.defaultPrevented || !['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(e.key)) return;
            const rows = [...el.querySelectorAll<HTMLButtonElement>('li > button:first-child')];
            const at = rows.indexOf(e.target as HTMLButtonElement);
            if (at < 0) return;
            e.preventDefault();
            rows[e.key === 'Home' ? 0 : e.key === 'End' ? rows.length - 1 : Math.min(rows.length - 1, Math.max(0, at + (e.key === 'ArrowDown' ? 1 : -1)))]?.focus();
        };
        el.addEventListener('keydown', onKey);
        return () => el.removeEventListener('keydown', onKey);
    }, []);

    const fold = (
        <button
            type="button"
            aria-label={hideLabel}
            onClick={() => (docked ? onFold() : hush())}
            onPointerEnter={(e) => tips.hover(tipBeside(e.currentTarget, edge(), 'right', hideLabel))}
            onPointerLeave={() => tips.hide()}
            onFocus={(e) => e.currentTarget.matches(':focus-visible') && tips.focus(tipBeside(e.currentTarget, edge(), 'right', hideLabel))}
            onBlur={() => tips.hide()}
            className={cn(GLYPH, 'ml-auto -mr-1')}
        >
            <span>
                <PanelLeftClose className="h-5 w-5" strokeWidth={1.6} />
            </span>
        </button>
    );

    return (
        <aside className={cn('work-rail-slot relative shrink-0', resizing && 'work-rail-resizing')} style={{ width: folded ? RAIL_WIDTH : width }} data-testid="work-list">
            <style href="work-rail" precedence="default">
                {RAIL_CSS}
            </style>
            <nav
                ref={panel}
                aria-label="The list"
                data-expanded={expanded}
                data-docked={!folded}
                className={cn('work-rail absolute inset-y-0 left-0 flex flex-col overflow-hidden border-r bg-background', floating && 'z-40', HAIRLINE)}
                style={{ width: expanded ? width : RAIL_WIDTH, boxShadow: floating ? '12px 0 32px -12px rgb(0 0 0 / 0.35)' : undefined }}
                {...(folded ? intent.handlers : {})}
                onPointerLeave={(e) => {
                    if (folded) intent.handlers.onPointerLeave(e);
                    tipRow.current = null;
                    tips.hide();
                }}
                // After a click, when resting no longer opens it until the pointer leaves, a face says who it is.
                onPointerOver={(e) => {
                    if (expanded || !quiet()) return;
                    const row = rowOf(e.target);
                    if (row === tipRow.current) return;
                    tipRow.current = row;
                    if (row) tips.hover(tipOf(row));
                    else tips.hide();
                }}
                onPointerDown={() => tips.press()}
                onFocus={(e) => {
                    if (!folded) return;
                    // Its search, or a menu it opened (the space's, a row's), holds it open as Show does: an open menu
                    // takes the pointer from everything else, so the pointer would seem to have left the list.
                    if (e.target.matches('input') || e.target.closest('[role="menu"]')) return show('click');
                    const row = rowOf(e.target);
                    if (!expanded && row && e.target.matches(':focus-visible')) tips.focus(tipOf(row));
                }}
                onBlur={() => tips.hide()}
                onClickCapture={(e) => {
                    if (!folded || !(e.target as Element).closest('li > button:first-child, .sticky > button')) return;
                    hush();
                    tips.hide();
                }}
            >
                {rail && (
                    // The header row's slot, folded: shows the list, on the faces' line and first in the tab order. It
                    // lies over the header's start, so only its button takes the pointer, and only while it shows.
                    <div className="pointer-events-none absolute left-0 top-0 grid h-12 place-items-center" style={{ width: RAIL_WIDTH }}>
                        <button
                            type="button"
                            data-rail-tip={showLabel}
                            aria-label={showLabel}
                            tabIndex={expanded ? -1 : 0}
                            onClick={(e) => {
                                tips.hide();
                                if (onShow) return onShow();
                                show('click');
                                // From the keyboard, on into the list: its search is first.
                                if (e.detail === 0) window.setTimeout(() => panel.current?.querySelector<HTMLInputElement>('label > input')?.focus(), 0);
                            }}
                            className={cn('work-rail-show pointer-events-auto', GLYPH)}
                        >
                            <span>
                                <PanelLeftOpen className="h-5 w-5" strokeWidth={1.6} />
                            </span>
                        </button>
                    </div>
                )}
                <div className="work-rail-list flex min-h-0 flex-1 flex-col" style={{ width: width - 1 }}>
                    {head(rail && expanded ? fold : null)}
                    <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-6 scrollbar-subtle">{children}</div>
                </div>
            </nav>
            {!folded && <ResizeEdge panel={LIST_COLUMN} label="Resize the list" />}
            <RailTip tip={tips.tip} />
        </aside>
    );
}

const F = '.work-rail[data-expanded="false"] .work-rail-list';
const EASE = 'cubic-bezier(0.32, 0.72, 0, 1)';
const PLUS =
    "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='1.8' stroke-linecap='round'%3E%3Cpath d='M12 5v14M5 12h14'/%3E%3C/svg%3E\")";

/** The rail's look: the column gliding between states; folded, only the faces, their counts (on the face) and the two
 *  actions as matching circles with a hairline under them, every row where the full list puts it. */
export const RAIL_CSS = `.work-rail, .work-rail-slot { transition: width 220ms ${EASE} }
.work-rail-resizing, .work-rail-resizing .work-rail { transition: none }
.work-rail-glyph > span { display: grid; place-items: center; width: 32px; height: 32px; border-radius: 9999px; transition: background-color 120ms ease, box-shadow 120ms ease }
.work-rail-glyph:hover > span { background-color: hsl(var(--foreground) / 0.05) }
.work-rail-glyph:focus-visible > span { box-shadow: 0 0 0 2px hsl(var(--ring)) }
.work-rail-list [data-space-head], .work-rail-show { transition: opacity 160ms ease, visibility 160ms }
${F} [data-space-head], .work-rail[data-expanded="true"] .work-rail-show { opacity: 0; visibility: hidden; pointer-events: none }
${F} [data-rail-text] { opacity: 0; pointer-events: none }
${F} [data-rail-hide], ${F} [role="group"], ${F} p { visibility: hidden }
${F} button { background-color: transparent !important; box-shadow: none !important }
${F} .sticky > button { font-size: 0 }
${F} li > button:first-child { position: relative; isolation: isolate }
${F} [data-count] { position: absolute; left: 30px; top: calc(50% - 20px) }
${F} li > button:first-child::after { content: ''; position: absolute; z-index: -1; left: 2px; top: 50%; width: 44px; height: 44px; transform: translateY(-50%); border-radius: 14px; transition: background-color 120ms ease }
${F} li > button:first-child:hover::after { background-color: hsl(var(--foreground) / 0.05) }
${F} li > button:first-child[aria-current="page"]::after { background-color: hsl(var(--foreground) / 0.09) }
${F} li > button:first-child[aria-current="page"]::before { content: ''; position: absolute; left: -8px; top: 50%; width: 4px; height: 24px; transform: translateY(-50%); border-radius: 0 9999px 9999px 0; background: hsl(var(--foreground)) }
${F} li > button:first-child:focus-visible::after { box-shadow: inset 0 0 0 2px hsl(var(--ring)) }
${F} .sticky + div[aria-current] { background: transparent; position: relative; isolation: isolate }
${F} .sticky + div[aria-current] > span + span { opacity: 0 }
${F} .sticky + div[aria-current]::after { content: ''; position: absolute; z-index: -1; left: 2px; top: 50%; width: 44px; height: 44px; transform: translateY(-50%); border-radius: 14px; background-color: hsl(var(--foreground) / 0.09) }
${F} .sticky + div[aria-current]::before { content: ''; position: absolute; left: -8px; top: 50%; width: 4px; height: 24px; transform: translateY(-50%); border-radius: 0 9999px 9999px 0; background: hsl(var(--foreground)) }
.work-rail-list .sticky > button > span:first-child { position: relative; transition: background-color 160ms ease, box-shadow 160ms ease, color 160ms ease, opacity 160ms ease }
.work-rail-list .sticky > button > span:first-child > svg { transition: opacity 160ms ease }
.work-rail-list .sticky > button > span:first-child::before { content: ''; position: absolute; inset: 0; margin: auto; width: 16px; height: 16px; background-color: currentColor; -webkit-mask: ${PLUS} center / 16px 16px no-repeat; mask: ${PLUS} center / 16px 16px no-repeat; opacity: 0; transition: opacity 160ms ease }
${F} .sticky > button > span:first-child { opacity: 1; color: hsl(var(--foreground) / 0.8) }
${F} .sticky > button > span:first-child > svg { opacity: 0 }
${F} .sticky > button > span:first-child::before { opacity: 1 }
${F} .sticky > button:hover > span:first-child { background-color: hsl(var(--foreground) / 0.1) }
${F} .sticky > button:focus-visible > span:first-child { box-shadow: 0 0 0 2px hsl(var(--ring)) }
.work-rail-list label:has(> input) { position: relative; isolation: isolate; transition: border-color 220ms ease }
.work-rail-list label:has(> input) > svg { transition: color 160ms ease }
.work-rail-list label:has(> input)::before { content: ''; position: absolute; z-index: -1; left: 0; top: 0; width: 100%; height: 100%; border-radius: 9999px; transition: left 220ms ${EASE}, top 220ms ${EASE}, width 220ms ${EASE}, height 220ms ${EASE}, background-color 220ms ease }
.work-rail-list label:has(> input)::after { content: ''; position: absolute; left: 11px; bottom: -9px; width: 24px; height: 1px; background: hsl(var(--foreground) / 0.12); opacity: 0; pointer-events: none; transition: opacity 160ms ease }
${F} label:has(> input) { border-color: transparent; background: transparent }
${F} label:has(> input) > input, ${F} label:has(> input) > button { opacity: 0 }
${F} label:has(> input)::before { left: 7px; top: calc(50% - 16px); width: 32px; height: 32px; background-color: hsl(var(--foreground) / 0.06) }
${F} label:has(> input):hover::before { background-color: hsl(var(--foreground) / 0.1) }
${F} label:has(> input) > svg { color: hsl(var(--foreground) / 0.8) }
${F} label:has(> input)::after { opacity: 1 }
@media (prefers-reduced-motion: reduce) { .work-rail, .work-rail-slot, .work-rail-list *, .work-rail-list *::before, .work-rail-list *::after, .work-rail-show, .work-rail-glyph > span { transition: none !important } }`;
