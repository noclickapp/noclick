// Shared AI-editing UI primitives used by both AutomationNode (desktop ReactFlow path)
// and ForkCanvas's GenericCard (xyflow-free path). Updates to the expand animation,
// status text, or overlay layout land in both places at once.

import { useEffect, useMemo, useState } from 'react';
import { Loader2, CheckCircle2 } from 'lucide-react';
import { BrandIcon } from '~/components/shared/BrandIcon';
import {
    getIsAiEditing,
    isNodeBeingEdited,
    getNodeEditInfo,
    isNodeBeingEditedByRemote,
    type NodeEditInfo,
} from '../../WorkflowContext';

// Dimensions for the expand animation. Card transitions from its normal size to
// EXPANDED_WIDTH × EXPANDED_HEIGHT when AI starts editing it. EDIT_ICON_SIZE is the
// inner icon size on the left section of the overlay.
export const EDIT_EXPANDED_WIDTH = 220;
export const EDIT_EXPANDED_HEIGHT = 90;
export const EDIT_ICON_SIZE = 28;

// CSS transition that all callers should put on the wrapper so the resize is smooth.
// Constants used here match AutomationNode's existing values.
export const EDIT_TRANSITION = 'width 300ms ease-out, height 300ms ease-out';

/** Per-node AI editing state. Polls the workflow editor store (a module-level Map,
 *  not React-reactive) every 100ms so callers can render an editing overlay. Set
 *  options.skip to true to disable the polling (e.g. for read-only canvases that
 *  never enter the editing state). */
export function useNodeEditingState(
    nodeId: string,
    options: { skip?: boolean; previewEditInfo?: NodeEditInfo | null } = {}
) {
    const [state, setState] = useState<{
        isBeingEdited: boolean;
        editInfo?: NodeEditInfo;
        remoteEditorName?: string;
    }>({ isBeingEdited: false });
    const skip = options.skip ?? false;
    const previewEditInfo = options.previewEditInfo;
    // Product demos and other read-only surfaces can opt into the exact
    // production editing treatment without mutating the editor singleton. This
    // keeps the preview honest while preventing it from interfering with a real
    // workflow that happens to be open in another surface. It is derived during
    // render, not in an effect: an effect leaves the node's FIRST paint (and so
    // the size the canvas measures) un-edited, and the camera then frames a
    // graph the card is about to outgrow — the card ends up cropped.
    const previewState = useMemo(
        () =>
            previewEditInfo === undefined
                ? null
                : {
                      isBeingEdited: previewEditInfo !== null,
                      editInfo: previewEditInfo ?? undefined,
                      remoteEditorName: undefined,
                  },
        [previewEditInfo]
    );
    useEffect(() => {
        if (previewEditInfo !== undefined) return;
        if (skip) {
            setState({
                isBeingEdited: false,
                editInfo: undefined,
                remoteEditorName: undefined,
            });
            return;
        }
        const check = () => {
            if (getIsAiEditing() && isNodeBeingEdited(nodeId)) {
                setState({
                    isBeingEdited: true,
                    editInfo: getNodeEditInfo(nodeId),
                    remoteEditorName: undefined,
                });
                return;
            }
            const remote = isNodeBeingEditedByRemote(nodeId);
            if (remote) {
                setState({
                    isBeingEdited: true,
                    editInfo: remote.info,
                    remoteEditorName: remote.userName,
                });
                return;
            }
            setState({
                isBeingEdited: false,
                editInfo: undefined,
                remoteEditorName: undefined,
            });
        };
        check();
        const interval = setInterval(check, 100);
        return () => clearInterval(interval);
    }, [nodeId, previewEditInfo, skip]);
    return previewState ?? state;
}

/** Status line label — mirrors AutomationNode's getStatusText behavior. */
function getStatusText(
    editInfo: NodeEditInfo | undefined,
    remoteEditorName?: string
): string {
    const prefix = remoteEditorName ? `${remoteEditorName}: ` : '';
    if (!editInfo) return `${prefix}Processing...`;
    if (editInfo.status === 'complete') {
        const action =
            editInfo.action === 'added'
                ? 'Added'
                : editInfo.action === 'removed'
                  ? 'Removed'
                  : 'Updated';
        return `${prefix}${action}`;
    }
    const action =
        editInfo.action === 'added'
            ? 'Adding...'
            : editInfo.action === 'removed'
              ? 'Removing...'
              : 'Updating...';
    return `${prefix}${action}`;
}

