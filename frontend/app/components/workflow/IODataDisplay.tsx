// IODataDisplay component renders structured data (JSON or text) in a formatted display.
// Used by workflow nodes to display input/output data in the FlowHelperView panel.
// Now supports draggable JSON fields that can be dropped into config fields.
// Supports TABLE view for array/row data.

import { useMemo, useState, useCallback, useRef, useEffect } from 'react';
import { Copy, Check, Table, FileJson, List, type LucideIcon } from 'lucide-react';
import { DraggableJsonField } from './DraggableJsonField';
import { TableView } from './TableView';
import { SuggestedRefsTab, type SuggestedRef } from './SuggestedRefsTab';
import { useIOViewPreference, setIOViewPreference } from '~/hooks/useIOViewPreference';

// Hysteresis thresholds for compact mode to prevent ResizeObserver feedback loops.
// When non-compact, collapse at COMPACT_ENTER. When compact, only expand at COMPACT_LEAVE.
// The gap between them exceeds the width change from toggling button labels (~40px).
const COMPACT_ENTER_THRESHOLD = 280;
const COMPACT_LEAVE_THRESHOLD = 330;

// Shared chrome for the FIELDS / JSON / TABLE toggle buttons. Each
// button only differs by icon + label + click handler + active check; the
// styling is identical, so it lives here once.
const ViewToggleButton = ({
    icon: Icon,
    label,
    active,
    isCompact,
    title,
    onClick,
}: {
    icon: LucideIcon;
    label: string;
    active: boolean;
    isCompact: boolean;
    title: string;
    onClick: () => void;
}) => (
    <button
        onClick={onClick}
        className={`p-1 ${isCompact ? '' : 'px-2 py-1'} rounded transition-colors flex items-center gap-1 ${
            active
                ? 'bg-accent dark:bg-zinc-700 text-foreground'
                : 'hover:bg-accent/50 dark:hover:bg-zinc-700/50 text-muted-foreground dark:text-zinc-500 hover:text-foreground/80'
        }`}
        title={title}
    >
        <Icon className="w-3.5 h-3.5" />
        {!isCompact && <span className="text-xs">{label}</span>}
    </button>
);

interface IODataDisplayProps {
    data: any;
    label: string;
    nodeId?: string; // Required for draggable mode
    draggable?: boolean; // Enable draggable JSON fields
    isSchema?: boolean; // Schema mode: show type badges instead of literal type strings
    /** Curated reference list. When provided, surfaces a Fields tab as the
        default view. ``null`` means the curated list isn't ready yet (the
        Fields tab silently falls back to the JSON tree). ``undefined``
        means the caller doesn't supply curation at all — hide the tab. */
    suggestedRefs?: SuggestedRef[] | null;
}

