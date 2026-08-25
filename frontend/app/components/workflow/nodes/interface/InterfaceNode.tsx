// Shared ReactFlow node component for all interface nodes.
// Renders the actual UI block (textbox, slider, button, etc.) at full size inside ReactFlow,
// making the block interactive directly on the canvas. Supports resize via NodeResizer.

import { memo, useCallback, useState } from 'react';
import {
    NodeProps,
    Handle,
    Position,
    NodeResizer,
    useReactFlow,
} from '@xyflow/react';
import { BlockRenderer } from '~/components/interface/BlockRenderer';
import { BlockHeaderSlotContext } from '~/components/interface/BlockWrapper';
import { getBlockDefinition } from '~/components/interface/blockRegistry';
import { useFormSubmit } from '~/contexts/FormSubmitContext';
import type { BlockConfig } from '~/components/interface/types';
import {
    normalizeNodeUpdatePayload,
    updateNodeInList,
} from '~/lib/applyNodeUpdate';
import { resolveInterfaceBlockLabel } from '~/utils/interfaceNodes';
import { useWorkflowId } from '../../WorkflowContext';
import { CONNECTIONLESS_TYPES } from '../connectionlessTypes';
import { isTriggerSource } from '~/utils/nodeSchemas';
import { TriggerBoltBadge } from '../base/TriggerBoltBadge';
import { InterfaceBlockHeader } from './InterfaceBlockHeader';
import { InterfaceFormLinkButton } from './InterfaceFormLinkButton';

const HANDLE_CLASS =
    '!w-4 !h-4 !bg-zinc-300 dark:!bg-zinc-400 !border-2 !border-zinc-400 dark:!border-zinc-500 hover:!bg-zinc-300 hover:!border-zinc-300 dark:!border-zinc-400 transition-all';

interface InterfaceNodeProps extends NodeProps {
    Icon: React.ComponentType<{
        className?: string;
        style?: React.CSSProperties;
    }>;
    iconColor: string;
}

/** Extracts the block type from a node type (e.g. 'interface-markdown' → 'markdown').
 *  The image/audio/video blocks were merged into the universal 'file' block, and the
 *  config-form block into the unified 'form' block (both 2026-07) — legacy node types
 *  resolve to the merged block so pre-merge workflows keep working. */
function getBlockType(nodeType: string | undefined): string {
    const blockType = (nodeType ?? '').replace(/^interface-/, '');
    if (blockType === 'image' || blockType === 'audio' || blockType === 'video') {
        return 'file';
    }
    if (blockType === 'config-form') {
        return 'form';
    }
    return blockType;
}