interface NodeEditOverlayProps {
    Icon: React.ComponentType<{
        className?: string;
        style?: React.CSSProperties;
    }>;
    iconColor?: string;
    editInfo?: NodeEditInfo;
    remoteEditorName?: string;
}

/** The icon-on-left + status-on-right layout shown when AI is editing a node. Caller
 *  is responsible for the outer container (with width transition, border, background)
 *  — this component just renders the inner flex row. */
export function NodeEditOverlay({
    Icon,
    iconColor,
    editInfo,
    remoteEditorName,
}: NodeEditOverlayProps) {
    return (
        <div className="flex h-full">
            {/* Icon section — left side */}
            <div
                className="shrink-0 flex items-center justify-center border-r border-border dark:border-white/[0.06] overflow-hidden"
                style={{
                    width: 56,
                    // The card is still resizing when this mounts; capping the
                    // compartment at the card's own width keeps the icon
                    // inside it for the whole expand.
                    maxWidth: '100%',
                    background:
                        'radial-gradient(circle at 50% 50%, hsl(var(--accent) / 0.6), transparent)',
                }}
            >
                <BrandIcon
                    Icon={Icon}
                    iconColor={iconColor}
                    style={{
                        width: EDIT_ICON_SIZE,
                        height: EDIT_ICON_SIZE,
                        maxWidth: '100%',
                        maxHeight: '100%',
                        objectFit: 'contain',
                        filter: 'drop-shadow(0 2px 6px rgba(0, 0, 0, calc(0.4 * var(--icon-shadow-scale, 1))))',
                    }}
                />
            </div>

            {/* Content section — right side */}
            <div className="flex-1 flex flex-col justify-center px-3 py-2 min-w-0">
                <div className="flex items-center gap-2">
                    {editInfo?.status === 'processing' ? (
                        <Loader2 className="w-3.5 h-3.5 text-muted-foreground dark:text-white/50 animate-spin shrink-0" />
                    ) : (
                        <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500/80 shrink-0" />
                    )}
                    <span className="text-[11px] font-medium text-foreground/70 uppercase tracking-wide">
                        {getStatusText(editInfo, remoteEditorName)}
                    </span>
                </div>

                {editInfo?.operation && (
                    <div className="mt-1.5 flex items-center gap-1.5">
                        <span className="text-[10px] text-muted-foreground/80 dark:text-white/40 uppercase tracking-wider">
                            Action:
                        </span>
                        <span className="text-[11px] font-medium text-emerald-600 dark:text-emerald-400 truncate">
                            {editInfo.operation}
                        </span>
                    </div>
                )}

                {editInfo?.config &&
                    Object.keys(editInfo.config).length > 0 && (
                        <div className="mt-1 font-mono text-[9px] text-muted-foreground/80 dark:text-white/40 space-y-0.5 max-h-[32px] overflow-hidden">
                            {Object.entries(editInfo.config)
                                .slice(0, 2)
                                .map(([key, value]) => (
                                    <div
                                        key={key}
                                        className="flex gap-1 truncate"
                                    >
                                        <span className="text-muted-foreground/70 dark:text-white/50">
                                            {key}:
                                        </span>
                                        <span className="text-muted-foreground dark:text-white/50 truncate">
                                            {value === null
                                                ? 'null'
                                                : typeof value === 'object'
                                                  ? '...'
                                                  : String(value).slice(0, 20)}
                                        </span>
                                    </div>
                                ))}
                            {Object.keys(editInfo.config).length > 2 && (
                                <span className="text-muted-foreground/70 dark:text-white/50">
                                    +{Object.keys(editInfo.config).length - 2}{' '}
                                    more
                                </span>
                            )}
                        </div>
                    )}
            </div>
        </div>
    );
}
