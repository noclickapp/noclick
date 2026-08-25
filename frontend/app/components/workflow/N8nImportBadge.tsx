// Visual indicator shown while an n8n workflow paste is being translated into
// NoClick. Appears in the canvas prompt input (post-paste) and the chat
// sidebar header (during conversion), so the user has a persistent signal
// that their pasted workflow was recognized and is being processed.
//
// Name the source format directly while using the application's neutral
// import icon and semantic colors.

import { FileInput, Loader2 } from 'lucide-react';

export interface N8nImportBadgeProps {
    /** Number of source n8n nodes in the pasted workflow. */
    nodeCount: number;
    /** True while the agentic builder is actively processing the import. Adds a spinner. */
    processing?: boolean;
    /** Optional className for layout tweaks per call site. */
    className?: string;
}

export function N8nImportBadge({
    nodeCount,
    processing = false,
    className = '',
}: N8nImportBadgeProps) {
    const plural = nodeCount === 1 ? 'node' : 'nodes';
    return (
        <div
            className={
                'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ' +
                'bg-foreground/[0.04] border border-border text-foreground/90 ' +
                className
            }
            title={
                processing
                    ? 'Translating your n8n workflow into NoClick'
                    : 'n8n workflow detected'
            }
        >
            <FileInput
                className="h-3.5 w-3.5 text-muted-foreground"
                aria-hidden="true"
            />
            <span>n8n import</span>
            <span className="text-muted-foreground dark:text-white/45">·</span>
            <span className="text-muted-foreground dark:text-white/70 tabular-nums">
                {nodeCount} {plural}
            </span>
            {processing && (
                <Loader2
                    className="w-3 h-3 ml-0.5 animate-spin text-muted-foreground"
                    strokeWidth={2.5}
                />
            )}
        </div>
    );
}
