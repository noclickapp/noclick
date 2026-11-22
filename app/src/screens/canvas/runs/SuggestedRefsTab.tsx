// Renders the curated short-list of "most useful" output fields as draggable
// cards. Subtext switches between the field description (when no real data is
// available — e.g. expected-schema previews) and the resolved sample value
// (when the panel has a real execution output). Long values collapse to a
// preview with click-to-expand so a 200-row CSV doesn't drown the panel.

import { useState } from 'react';
import { useDraggable } from '@dnd-kit/core';
import { GripVertical, ChevronRight, ChevronDown } from 'lucide-react';
import type { JsonFieldDragData } from './DraggableJsonField';

export interface SuggestedRef {
    path: string;
    label: string;
    description: string;
}

interface SuggestedRefsTabProps {
    nodeId: string;
    refs: SuggestedRef[] | null;
    /** Whether to register drag handlers. False in the OutputPanel — a node
        can't reference its own output, so the cards still render but as
        read-only (no grip icon, no grab cursor, no useDraggable). */
    draggable: boolean;
    /** The data the cards' paths resolve against. When provided, each card's
        subtext is the resolved value instead of the description. Pass the
        actual execution output here, or undefined to use descriptions. */
    data?: unknown;
    /** Rendered when refs is null or empty. The owner passes the JSON view
        that lives in the sibling JSON tab. */
    fallback?: React.ReactNode;
}

// ── Path resolution ───────────────────────────────────────────────────────

/** Resolve a curated path like `rows[].owner.name` against actual data.
    `[]` segments fan out: each item is walked through the remaining path,
    producing an array. Returns `{found: false}` for any missing segment. */
function resolveAtPath(data: unknown, path: string): { found: boolean; value: unknown } {
    const segments = path.split('.');

    function walk(node: unknown, segs: string[]): { found: boolean; value: unknown } {
        if (segs.length === 0) return { found: true, value: node };
        if (node === null || node === undefined) return { found: false, value: undefined };

        const head = segs[0];
        const rest = segs.slice(1);
        const bracketIdx = head.indexOf('[]');

        if (bracketIdx === -1) {
            if (typeof node !== 'object') return { found: false, value: undefined };
            return walk((node as Record<string, unknown>)[head], rest);
        }

        const key = head.slice(0, bracketIdx);
        let arr: unknown;
        if (key === '') {
            arr = node;
        } else {
            if (typeof node !== 'object') return { found: false, value: undefined };
            arr = (node as Record<string, unknown>)[key];
        }
        if (!Array.isArray(arr)) return { found: false, value: undefined };

        const results = arr.map(item => walk(item, rest));
        return {
            found: results.every(r => r.found),
            value: results.map(r => r.value),
        };
    }

    return walk(data, segments);
}

// ── Value preview / full rendering ────────────────────────────────────────

const PREVIEW_STRING_MAX = 100;
const PREVIEW_ARRAY_MAX = 3;

/** Decide if a resolved value is "a lot" — multi-line / long / many items.
    These get a chevron and click-to-expand; everything else renders inline. */
function isLong(value: unknown): boolean {
    if (typeof value === 'string') {
        return value.length > PREVIEW_STRING_MAX || value.includes('\n');
    }
    if (Array.isArray(value)) {
        if (value.length > PREVIEW_ARRAY_MAX) return true;
        return value.some(isLong);
    }
    if (value && typeof value === 'object') {
        return Object.keys(value).length > 2 || Object.values(value).some(isLong);
    }
    return false;
}

function formatPreview(value: unknown): string {
    if (value === null) return 'null';
    if (value === undefined) return '—';
    if (typeof value === 'string') {
        const clipped = value.length > PREVIEW_STRING_MAX
            ? value.slice(0, PREVIEW_STRING_MAX) + '…'
            : value;
        return clipped.replace(/\n/g, ' ');
    }
    if (typeof value === 'number' || typeof value === 'boolean') {
        return String(value);
    }
    if (Array.isArray(value)) {
        if (value.length === 0) return '[]';
        const head = value.slice(0, PREVIEW_ARRAY_MAX).map(formatPreview).join(', ');
        return value.length > PREVIEW_ARRAY_MAX
            ? `[${head}, …] · ${value.length} items`
            : `[${head}]`;
    }
    if (typeof value === 'object') {
        const keys = Object.keys(value as object);
        return keys.length === 0 ? '{}' : `{${keys.slice(0, 3).join(', ')}${keys.length > 3 ? ', …' : ''}}`;
    }
    return String(value);
}

function formatFull(value: unknown): string {
    if (value === null) return 'null';
    if (value === undefined) return '—';
    if (typeof value === 'string') return value;
    if (typeof value === 'number' || typeof value === 'boolean') return String(value);
    try {
        return JSON.stringify(value, null, 2);
    } catch {
        return String(value);
    }
}

// ── Card body ─────────────────────────────────────────────────────────────

