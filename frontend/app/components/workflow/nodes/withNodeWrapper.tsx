/**
 * Higher-Order Component that wraps workflow nodes with common features:
 * - Collaborative selection border (via withCollaborativeBorder)
 * - Editable node label (via NodeLabel)
 * - "Run from here" hover pill for executing workflow from a specific node
 * - "Next step" hint (NextStepHintGroup) on every unconnected source handle
 *
 * Applied automatically to all nodes via the node registry.
 * This is the main wrapper - use this instead of withCollaborativeBorder directly.
 */

import { ComponentType } from 'react';
import { NodeProps, useReactFlow } from '@xyflow/react';
import { Trash2, Pin, PinOff, Ban } from 'lucide-react';
import { withCollaborativeBorder } from './withCollaborativeBorder';
import { markPointerDrivenDelete } from '../WorkflowContext';
import { NodeLabel } from './base/NodeLabel';
import { NodeAuroraLayers } from './base/NodeAuroraLayers';
import { NextStepHintGroup } from './base/NextStepHint';
import { resolveNodeType } from '~/utils/nodeSchemas';

const AFFORDANCE_EXCLUDED_TYPES = new Set(['stickyNote']);

// Run-from-here / pin / disable affordances are for executable automation steps,
// so they're hidden on interface (UI) nodes — except the unified form node, which
// is a workflow entry point (its output feeds downstream like any trigger). The
// delete button is separate — UI nodes should be removable from the canvas on
// hover just like automation nodes (see shouldShowDelete).
function shouldShowAffordances(type: string | undefined): boolean {
    if (!shouldShowDelete(type)) return false;
    if (resolveNodeType(type!) === 'interface-form') return true;
    if (type!.startsWith('interface-')) return false;
    return true;
}

// Interface nodes whose output meaningfully feeds downstream get the dashed
// next-step hint on their unconnected output handle: the form (submitted/stored
// values), multimedia (the resolved file URL), and file upload (the uploaded
// resource). Display-oriented blocks (table, html-react) stay hint-free.
const HINTED_INTERFACE_TYPES = new Set([
    'interface-form',
    'interface-file',
    'interface-file-upload',
]);

function shouldShowNextStepHint(type: string | undefined): boolean {
    if (!shouldShowDelete(type)) return false;
    const canonical = resolveNodeType(type!);
    if (canonical.startsWith('interface-')) {
        return HINTED_INTERFACE_TYPES.has(canonical);
    }
    return true;
}

function shouldShowDelete(type: string | undefined): boolean {
    if (!type) return false;
    if (AFFORDANCE_EXCLUDED_TYPES.has(type)) return false;
    return true;
}

// Moved to nodeChrome.ts (leaf) so the edge component can share it without
// pulling this module's schema-registry closure; re-exported for consumers.
import { NODE_DELETE_BTN_CLASSES } from './nodeChrome';
export { NODE_DELETE_BTN_CLASSES };

function RunFromHerePill({ nodeId }: { nodeId: string }) {
    return (
        <button
            onClick={(e) => {
                e.stopPropagation();
                document.dispatchEvent(
                    new CustomEvent('noclick:run-from-node', {
                        detail: { nodeId },
                    })
                );
            }}
            className="peer/runfromhere group/pill absolute z-20 flex items-center justify-center h-[25px] min-w-[25px] rounded-full opacity-0 group-hover:opacity-100 transition-all duration-200 nodrag border border-border/60 dark:border-zinc-700/60"
            style={{
                top: -28,
                left: 4,
                // Padding kept tight (5px) so the collapsed icon-only state stays a
                // 25×25 circle — the 12px icon + 2×5 padding + 2×1 border lands at
                // exactly 24px content, with min-w pushing the button to a clean 25.
                paddingLeft: 5,
                paddingRight: 5,
                background: 'hsl(var(--popover))',
            }}
            title="Run workflow from this node"
        >
            <svg
                className="w-3 h-3 text-foreground/80 shrink-0"
                viewBox="0 0 24 24"
                fill="currentColor"
            >
                <path d="M8 5v14l11-7z" />
            </svg>
            <span className="max-w-0 overflow-hidden whitespace-nowrap text-xs font-medium text-foreground/80 transition-all duration-200 group-hover/pill:max-w-[100px] group-hover/pill:ml-1.5 group-hover/pill:mr-0.5">
                Run from here
            </span>
        </button>
    );
}

