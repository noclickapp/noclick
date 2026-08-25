// Editable node label component rendered via NodeToolbar.
// Positioned outside the node's DOM tree so clicks don't trigger node selection.
// Used by withNodeWrapper to add labels to all workflow nodes.

import { useCallback, useEffect, useState } from 'react';
import { Position } from '@xyflow/react';
import { InlineTextEditor } from '~/components/ui/InlineTextEditor';
import { ScaledNodeToolbar } from './ScaledNodeToolbar';
import { InterfaceConsumerBadge } from './InterfaceConsumerBadge';
import { NodeStatusChip, shouldShowStatusChip } from './NodeStatusChip';

// Nodes that should NOT show labels (they handle their own or don't need them)
const NODES_WITHOUT_LABELS = new Set(['stickyNote']);

// Derive a readable display name from node type (e.g., "automation-telegram" -> "Telegram")
const LABEL_OVERRIDES: Record<string, string> = {
    'noclick': 'NoClick',
};

export function getDefaultLabelFromType(nodeType: string): string {
    if (LABEL_OVERRIDES[nodeType]) return LABEL_OVERRIDES[nodeType];
    return nodeType
        .replace(/^automation-/, '') // Remove "automation-" prefix
        .split('-')
        .map(word => word.charAt(0).toUpperCase() + word.slice(1)) // Capitalize each word
        .join(' ');
}

interface NodeLabelProps {
    nodeId: string;
    // Preview stories reserve a node's place before revealing it. The caption
    // stays mounted (so its toolbar is already positioned) but paints nothing.
    hidden?: boolean;
    nodeType: string;
    customLabel?: string;
    // Persisted last-run status (set by the backend on every execution, incl.
    // headless webhook/cron runs, and live by the node:state handler). Drives the
    // status chip below the label so users see the last outcome + how long ago.
    lastRunStatus?: string;
    lastRunAt?: number;
    isRunning?: boolean;
    // Whether to render the interface-consumer badge as the last row of the stack
    // (gated by withNodeWrapper's affordance rules). The badge itself self-hides
    // when the node has no interface consumers.
    showInterfaceBadge?: boolean;
}

export function NodeLabel({ nodeId, nodeType, customLabel, lastRunStatus, lastRunAt, isRunning, showInterfaceBadge, hidden = false }: NodeLabelProps) {
    const defaultLabel = getDefaultLabelFromType(nodeType);
    const displayLabel = customLabel || defaultLabel;
    const showLabel = !NODES_WITHOUT_LABELS.has(nodeType);

    // External rename trigger: the right-click "Rename" menu dispatches
    // `noclick:node:start-rename` with the target node's id; we bump a counter
    // signal that InlineTextEditor reads to enter edit mode + select all.
    const [renameSignal, setRenameSignal] = useState(0);
    useEffect(() => {
        const handler = (e: Event) => {
            const detail = (e as CustomEvent<{ nodeId: string }>).detail;
            if (detail?.nodeId === nodeId) setRenameSignal(c => c + 1);
        };
        document.addEventListener('noclick:node:start-rename', handler);
        return () => document.removeEventListener('noclick:node:start-rename', handler);
    }, [nodeId]);

    // React Flow only refreshes a toolbar's transform once the node it belongs
    // to has been measured, and a reserved preview node is never measured while
    // it is hidden. Flipping the caption in the same frame as the node therefore
    // paints it at a stale position for one frame; wait for the node's own
    // measurement pass instead.
    const [captionVisible, setCaptionVisible] = useState(!hidden);
    useEffect(() => {
        if (hidden) {
            setCaptionVisible(false);
            return;
        }
        let inner = 0;
        const outer = requestAnimationFrame(() => {
            inner = requestAnimationFrame(() => setCaptionVisible(true));
        });
        return () => {
            cancelAnimationFrame(outer);
            cancelAnimationFrame(inner);
        };
    }, [hidden]);

    // Save label by dispatching a custom event that FlowCanvas listens to
    const handleLabelSave = useCallback((newLabel: string) => {
        // Convert empty string to undefined to clear custom label
        const labelToSave = newLabel || undefined;
        if (labelToSave !== customLabel) {
            document.dispatchEvent(new CustomEvent('noclick:node:update-data', {
                detail: { nodeId, data: { label: labelToSave } }
            }));
        }
    }, [nodeId, customLabel]);

    // Show the last-run chip only for terminal outcomes and not while a fresh
    // run is in flight (the running animation conveys that state instead).
    // Interface (UI) nodes aren't executable steps, so they get no run-status chip.
    const showChip = !nodeType.startsWith('interface-') && shouldShowStatusChip(lastRunStatus, lastRunAt, isRunning);

    // One shared Bottom toolbar owns the whole stack — label, status chip, and the
    // interface-consumer badge — so they always flow vertically and never overlap
    // (no fixed per-item offsets, robust to multi-line labels). Each row is
    // independently conditional; the badge self-hides when there are no consumers.
    if (!showLabel && !showChip && !showInterfaceBadge) {
        return null;
    }

    return (
        <ScaledNodeToolbar position={Position.Bottom} offset={8}>
            {/* Stays mounted while hidden: a toolbar that mounts at reveal paints one
                frame before React Flow has positioned it — a caption flashing at the
                canvas edge. */}
            <div className="flex flex-col items-center gap-1" style={captionVisible ? undefined : { visibility: 'hidden' }}>
                {showLabel && (
                    <InlineTextEditor
                        value={displayLabel}
                        placeholder={defaultLabel}
                        onSave={handleLabelSave}
                        maxWidth={200}
                        textShadow={true}
                        wrap={true}
                        startEditingSignal={renameSignal}
                    />
                )}
                {showChip && <NodeStatusChip status={lastRunStatus as string} at={lastRunAt as number} />}
                {showInterfaceBadge && <InterfaceConsumerBadge nodeId={nodeId} />}
            </div>
        </ScaledNodeToolbar>
    );
}
