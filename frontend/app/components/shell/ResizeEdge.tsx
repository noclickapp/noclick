// A column's edge (its right, or its left for a column docked on the right):
// drag to resize, arrow keys to nudge, double-click to reset. Sits over the
// column's border; the column itself must be positioned.
import type { PointerEvent as ReactPointerEvent } from 'react';
import { cn } from '~/lib/utils';
import type { PanelWidth } from './panelWidth';

export function ResizeEdge({ panel, label, className, side = 'right' }: { panel: PanelWidth; label: string; className?: string; side?: 'left' | 'right' }) {
    // Dragging away from the column widens it: rightward from its right edge, leftward from its left.
    const sign = side === 'left' ? -1 : 1;
    const width = panel.useWidth();
    const resizing = panel.useResizing();
    const onPointerDown = (e: ReactPointerEvent<HTMLButtonElement>) => {
        if (e.button !== 0) return;
        e.preventDefault();
        const startX = e.clientX;
        const startWidth = width;
        const target = e.currentTarget;
        target.setPointerCapture(e.pointerId);
        panel.setResizing(true);
        document.body.style.cursor = 'col-resize';
        const move = (ev: PointerEvent) => panel.set(startWidth + sign * (ev.clientX - startX));
        const up = () => {
            target.removeEventListener('pointermove', move);
            target.removeEventListener('pointerup', up);
            target.removeEventListener('pointercancel', up);
            document.body.style.cursor = '';
            panel.setResizing(false);
        };
        target.addEventListener('pointermove', move);
        target.addEventListener('pointerup', up);
        target.addEventListener('pointercancel', up);
    };
    return (
        <button
            type="button"
            aria-label={label}
            title="Drag to resize · double-click to reset"
            onPointerDown={onPointerDown}
            onDoubleClick={() => panel.set(panel.initial)}
            onKeyDown={(e) => {
                if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
                    e.preventDefault();
                    panel.set(width + sign * (e.key === 'ArrowRight' ? 16 : -16));
                }
            }}
            className={cn('group/edge absolute inset-y-0 z-10 w-2 cursor-col-resize touch-none select-none focus-visible:outline-none', side === 'left' ? '-left-1' : '-right-1', className)}
        >
            <span
                className={cn(
                    'absolute inset-y-0 left-1/2 w-px -translate-x-1/2 transition-colors',
                    resizing ? 'bg-foreground/30' : 'bg-transparent group-hover/edge:bg-foreground/20 group-focus-visible/edge:bg-ring'
                )}
            />
        </button>
    );
}
