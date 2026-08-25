// Resize handle UI components, one per axis. The actual drag bookkeeping lives
// in ./resize.ts (beginResizeDrag). Keep these dumb: just render the handle and
// forward onMouseDown.

interface HorizontalResizeHandleProps {
    onMouseDown: (e: React.MouseEvent) => void;
    position: 'left' | 'right';
}

export function ResizeHandle({ onMouseDown, position }: HorizontalResizeHandleProps) {
    return (
        <div
            className="absolute top-0 bottom-0 w-1 hover:w-1.5 bg-transparent hover:bg-blue-500/30 transition-all cursor-col-resize z-20 group"
            style={{ [position === 'left' ? 'left' : 'right']: 0 }}
            onMouseDown={onMouseDown}
        >
            <div className="absolute inset-y-0 left-1/2 -translate-x-1/2 w-0.5 bg-border dark:bg-zinc-700/50 group-hover:bg-blue-500/50 transition-colors" />
        </div>
    );
}

export function VerticalResizeHandle({ onMouseDown }: { onMouseDown: (e: React.MouseEvent) => void }) {
    return (
        <button
            type="button"
            aria-label="Resize panel height"
            className="absolute top-0 left-0 right-0 h-2 bg-transparent hover:bg-accent/50 dark:hover:bg-zinc-500/10 transition-all cursor-ns-resize z-30 group border-none outline-none"
            onMouseDown={onMouseDown}
        >
            <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-16 h-1 rounded-full bg-muted-foreground/30 dark:bg-zinc-600/30 group-hover:bg-muted-foreground/50 transition-colors" />
        </button>
    );
}