export const IODataDisplay = ({ data, label, nodeId, draggable = false, isSchema = false, suggestedRefs }: IODataDisplayProps) => {
    const [copied, setCopied] = useState(false);
    // 'suggested' (Fields) and 'json' are the two persistent tab modes —
    // their preference is shared across every IODataDisplay on screen and
    // persisted in localStorage. 'table' is ad-hoc per card and doesn't touch
    // the preference.
    // null = curation pending (tab shows, content falls back to JSON); an
    // array = curated. Anything else (undefined = feature off, or a malformed
    // non-array payload) means no Fields tab.
    const hasSuggestedTab = suggestedRefs === null || Array.isArray(suggestedRefs);
    const hasFields = Array.isArray(suggestedRefs) && suggestedRefs.length > 0;
    const preferredView = useIOViewPreference();
    const [viewMode, setViewMode] = useState<'json' | 'table' | 'suggested'>(
        () => (hasFields && preferredView === 'suggested' ? 'suggested' : 'json'),
    );
    const [isCompact, setIsCompact] = useState(false);
    const containerRef = useRef<HTMLDivElement>(null);

    // Keep viewMode in sync with the global preference. Skipped when the
    // user is on the ad-hoc table tab so a sibling card flipping Fields↔JSON
    // doesn't yank them out.
    useEffect(() => {
        setViewMode((prev) => {
            if (prev === 'table') return prev;
            return hasFields && preferredView === 'suggested' ? 'suggested' : 'json';
        });
    }, [preferredView, hasFields]);

    // Track container width to collapse button labels when narrow.
    // Uses hysteresis (different enter/leave thresholds) to prevent feedback loops:
    // toggling button text changes width by ~40px, so the 50px gap between thresholds
    // ensures the width can't oscillate back and forth.
    useEffect(() => {
        const container = containerRef.current;
        if (!container) return;

        const observer = new ResizeObserver((entries) => {
            for (const entry of entries) {
                const w = entry.contentRect.width;
                setIsCompact(prev =>
                    prev ? w < COMPACT_LEAVE_THRESHOLD : w < COMPACT_ENTER_THRESHOLD
                );
            }
        });

        observer.observe(container);
        return () => observer.disconnect();
    }, []);

    const handleCopy = useCallback(async () => {
        try {
            const textToCopy = typeof data === 'string' ? data : JSON.stringify(data, null, 2);
            await navigator.clipboard.writeText(textToCopy);
            setCopied(true);
            setTimeout(() => setCopied(false), 2000);
        } catch (err) {
            console.error('Failed to copy:', err);
        }
    }, [data]);

    // Check if data is a non-primitive (object/array) that should use tree view
    const isStructuredData = useMemo(() => {
        return data !== null && data !== undefined && typeof data === 'object';
    }, [data]);

    // Check if data is suitable for table view (has rows/array structure)
    const isTableCompatible = useMemo(() => {
        if (!isStructuredData) return false;

        // Check if data is directly an array
        if (Array.isArray(data) && data.length > 0) {
            return true;
        }

        // Check for array in data.data (common pattern for API responses)
        if (data?.data && typeof data.data === 'object') {
            // Find any array property in data.data
            const arrayProp = Object.values(data.data).find(
                val => Array.isArray(val) && val.length > 0
            );
            if (arrayProp) return true;
        }

        // Check for any array property at the top level
        if (typeof data === 'object' && data !== null) {
            const arrayProp = Object.values(data).find(
                val => Array.isArray(val) && val.length > 0
            );
            if (arrayProp) return true;
        }

        return false;
    }, [data, isStructuredData]);

    // Format the data for plain text display (primitives only)
    const formattedData = useMemo(() => {
        if (data === undefined || data === null) {
            return 'No data';
        }
        if (typeof data === 'string') {
            return data;
        }
        return JSON.stringify(data, null, 2);
    }, [data]);

    // Copy button component - reused in both layouts
    const copyButton = (
        <button
            onClick={handleCopy}
            className="p-1 hover:bg-accent dark:hover:bg-zinc-700/50 rounded transition-colors"
            title="Copy data"
        >
            {copied ? (
                <Check className="w-3.5 h-3.5 text-green-600 dark:text-green-400" />
            ) : (
                <Copy className="w-3.5 h-3.5 text-muted-foreground hover:text-foreground/80" />
            )}
        </button>
    );

    // Use tree view for structured data (with or without drag enabled)
    // Note: path is empty string so references like {{nodeId.fieldName}} work correctly
    // The backend resolves references starting from node_outputs[nodeId] directly
    if (isStructuredData && nodeId) {
        return (
            <div ref={containerRef} className="space-y-2">
                {/* Show label row if there's a label OR if data is table-compatible (for toggle buttons) */}
                {(label || isTableCompatible || hasSuggestedTab) && (
                    <div className="text-[11px] text-muted-foreground dark:text-zinc-500 uppercase tracking-wider flex items-center gap-2">
                        {label && <span>{label}</span>}
                        {/* View mode toggle (show if data is table-compatible or has suggested refs) */}
                        {(isTableCompatible || hasSuggestedTab) && (
                            <div className={`flex items-center gap-1 ${label ? 'ml-2' : ''}`}>
                                {hasSuggestedTab && (
                                    <ViewToggleButton
                                        icon={List} label="FIELDS" isCompact={isCompact}
                                        active={viewMode === 'suggested'}
                                        title="Fields you can drag into your config"
                                        // Set local viewMode too: a direct click must move
                                        // this card even from an ad-hoc table/loop view, where
                                        // the preference-sync effect intentionally won't.
                                        onClick={() => { setIOViewPreference('suggested'); setViewMode('suggested'); }}
                                    />
                                )}
                                <ViewToggleButton
                                    icon={FileJson} label="JSON" isCompact={isCompact}
                                    active={viewMode === 'json'}
                                    title="JSON view"
                                    onClick={() => { setIOViewPreference('json'); setViewMode('json'); }}
                                />
                                {isTableCompatible && (
                                    <ViewToggleButton
                                        icon={Table} label="TABLE" isCompact={isCompact}
                                        active={viewMode === 'table'}
                                        title="Table view"
                                        onClick={() => setViewMode('table')}
                                    />
                                )}
                            </div>
                        )}
                        {/* Copy button copies the raw JSON; suppress it in the
                            Fields view where the on-screen content is a curated
                            list, not the underlying JSON. */}
                        {viewMode !== 'suggested' && <span className="ml-auto">{copyButton}</span>}
                    </div>
                )}
                {/* Drag hint - shown below the header when draggable */}
                {draggable && (
                    <div className="text-[9px] text-muted-foreground/70 dark:text-zinc-600 bg-muted dark:bg-zinc-800/50 px-2 py-1 rounded inline-block">
                        Drag fields to config inputs
                    </div>
                )}
                <div className="relative bg-card dark:bg-black/20 border border-border dark:border-border/50 rounded-lg p-3 overflow-hidden">
                    {/* Copy button in top-right corner ONLY when no header row is shown
                        — the header row (label / table toggle / Fields tab) already
                        renders its own copy button, so this must mirror that row's
                        condition to avoid a duplicate copy button. */}
                    {!label && !isTableCompatible && !hasSuggestedTab && viewMode !== 'suggested' && (
                        <div className="absolute top-1.5 right-1.5 z-10">
                            {copyButton}
                        </div>
                    )}
                    {viewMode === 'suggested' && hasSuggestedTab ? (
                        <SuggestedRefsTab
                            nodeId={nodeId}
                            refs={suggestedRefs ?? null}
                            draggable={draggable}
                            // Pass real output so cards show resolved values;
                            // skip for schema-only previews (the "data" is
                            // type descriptors, not values).
                            data={isSchema ? undefined : data}
                            fallback={
                                <DraggableJsonField
                                    data={data}
                                    nodeId={nodeId}
                                    path=""
                                    draggable={draggable}
                                    isSchema={isSchema}
                                />
                            }
                        />
                    ) : viewMode === 'table' && isTableCompatible ? (
                        <TableView data={data} maxRows={100} />
                    ) : (
                        <DraggableJsonField
                            data={data}
                            nodeId={nodeId}
                            path=""
                            draggable={draggable}
                            isSchema={isSchema}
                        />
                    )}
                </div>
            </div>
        );
    }

    // Default: plain text display (primitives or when nodeId not provided)
    return (
        <div className="space-y-2">
            {/* Only show label row if there's a label */}
            {label && (
                <div className="text-[11px] text-muted-foreground dark:text-zinc-500 uppercase tracking-wider flex items-center gap-2">
                    {label}
                    <span className="ml-auto">{copyButton}</span>
                </div>
            )}
            <div className="relative bg-card dark:bg-black/20 border border-border dark:border-border/50 rounded-lg p-3">
                {/* Copy button in top-right corner when no label */}
                {!label && (
                    <div className="absolute top-1.5 right-1.5 z-10">
                        {copyButton}
                    </div>
                )}
                <pre className="text-xs text-foreground/80 font-mono whitespace-pre-wrap break-words">
                    {formattedData}
                </pre>
            </div>
        </div>
    );
};