// Hover-revealed delete button. Uses ReactFlow's deleteElements so the deletion
// flows through onNodesChange — cron cleanup, broadcast to collaborators,
// interface block sync — the same way keyboard Delete or right-click → Remove
// does. Vertically aligned with RunFromHerePill (same 25×25 / top: -28).
function DeletePill({ nodeId }: { nodeId: string }) {
    const { deleteElements } = useReactFlow();
    return (
        <button
            onClick={(e) => {
                e.stopPropagation();
                // Mouse delete: keep the post-delete selection move but skip the
                // autopan — the cursor is already where the user is looking.
                markPointerDrivenDelete();
                deleteElements({ nodes: [{ id: nodeId }] });
            }}
            className={`absolute z-20 opacity-0 group-hover:opacity-100 peer-hover/runfromhere:opacity-0 nodrag ${NODE_DELETE_BTN_CLASSES}`}
            style={{ top: -28, right: 4 }}
            title="Delete node"
        >
            <Trash2 size={12} />
        </button>
    );
}

// Left-side toggle pills (pin / disable) share the delete button's 25×25 shape
// but no red hover — they're stateful toggles, not destructive actions. The
// per-state classes layer color on top of this base.
const NODE_TOGGLE_BTN_BASE =
    'w-[25px] h-[25px] rounded-full flex items-center justify-center backdrop-blur-sm border shadow-[0_2px_8px_rgba(0,0,0,0.4)] transition-colors duration-200 active:scale-95';

// On-node edits go through the same custom event the inline label editor uses,
// so they flow through handleNodeDataUpdate (undo capture + collaborator
// broadcast) rather than a raw setNodes that would be local-only.
function dispatchNodeDataUpdate(nodeId: string, data: Record<string, unknown>) {
    document.dispatchEvent(
        new CustomEvent('noclick:node:update-data', {
            detail: { nodeId, data },
        })
    );
}

// Pin (mock) toggle — top-left corner, clear of the centered input handle.
// Pins the node's last output as mock data so downstream runs reuse it without
// re-executing this step; click again to clear. Disabled until there's an
// output to pin. Mirrors the Mock button in the flow-helper OutputPanel and the
// M/P keyboard shortcut. Stays visible while pinned so the state is reversible
// without hunting on hover.
function PinPill({
    nodeId,
    mockedOutput,
    output,
}: {
    nodeId: string;
    mockedOutput: unknown;
    output: unknown;
}) {
    const isMocked = mockedOutput !== undefined;
    const hasOutput = output !== undefined && output !== null;
    const canToggle = isMocked || hasOutput;
    return (
        <button
            onClick={(e) => {
                e.stopPropagation();
                if (!canToggle) return;
                // null signals deletion of the mock; otherwise pin the live output.
                dispatchNodeDataUpdate(nodeId, {
                    mockedOutput: isMocked ? null : output,
                });
            }}
            disabled={!canToggle}
            className={`absolute z-20 nodrag ${NODE_TOGGLE_BTN_BASE} ${
                isMocked
                    ? 'opacity-100 text-foreground bg-muted border-border hover:bg-accent dark:text-zinc-100 dark:bg-zinc-600/50 dark:border-zinc-400/50 dark:hover:bg-zinc-600/70'
                    : canToggle
                      ? 'opacity-0 group-hover:opacity-100 text-muted-foreground bg-card border-border hover:bg-accent hover:text-foreground dark:text-zinc-300 dark:bg-zinc-900 dark:border-zinc-700/60 dark:hover:bg-zinc-700 dark:hover:text-white'
                      : 'opacity-0 group-hover:opacity-100 text-muted-foreground/50 bg-card/80 border-border cursor-not-allowed dark:text-zinc-600 dark:bg-zinc-900/80 dark:border-zinc-800'
            }`}
            style={{ top: 4, left: -28 }}
            title={
                isMocked
                    ? 'Clear mock data (use live output)'
                    : canToggle
                      ? 'Pin output as mock data'
                      : 'Run this node first to pin its output'
            }
        >
            {isMocked ? <PinOff size={12} /> : <Pin size={12} />}
        </button>
    );
}

