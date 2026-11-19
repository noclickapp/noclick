// The pieces Home's sections are drawn with: a list's header (its fold chevron, its name, a hover menu, an add
// button), the pill a section is named in, a channel row's Move menu, and the drag state channels and sections move by.
// Every icon-only button wears the app's tooltip naming what it does; the menus carry everything a drag does, so a
// keyboard and a phone reach it all.
import { useEffect, useRef, useState, type DragEvent, type PointerEvent as ReactPointerEvent, type ReactNode } from 'react';
import { ArrowDown, ArrowUp, Check, ChevronDown, FolderPlus, MoreHorizontal, Pencil, Plus, Trash2 } from 'lucide-react';
import { useInPhoneShell } from '@/ui/phoneBar';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from '@/ui/dropdown-menu';
import { cn } from '@/ui/utils';
import { MAX_SECTION_NAME, type Destination, type Section } from './sections';
import { Tip } from '../tooltip';

export const MENU_ITEM = 'gap-2.5 rounded-lg px-2.5 py-2 text-[14px]';
const MENU_ICON = 'h-4 w-4 text-muted-foreground';
const MENU_CONTENT = 'min-w-[220px] rounded-xl p-1';
/** A header's small round button (fold, menu, add), its hover a circle. */
/** A header's small round control; on a phone its hit grows to 40px around the same face, its row unmoved. */
const SMALL =
    'max-md:-m-2 max-md:h-10 max-md:w-10 grid h-6 w-6 shrink-0 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring data-[state=open]:bg-foreground/[0.06] data-[state=open]:text-foreground';
/** Shown on hover or keyboard focus, and while its menu is open. */
const ON_HOVER = 'opacity-0 focus-visible:opacity-100 data-[state=open]:opacity-100';
/** How long a finger rests on a row before its menu opens, and how far it may drift meanwhile. */
const HOLD_MS = 450;
const HOLD_SLOP = 8;

/** A phone's way to a row's menu: press and hold (as Slack's app does), so the rows carry no ⋯ of their own. The click
 *  that ends a hold doesn't also open the row. */
export function usePressAndHold(onHold: (id: string) => void) {
    const s = useRef({ timer: undefined as number | undefined, at: null as { x: number; y: number } | null, held: false });
    const clear = () => {
        window.clearTimeout(s.current.timer);
        s.current.at = null;
    };
    return (id: string) => ({
        onPointerDown: (e: ReactPointerEvent) => {
            if (e.pointerType === 'mouse') return;
            clear();
            s.current.held = false;
            s.current.at = { x: e.clientX, y: e.clientY };
            s.current.timer = window.setTimeout(() => {
                s.current.held = true;
                navigator.vibrate?.(10);
                onHold(id);
            }, HOLD_MS);
        },
        onPointerMove: (e: ReactPointerEvent) => {
            const at = s.current.at;
            if (at && Math.hypot(e.clientX - at.x, e.clientY - at.y) > HOLD_SLOP) clear();
        },
        onPointerUp: clear,
        onPointerCancel: clear,
        // A hold's release sends no mouse events after it: their focus would land on the row and close the menu.
        onTouchEnd: (e: { preventDefault(): void }) => {
            if (s.current.held) e.preventDefault();
        },
        // Only the row's own click: its menu's, portalled out of it, still bubbles here through React.
        onClickCapture: (e: { currentTarget: EventTarget; target: EventTarget; preventDefault(): void; stopPropagation(): void }) => {
            if (!s.current.held || !(e.currentTarget as Node).contains(e.target as Node)) return;
            s.current.held = false;
            e.preventDefault();
            e.stopPropagation();
        },
    });
}

// ── dragging ────────────────────────────────────────────────────────────────

const CHANNEL_TYPE = 'application/x-noclick-channel';
const SECTION_TYPE = 'application/x-noclick-section';

export type Dragged = { kind: 'channel'; id: string } | { kind: 'section'; id: string };
/** Where a drop lands: a list (a section's id, `starred` or `channels`) and the index in it. */
export interface DropAt {
    list: string;
    index: number;
}

