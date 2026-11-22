// The canvas's right-click menu as drawn: a floating list at the pointer, kept inside the window, closed by a click
// outside it, Escape or the window losing focus.
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { cn } from '@/ui/utils';

export type ContextMenuItem =
    | {
          type: 'item';
          label: string;
          icon?: ReactNode;
          /** Its keyboard shortcut (['mod', 'C']), which still works; never drawn. */
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

    // Kept inside the window once the menu has measured itself.
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

    // Closed on pointerdown, so it goes before a choice's own click lands elsewhere. A right-click isn't a close: the
    // menu that follows it moves this one in place, and closing first would draw it opening twice.
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
                // A soft drop and a hairline inside it for the glass edge; a much gentler drop in light.
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
                    </button>
                );
            })}
        </div>
    );
}