const InterfaceNodeComponent = ({
    id,
    type,
    data,
    selected,
    iconColor,
}: InterfaceNodeProps) => {
    const blockType = getBlockType(type);
    const def = getBlockDefinition(blockType);
    const Icon = def?.icon;
    const showHandles = !CONNECTIONLESS_TYPES.has(type ?? '');
    // The unified form node is a workflow entry point: like other trigger nodes,
    // nothing flows in — the input handle is replaced by the amber bolt.
    const isTrigger = isTriggerSource(
        type,
        (data as Record<string, unknown> | undefined)?.operation as
            | string
            | undefined
    );
    // Config fields live under data.config (authoritative), with label from data metadata.
    // operation lives at data.operation (top-level), so merge it in for blocks that need it.
    const rawConfig = ((data?.config as BlockConfig | undefined) ??
        {}) as BlockConfig;
    const blockConfig = data?.operation
        ? { ...rawConfig, operation: data.operation as string }
        : rawConfig;
    const label = resolveInterfaceBlockLabel(
        data?.label as string | undefined,
        blockConfig.label as string | undefined,
        def?.label,
        blockType,
    );

    const { setNodes, getNodes } = useReactFlow();
    const formSubmit = useFormSubmit();
    const workflowId = useWorkflowId();
    const isReadOnly = !!(data?.isReadOnly as boolean | undefined);
    // Track resize to disable iframe pointer events (prevents event capture by iframe)
    const [resizing, setResizing] = useState(false);
    // Ref callback so block children can portal header actions into the title bar.
    const [headerSlot, setHeaderSlot] = useState<HTMLDivElement | null>(null);

    const handleConfigChange = useCallback(
        (config: BlockConfig) => {
            setNodes((nodes) =>
                updateNodeInList(nodes, id, {
                    config: config as Record<string, any>,
                })
            );
        },
        [id, setNodes]
    );

    const handleSubmit = useCallback(
        (values: Record<string, unknown>) => {
            formSubmit?.(id, values);
        },
        [formSubmit, id]
    );

    return (
        <>
            <NodeResizer
                color="transparent"
                isVisible={true}
                minWidth={250}
                minHeight={120}
                handleStyle={{
                    width: '20px',
                    height: '20px',
                    border: 'none',
                    backgroundColor: 'transparent',
                    borderRadius: '0',
                    opacity: 0,
                    // Stack above the chrome (default 0) so the corner hit area
                    // is reachable inside the rounded frame, but below input/output
                    // handles (z-index 10) so those stay grabbable at the edge midpoints.
                    zIndex: 5,
                }}
                lineStyle={{
                    border: 'none',
                    opacity: 0,
                    zIndex: 5,
                }}
                onResizeStart={() => setResizing(true)}
                onResizeEnd={() => setResizing(false)}
            />

            {showHandles && (
                <>
                    {/* Input Handle (hidden on the trigger form node) */}
                    {!isTrigger && (
                        <Handle
                            type="target"
                            position={Position.Left}
                            className={HANDLE_CLASS}
                            style={{ zIndex: 10 }}
                        />
                    )}
                    {isTrigger && <TriggerBoltBadge />}

                    {/* Output Handle */}
                    <Handle
                        type="source"
                        position={Position.Right}
                        className={HANDLE_CLASS}
                        style={{ zIndex: 10 }}
                    />
                </>
            )}

            <div
                className={`rounded-xl overflow-hidden flex flex-col h-full w-full transition-all ${
                    selected
                        ? 'ring-2 ring-foreground/40 shadow-2xl dark:shadow-black/60'
                        : 'ring-1 ring-border dark:ring-white/[0.06] shadow-xl dark:shadow-black/50'
                } ${resizing ? 'nc-resizing' : ''}`}
                style={{
                    width: '100%',
                    height: '100%',
                    background: 'hsl(var(--card))',
                }}
            >
                {/* Browser-style header: icon + label on the left, Publish flush-right. */}
                <InterfaceBlockHeader
                    Icon={Icon}
                    iconColor={iconColor}
                    label={label}
                    headerSlotRef={setHeaderSlot}
                    trailing={
                        <>
                            <InterfaceFormLinkButton
                                nodeId={id}
                                nodeType={type}
                                config={rawConfig}
                                workflowId={workflowId}
                                isReadOnly={isReadOnly}
                            />
                        </>
                    }
                />

                {/* Block UI content */}
                <div className="flex-1 min-h-0 overflow-auto relative">
                    <BlockHeaderSlotContext.Provider value={headerSlot}>
                        <BlockRenderer
                            blockType={blockType}
                            id={id}
                            config={blockConfig}
                            output={
                                (data?.output as Record<string, unknown>) ??
                                null
                            }
                            isSelected={!!selected}
                            onConfigChange={
                                isReadOnly ? () => {} : handleConfigChange
                            }
                            onSubmit={
                                blockType === 'form' && !isReadOnly
                                    ? handleSubmit
                                    : undefined
                            }
                            isReadOnly={isReadOnly}
                            sdkBridge={{
                                getNodes,
                                updateNodeData: isReadOnly
                                    ? undefined
                                    : (nodeId, update) => {
                                          setNodes((nodes) =>
                                              updateNodeInList(
                                                  nodes,
                                                  nodeId,
                                                  normalizeNodeUpdatePayload(
                                                      update as Parameters<
                                                          typeof normalizeNodeUpdatePayload
                                                      >[0]
                                                  )
                                              )
                                          );
                                      },
                                readOnly: isReadOnly,
                            }}
                        />
                    </BlockHeaderSlotContext.Provider>
                    {/* Interaction shield. Iframe-based blocks (e.g. html-react) swallow
                        wheel/pointer events, which breaks canvas pan/zoom whenever the
                        cursor is over them. While the node is unselected this transparent
                        overlay sits above the iframe so gestures fall through to ReactFlow.
                        Inset by 8px so it doesn't cover the NodeResizer handles that sit
                        at the chrome's corners/edges (the chrome is edge-to-edge now). */}
                    {def?.usesIframe && !selected && (
                        <div className="absolute inset-2 z-10 cursor-pointer" />
                    )}
                </div>
            </div>
        </>
    );
};

export default memo(InterfaceNodeComponent);