export interface Drag {
    dragged: Dragged | null;
    over: DropAt | null;
    start(e: DragEvent, dragged: Dragged): void;
    /** The pointer is over `list`'s `index`: there's where it drops, if what's dragged can go there. */
    hover(e: DragEvent, at: DropAt): void;
    end(): void;
}

/** What's being dragged and where it would land. Only Work's own drags count: a file dragged over the list isn't one. */
export function useDrag(accepts: (dragged: Dragged, at: DropAt) => boolean): Drag {
    const [dragged, setDragged] = useState<Dragged | null>(null);
    const [over, setOver] = useState<DropAt | null>(null);
    return {
        dragged,
        over,
        start: (e, d) => {
            e.dataTransfer.effectAllowed = 'move';
            e.dataTransfer.setData(d.kind === 'channel' ? CHANNEL_TYPE : SECTION_TYPE, d.id);
            setDragged(d);
        },
        hover: (e, at) => {
            if (!dragged || !accepts(dragged, at)) return;
            e.preventDefault();
            e.dataTransfer.dropEffect = 'move';
            if (over?.list !== at.list || over.index !== at.index) setOver(at);
        },
        end: () => {
            setDragged(null);
            setOver(null);
        },
    };
}

/** Whether the pointer is in the lower half of `el`: a drop there lands after it. */
export const lowerHalf = (e: DragEvent, el: Element) => {
    const r = el.getBoundingClientRect();
    return e.clientY > r.top + r.height / 2;
};

/** The line a drop would land on, at a row's top or bottom edge (absolute: nothing moves while dragging). */
export function DropLine({ at }: { at: 'top' | 'bottom' }) {
    return <span aria-hidden className={cn('pointer-events-none absolute inset-x-2 z-10 h-0.5 rounded-full bg-foreground/60', at === 'top' ? '-top-px' : '-bottom-px')} />;
}

/** For a menu whose item opens the name field: the field opens once the menu has closed and given focus back, so
 *  neither the trigger nor an item still fading out under the pointer takes focus from it (which would cancel it).
 *  `naming(run)` wraps such an item's action. */
function useNameAfterMenu() {
    const pending = useRef<(() => void) | null>(null);
    return {
        naming: (run: () => void) => () => {
            pending.current = run;
        },
        onCloseAutoFocus: (e: Event) => {
            const run = pending.current;
            if (!run) return;
            pending.current = null;
            e.preventDefault();
            run();
        },
    };
}

// ── a list's header ─────────────────────────────────────────────────────────

export interface SectionMenu {
    onRename?: () => void;
    onMoveUp?: (() => void) | null;
    onMoveDown?: (() => void) | null;
    onNewSection: () => void;
    onDelete?: () => void;
}

/** A list's header, as the Channels header has been: its fold chevron (where it folds), its name (a click folds it
 *  too, and a section's name is what drags it), a menu on hover, then its add button. */