/** Shared label + subtext layout. The subtext logic — value vs description,
    inline vs expandable — is identical between the draggable and read-only
    variants, so factor it once. */
const CardBody = ({
    entry,
    resolved,
}: {
    entry: SuggestedRef;
    resolved: { found: boolean; value: unknown } | null;
}) => {
    const [expanded, setExpanded] = useState(false);
    const hasValue = resolved?.found === true;
    const value: unknown = hasValue ? resolved.value : undefined;
    const expandable = hasValue && isLong(value);

    return (
        <div className="min-w-0 flex-1">
            <div className="flex items-center gap-1">
                {expandable && (
                    <button
                        onClick={(e) => { e.stopPropagation(); e.preventDefault(); setExpanded((v) => !v); }}
                        onPointerDown={(e) => e.stopPropagation()}
                        className="text-muted-foreground dark:text-zinc-500 hover:text-foreground/80 flex-shrink-0"
                        title={expanded ? 'Collapse' : 'Expand'}
                    >
                        {expanded
                            ? <ChevronDown className="h-3 w-3" />
                            : <ChevronRight className="h-3 w-3" />}
                    </button>
                )}
                <div className="text-xs font-medium text-foreground truncate">{entry.label}</div>
            </div>
            {expanded && hasValue ? (
                <pre className="text-[11px] text-muted-foreground mt-1 max-h-48 overflow-auto whitespace-pre-wrap break-words font-mono">
                    {formatFull(value)}
                </pre>
            ) : hasValue ? (
                // Real values vs descriptions: same size/color, just mono
                // font. That's enough to read as "data" without looking
                // like a chip or input field.
                <div className="text-[11px] text-muted-foreground dark:text-zinc-500 mt-0.5 line-clamp-2 font-mono">
                    {formatPreview(value)}
                </div>
            ) : (
                <div className="text-[11px] text-muted-foreground dark:text-zinc-500 mt-0.5 line-clamp-2">{entry.description}</div>
            )}
        </div>
    );
};

// ── Card variants ─────────────────────────────────────────────────────────

const SuggestedRefDraggableCard = ({
    nodeId,
    entry,
    resolved,
}: {
    nodeId: string;
    entry: SuggestedRef;
    resolved: { found: boolean; value: unknown } | null;
}) => {
    const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
        id: `suggested-ref-${nodeId}-${entry.path}`,
        data: {
            type: 'json-field-reference',
            nodeId,
            path: entry.path,
            value: null,
            displayValue: entry.label,
        } as JsonFieldDragData,
    });

    return (
        <div
            ref={setNodeRef}
            {...attributes}
            {...listeners}
            style={{ opacity: isDragging ? 0.5 : 1, cursor: isDragging ? 'grabbing' : 'grab' }}
            className="group flex items-start gap-2 px-2 py-1.5 rounded-md bg-foreground/[0.02] hover:bg-foreground/[0.05] border border-foreground/[0.04] hover:border-foreground/[0.1] transition-all"
        >
            <GripVertical className="h-3.5 w-3.5 text-muted-foreground/70 dark:text-zinc-600 group-hover:text-muted-foreground mt-0.5 flex-shrink-0 transition-colors" />
            <CardBody entry={entry} resolved={resolved} />
        </div>
    );
};

const SuggestedRefReadOnlyCard = ({
    entry,
    resolved,
}: {
    entry: SuggestedRef;
    resolved: { found: boolean; value: unknown } | null;
}) => (
    <div className="flex items-start gap-2 px-2 py-1.5 rounded-md bg-foreground/[0.02] border border-foreground/[0.04]">
        <CardBody entry={entry} resolved={resolved} />
    </div>
);

// ── Top-level ─────────────────────────────────────────────────────────────

export const SuggestedRefsTab = ({ nodeId, refs, draggable, data, fallback }: SuggestedRefsTabProps) => {
    // No refs (still loading, or LLM produced nothing usable) → silently
    // render the fallback. Showing a curated-list-pending banner would be a
    // tell that something AI-shaped is happening behind the scenes; the
    // fallback covers the user's actual need either way. The Array.isArray
    // check also guards against malformed payloads (e.g. a legacy
    // double-encoded jsonb row that arrives as a JSON string, not an array).
    if (!Array.isArray(refs) || refs.length === 0) {
        return <>{fallback}</>;
    }

    // Only attempt resolution when data is provided AND is a plain object —
    // schema-only previews pass undefined, in which case all cards fall
    // through to their description text.
    const hasResolvableData = data !== undefined && data !== null && typeof data === 'object';

    return (
        <div className="space-y-1">
            {refs.map((entry) => {
                const resolved = hasResolvableData ? resolveAtPath(data, entry.path) : null;
                return draggable
                    ? <SuggestedRefDraggableCard key={entry.path} nodeId={nodeId} entry={entry} resolved={resolved} />
                    : <SuggestedRefReadOnlyCard key={entry.path} entry={entry} resolved={resolved} />;
            })}
        </div>
    );
};