// Disable toggle — bottom-left corner, clear of the centered input handle. A
// disabled node is skipped at run time (data.disabled round-trips to the
// backend). Stays visible while disabled so it can be re-enabled without
// hovering. Mirrors the D keyboard shortcut.
function DisablePill({
    nodeId,
    disabled,
}: {
    nodeId: string;
    disabled: boolean;
}) {
    return (
        <button
            onClick={(e) => {
                e.stopPropagation();
                dispatchNodeDataUpdate(nodeId, { disabled: !disabled });
            }}
            className={`absolute z-20 nodrag ${NODE_TOGGLE_BTN_BASE} ${
                disabled
                    ? 'opacity-100 text-amber-600 bg-amber-100 border-amber-300 hover:bg-amber-200 dark:text-amber-300 dark:bg-amber-500/20 dark:border-amber-400/50 dark:hover:bg-amber-500/30'
                    : 'opacity-0 group-hover:opacity-100 text-muted-foreground dark:text-zinc-300 bg-card border-border dark:border-zinc-700/60 hover:bg-amber-500 hover:text-white hover:border-amber-400/60 dark:text-zinc-300 dark:bg-zinc-900 dark:border-zinc-700/60'
            }`}
            style={{ bottom: 4, left: -28 }}
            title={disabled ? 'Enable node' : 'Disable node (skip at run time)'}
        >
            <Ban size={12} />
        </button>
    );
}

export function withNodeWrapper<P extends NodeProps>(
    WrappedComponent: ComponentType<P>
): ComponentType<P> {
    // First wrap with collaborative border
    const WithBorder = withCollaborativeBorder(WrappedComponent);

    const WithNodeWrapper = (props: P) => {
        const customLabel = props.data?.label as string | undefined;
        const runData = props.data as
            | {
                  _lastRunStatus?: string;
                  _lastRunAt?: number;
                  executionState?: string;
              }
            | undefined;
        const execState = runData?.executionState;
        const lastRunStatus = runData?._lastRunStatus;
        const lastRunAt = runData?._lastRunAt;
        const toggleData = props.data as
            | { disabled?: boolean; mockedOutput?: unknown; output?: unknown }
            | undefined;
        const isReadOnly =
            (props.data as { isReadOnly?: boolean } | undefined)?.isReadOnly ===
            true;
        const previewHidden =
            (props.data as { _previewHidden?: boolean } | undefined)
                ?._previewHidden === true;
        const showAffordances =
            shouldShowAffordances(props.type) && !isReadOnly;
        const showNextStepHint =
            shouldShowNextStepHint(props.type) && !isReadOnly;
        const showDelete = shouldShowDelete(props.type) && !isReadOnly;

        return (
            <>
                <WithBorder
                    {...props}
                    extraContent={
                        <>
                            {/* Run-status aurora (running sweep + completed treatment) on every node
                  type — automation and special alike — via the one shared overlay. */}
                            <NodeAuroraLayers
                                data={{
                                    ...(props.data as {
                                        configValid?: boolean;
                                        isReadOnly?: boolean;
                                    }),
                                    executionState: execState,
                                    _lastRunStatus: lastRunStatus,
                                }}
                                selected={props.selected}
                                nodeType={props.type}
                            />
                            {showDelete && (
                                <>
                                    {showAffordances && (
                                        <RunFromHerePill nodeId={props.id} />
                                    )}
                                    <DeletePill nodeId={props.id} />
                                    {showAffordances && (
                                        <>
                                            <PinPill
                                                nodeId={props.id}
                                                mockedOutput={
                                                    toggleData?.mockedOutput
                                                }
                                                output={toggleData?.output}
                                            />
                                            <DisablePill
                                                nodeId={props.id}
                                                disabled={
                                                    toggleData?.disabled ===
                                                    true
                                                }
                                            />
                                        </>
                                    )}
                                    {showNextStepHint && (
                                        <NextStepHintGroup nodeId={props.id} />
                                    )}
                                </>
                            )}
                        </>
                    }
                />
                <NodeLabel
                    nodeId={props.id}
                    nodeType={props.type || ''}
                    customLabel={customLabel}
                    lastRunStatus={lastRunStatus}
                    lastRunAt={lastRunAt}
                    isRunning={execState === 'running'}
                    showInterfaceBadge={showAffordances}
                    hidden={previewHidden}
                />
            </>
        );
    };

    WithNodeWrapper.displayName = `WithNodeWrapper(${
        WrappedComponent.displayName || WrappedComponent.name || 'Component'
    })`;

    return WithNodeWrapper;
}
