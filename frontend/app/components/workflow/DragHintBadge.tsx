// Tiny inline hint pill shown next to palette section headers ("Available Nodes",
// "Found N blocks") to remind users they can drag items onto the canvas.
// Centralized here so the node palette (FlowHelperView) and block palette (BlockPalette)
// stay visually consistent without each file redefining the same styling.

import { Hand } from 'lucide-react';

export function DragHintBadge({ label }: { label: string }) {
    return (
        <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-card border border-border/70 dark:border-zinc-800/70 text-xs text-muted-foreground">
            <Hand className="w-3.5 h-3.5" strokeWidth={1.75} />
            {label}
        </div>
    );
}
