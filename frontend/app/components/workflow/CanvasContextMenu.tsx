// Floating right-click context menu for the workflow canvas.
// Renders at viewport pixel coordinates passed in by FlowCanvas (positioned just to
// the right-bottom of the pointer), dismisses on outside click / escape / window blur,
// and clamps inside the viewport so it never opens off-screen.

import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { cn } from '~/lib/utils';
import { KeyHint } from '~/components/shared/KeyHint';

export type ContextMenuItem =
    | {
          type: 'item';
          label: string;
          icon?: ReactNode;
          /** Key tokens for KeyHint — e.g. ['mod', 'C'] renders ⌘C on macOS,
           *  CtrlC elsewhere. 'backspace', 'enter', 'esc', etc. → glyphs. */
          shortcut?: string[];
          onSelect: () => void;
          disabled?: boolean;
          destructive?: boolean;
      }
    | { type: 'separator' };

export interface ContextMenuPosition {
    x: number;
    y: number;
}

interface CanvasContextMenuProps {
    position: ContextMenuPosition;
    items: ContextMenuItem[];
    onClose: () => void;
}

const MENU_MARGIN = 8;

export function CanvasContextMenu({ position, items, onClose }: CanvasContextMenuProps) {
    const ref = useRef<HTMLDivElement>(null);
    const [clamped, setClamped] = useState<ContextMenuPosition>(position);

    // Clamp inside the viewport after the menu measures itself.
    useLayoutEffect(() => {
        const el = ref.current;
        if (!el) return;
        const rect = el.getBoundingClientRect();
        const vw = window.innerWidth;
        const vh = window.innerHeight;
        let x = position.x;
        let y = position.y;
        if (x + rect.width + MENU_MARGIN > vw) x = Math.max(MENU_MARGIN, vw - rect.width - MENU_MARGIN);
        if (y + rect.height + MENU_MARGIN > vh) y = Math.max(MENU_MARGIN, vh - rect.height - MENU_MARGIN);
        setClamped({ x, y });
    }, [position]);

    // Click-outside / escape / window-blur dismiss. Uses pointerdown so the
    // dismissal fires before a menu item's own click (mousedown→mouseup→click).
    // Right-clicks (button 2) are intentionally NOT a dismissal — the upcoming
    // contextmenu event will update the menu's position/items in place, and
    // closing first would tear it down + replay the open animation (the
    // "spazzing" the user sees on rapid right-clicks).
    useEffect(() => {
        const onPointerDown = (e: PointerEvent) => {
            if (e.button === 2) return;
            if (!ref.current?.contains(e.target as Node)) onClose();
        };
        const onKeyDown = (e: KeyboardEvent) => {
            if (e.key === 'Escape') {
                e.stopPropagation();
                onClose();
            }
        };
        const onBlur = () => onClose();
        window.addEventListener('pointerdown', onPointerDown, true);
        window.addEventListener('keydown', onKeyDown, true);
        window.addEventListener('blur', onBlur);
        return () => {
            window.removeEventListener('pointerdown', onPointerDown, true);
            window.removeEventListener('keydown', onKeyDown, true);
            window.removeEventListener('blur', onBlur);
        };
    }, [onClose]);

    return (
        <div
            ref={ref}
            role="menu"
            tabIndex={-1}
            className={cn(
                'fixed z-[90] min-w-[224px] origin-top-left overflow-hidden rounded-xl p-1',
                'border border-foreground/[0.07] bg-popover/80 dark:bg-zinc-950/80 text-[13px] text-foreground backdrop-blur-2xl',
                // Layered shadow: soft drop + ~hairline inset ring for the crisp
                // translucent-glass edge. Light mode gets a much gentler drop (the
                // 0.75-alpha dark halo was far too heavy on the light canvas).
                'shadow-[0_12px_32px_-14px_rgba(0,0,0,0.22),0_0_0_0.5px_hsl(var(--foreground)/0.04)_inset]',
                'dark:shadow-[0_24px_60px_-12px_rgba(0,0,0,0.75),0_0_0_0.5px_hsl(var(--foreground)/0.04)_inset]',
                'animate-in fade-in-0 zoom-in-95 duration-100 ease-out',
            )}
            style={{ left: clamped.x, top: clamped.y }}
            onContextMenu={(e) => e.preventDefault()}
        >
            {items.map((item, i) => {
                if (item.type === 'separator') {
                    return <div key={`sep-${i}`} className="my-1 h-px bg-foreground/[0.06]" />;
                }
                return (
                    <button
                        key={item.label}
                        role="menuitem"
                        type="button"
                        disabled={item.disabled}
                        className={cn(
                            'group flex w-full cursor-default select-none items-center gap-2.5 rounded-md px-2.5 py-1.5 text-left outline-none transition-colors duration-75',
                            'hover:bg-foreground/[0.06] focus:bg-foreground/[0.06]',
                            item.disabled && 'pointer-events-none opacity-40',
                            item.destructive ? 'text-red-600 dark:text-red-400 hover:text-red-700 dark:hover:text-red-300' : 'text-foreground',
                        )}
                        onClick={(e) => {
                            e.stopPropagation();
                            if (item.disabled) return;
                            item.onSelect();
                            onClose();
                        }}
                    >
                        {item.icon && (
                            <span
                                className={cn(
                                    'flex h-4 w-4 shrink-0 items-center justify-center transition-colors duration-75 [&_svg]:size-3.5',
                                    item.destructive ? 'text-red-600/85 dark:text-red-400/85' : 'text-muted-foreground group-hover:text-foreground',
                                )}
                            >
                                {item.icon}
                            </span>
                        )}
                        <span className="flex-1 truncate tracking-[-0.005em]">{item.label}</span>
                        {item.shortcut && (
                            <KeyHint
                                keys={item.shortcut}
                                className="ml-3 shrink-0"
                                kbdClassName="bg-foreground/[0.04] text-muted-foreground group-hover:text-foreground"
                            />
                        )}
                    </button>
                );
            })}
        </div>
    );
}