export function FoldHeader({
    label,
    listId,
    folded,
    onFold,
    menu,
    onAdd,
    addLabel,
    drop,
    dragName,
    children,
}: {
    label: string;
    /** The list it folds, for assistive tech. */
    listId: string;
    folded?: boolean;
    /** Absent: this list doesn't fold. */
    onFold?: () => void;
    menu?: SectionMenu;
    onAdd?: () => void;
    addLabel?: string;
    /** Highlighted as where a drag drops. */
    drop?: boolean;
    /** The name's drag start, for a section that moves by dragging it. */
    dragName?: (e: DragEvent) => void;
    /** What else the header row holds (its drag handlers' wrapper is the caller's). */
    children?: ReactNode;
}) {
    return (
        <div className={cn('group/head flex h-8 items-center gap-0.5 rounded-full pl-1.5 pt-0.5 transition-colors max-md:h-10', drop && 'bg-foreground/[0.06]')}>
            {onFold ? (
                <Tip label={folded ? 'Unfold' : 'Fold'}>
                    <button type="button" onClick={onFold} aria-expanded={!folded} aria-controls={listId} aria-label={`${folded ? 'Unfold' : 'Fold'} ${label}`} className={SMALL}>
                        <ChevronDown className={cn('h-3.5 w-3.5 transition-transform duration-150 motion-reduce:transition-none', folded && '-rotate-90')} strokeWidth={2.25} />
                    </button>
                </Tip>
            ) : (
                <span className="w-1" />
            )}
            {/* The name is a larger target for the pointer; the chevron is the control a keyboard and a reader use. */}
            {/* eslint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/no-static-element-interactions */}
            <span
                data-rail-text
                draggable={!!dragName}
                onDragStart={dragName}
                onClick={onFold}
                className={cn('min-w-0 flex-1 select-none truncate pl-1 text-[13px] font-medium text-muted-foreground', onFold && 'cursor-pointer hover:text-foreground')}
            >
                {label}
            </span>
            {children}
            {menu && <HeaderMenu label={label} menu={menu} />}
            {onAdd && (
                <Tip label={addLabel}>
                    <button type="button" onClick={onAdd} aria-label={addLabel} className={SMALL}>
                        <Plus className="h-4 w-4" strokeWidth={2} />
                    </button>
                </Tip>
            )}
        </div>
    );
}

function HeaderMenu({ label, menu }: { label: string; menu: SectionMenu }) {
    // A phone has no hover: its headers keep their menu in sight.
    const phone = useInPhoneShell();
    const focus = useNameAfterMenu();
    return (
        <DropdownMenu modal={false}>
            <Tip label="Section options">
                <DropdownMenuTrigger aria-label={`${label} options`} className={cn(SMALL, !phone && cn(ON_HOVER, 'group-hover/head:opacity-100 group-focus-within/head:opacity-100'))}>
                    <MoreHorizontal className="h-4 w-4" />
                </DropdownMenuTrigger>
            </Tip>
            <DropdownMenuContent align="end" sideOffset={6} className={MENU_CONTENT} onCloseAutoFocus={focus.onCloseAutoFocus}>
                {menu.onRename && (
                    <DropdownMenuItem onSelect={focus.naming(menu.onRename)} className={MENU_ITEM}>
                        <Pencil className={MENU_ICON} strokeWidth={1.75} />
                        Rename
                    </DropdownMenuItem>
                )}
                {menu.onMoveUp !== undefined && (
                    <DropdownMenuItem disabled={!menu.onMoveUp} onSelect={() => menu.onMoveUp?.()} className={MENU_ITEM}>
                        <ArrowUp className={MENU_ICON} strokeWidth={1.75} />
                        Move up
                    </DropdownMenuItem>
                )}
                {menu.onMoveDown !== undefined && (
                    <DropdownMenuItem disabled={!menu.onMoveDown} onSelect={() => menu.onMoveDown?.()} className={MENU_ITEM}>
                        <ArrowDown className={MENU_ICON} strokeWidth={1.75} />
                        Move down
                    </DropdownMenuItem>
                )}
                <DropdownMenuItem onSelect={focus.naming(menu.onNewSection)} className={MENU_ITEM}>
                    <FolderPlus className={MENU_ICON} strokeWidth={1.75} />
                    New section
                </DropdownMenuItem>
                {menu.onDelete && (
                    <>
                        <DropdownMenuSeparator className="mx-1 bg-border dark:bg-foreground/[0.08]" />
                        <DropdownMenuItem onSelect={menu.onDelete} className={cn(MENU_ITEM, 'text-red-600 focus:text-red-600 dark:text-red-400 dark:focus:text-red-400')}>
                            <Trash2 className="h-4 w-4" strokeWidth={1.75} />
                            Delete section
                        </DropdownMenuItem>
                    </>
                )}
            </DropdownMenuContent>
        </DropdownMenu>
    );
}

// ── naming a section ────────────────────────────────────────────────────────

