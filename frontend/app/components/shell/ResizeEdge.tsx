// A column's right edge: drag to resize, arrow keys to nudge, double-click to
// reset. Sits over the column's border; the column itself must be positioned.
import type { PointerEvent as ReactPointerEvent } from 'react';
import { cn } from '~/lib/utils';
import type { PanelWidth } from './panelWidth';

export function ResizeEdge({ panel, label, className }: { panel: PanelWidth; label: string; className?: string }) {
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
        const move = (ev: PointerEvent) => panel.set(startWidth + ev.clientX - startX);
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
                    panel.set(width + (e.key === 'ArrowRight' ? 16 : -16));
                }
            }}
            className={cn('group/edge absolute inset-y-0 -right-1 z-10 w-2 cursor-col-resize touch-none select-none focus-visible:outline-none', className)}
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