/** The pill a section is named or renamed in: Enter (or leaving it) keeps the name, Esc or nothing typed keeps none. */
export function SectionNameField({ initial = '', onDone, onCancel }: { initial?: string; onDone: (name: string) => void; onCancel: () => void }) {
    const [name, setName] = useState(initial);
    const input = useRef<HTMLInputElement>(null);
    const finish = () => (name.trim() ? onDone(name) : onCancel());
    // Opened by asking for it (a menu's New section or Rename), it takes the typing at once.
    useEffect(() => input.current?.focus(), []);
    return (
        <div className="flex h-8 items-center pl-1 pr-1 pt-0.5">
            <input
                ref={input}
                value={name}
                maxLength={MAX_SECTION_NAME}
                onChange={(e) => setName(e.target.value)}
                onFocus={(e) => e.currentTarget.select()}
                onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                        e.preventDefault();
                        finish();
                    } else if (e.key === 'Escape') {
                        e.preventDefault();
                        e.stopPropagation();
                        onCancel();
                    }
                }}
                onBlur={finish}
                placeholder="Name the section"
                aria-label="Section name"
                className="h-7 w-full rounded-full border border-foreground/20 bg-foreground/[0.03] px-3 text-[13px] font-medium text-foreground outline-none placeholder:font-normal placeholder:text-muted-foreground focus:border-foreground/35 max-sm:text-[16px]"
            />
        </div>
    );
}

// ── a channel's Move menu ───────────────────────────────────────────────────

/** A channel row's menu: where it can go (its section, or Channels) and a new section to put it in. Its ⋯ shows on
 *  the row's hover or focus; a phone opens it by holding the row, the ⋯ only where it opens. */
export function MoveMenu({
    name,
    sections,
    current,
    open,
    onOpenChange,
    onMove,
    onNewSection,
}: {
    name: string;
    sections: Section[];
    /** Its section, or null (Channels). */
    current: Destination;
    open: boolean;
    onOpenChange: (open: boolean) => void;
    onMove: (to: Destination) => void;
    onNewSection: () => void;
}) {
    const item = (to: Destination, label: string) => (
        <DropdownMenuItem key={to ?? 'channels'} onSelect={() => to !== current && onMove(to)} className={MENU_ITEM}>
            <span className="min-w-0 flex-1 truncate">{label}</span>
            {to === current && <Check aria-label="Here now" className="h-4 w-4 text-foreground/70" strokeWidth={2} />}
        </DropdownMenuItem>
    );
    const phone = useInPhoneShell();
    const focus = useNameAfterMenu();
    return (
        <DropdownMenu open={open} onOpenChange={onOpenChange} modal={false}>
            <Tip label="Move to section">
                <DropdownMenuTrigger
                    aria-label={`Move #${name} to a section`}
                    className={cn(SMALL, ON_HOVER, 'absolute right-1.5 top-1/2 -translate-y-1/2', phone ? 'pointer-events-none' : 'group-hover/row:opacity-100 group-focus-within/row:opacity-100')}
                >
                    <MoreHorizontal className="h-4 w-4" />
                </DropdownMenuTrigger>
            </Tip>
            <DropdownMenuContent align="end" sideOffset={6} className={cn(MENU_CONTENT, 'max-h-[60dvh] overflow-y-auto')} onCloseAutoFocus={focus.onCloseAutoFocus}>
                <DropdownMenuLabel className="px-2.5 pb-1 pt-1.5 text-[12px] font-medium text-muted-foreground">Move to section</DropdownMenuLabel>
                {sections.map((s) => item(s.id, s.name))}
                {item(null, 'Channels')}
                <DropdownMenuSeparator className="mx-1 bg-border dark:bg-foreground/[0.08]" />
                <DropdownMenuItem onSelect={focus.naming(onNewSection)} className={MENU_ITEM}>
                    <FolderPlus className={MENU_ICON} strokeWidth={1.75} />
                    New section
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    );
}
