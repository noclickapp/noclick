// AgentWiringChips renders the agent's wiring under its Message field in the
// canvas config panel: one chip per wired trigger and per tool provider.
// Chips are clickable — triggers open the palette's credential step (when the
// type takes credentials), tools open the in-palette allowlist/mounts config.
// × deletes the edge via the same deleteElements path as the edge's own
// delete button (keeps collab sync; the node stays visible on canvas).
// "+ Add" buttons open the shared AgentWiringPalette.

import { useState } from 'react';
import { Plus, X } from 'lucide-react';
import { useReactFlow } from '@xyflow/react';
import { BrandIcon } from '~/components/shared/BrandIcon';
import { getNodeCredentialInfo, type AgentTriggerSource, type AgentWiredTool } from '~/utils/nodeSchemas';
import { AgentWiringPalette, type PaletteConfigNode, type WiredNodeData } from './AgentWiringPalette';
import { FieldRequirementBadge } from './FieldRequirementBadge';
import { getNodeDisplayName, getNodeMetadata } from './nodes/nodeRegistry';

interface AgentWiringChipsProps {
    /** 'agent' (default): triggers + tools sections under the Message field.
     *  'mcp': tools only — the wired providers ARE the hosted server's tools. */
    variant?: 'agent' | 'mcp';
    triggers: AgentTriggerSource[];
    tools: AgentWiredTool[];
    /** Wire a new trigger/tool to this agent (FlowCanvas callback); absent in
     *  read-only surfaces — hides add/config affordances. Returns the new
     *  node id so the palette can continue into its config step. */
    onAdd?: (nodeType: string, role: 'trigger' | 'tool', operation?: string) => string | void;
    onWiredNodeConfigPatch?: (nodeId: string, config: Record<string, unknown>) => void;
    onWiredNodeCredentialsChange?: (nodeId: string, credentialIds: Record<string, string>) => void;
    getWiredNodeData?: (nodeId: string) => WiredNodeData | null;
    workflowId?: string;
}

function Chip({
    nodeType,
    label,
    badge,
    chipTitle,
    onOpen,
    onRemove,
    removeTitle,
}: {
    nodeType: string;
    label: string;
    badge?: string;
    chipTitle?: string;
    onOpen?: () => void;
    onRemove: () => void;
    removeTitle: string;
}) {
    const meta = getNodeMetadata(nodeType);
    const body = (
        <>
            {meta?.Icon && (
                <BrandIcon Icon={meta.Icon} iconColor={meta.iconColor} className="h-4 w-4 flex-shrink-0" />
            )}
            <span className="max-w-[200px] truncate">{label}</span>
            {badge && <span className="text-[10px] text-muted-foreground dark:text-zinc-500 tabular-nums">{badge}</span>}
        </>
    );
    return (
        <span className="inline-flex items-center gap-2 rounded-lg border border-muted-foreground/40 dark:border-zinc-600/80 bg-card dark:bg-muted/80 px-3 py-1.5 text-[13px] font-medium text-foreground">
            {onOpen ? (
                <button
                    type="button"
                    onClick={onOpen}
                    title={chipTitle}
                    className="inline-flex items-center gap-2 transition-colors hover:text-foreground"
                >
                    {body}
                </button>
            ) : (
                body
            )}
            <button
                type="button"
                onClick={onRemove}
                className="-mr-1 rounded p-0.5 text-muted-foreground dark:text-zinc-500 transition-colors hover:bg-foreground/[0.08] hover:text-foreground"
                title={removeTitle}
            >
                <X className="h-3.5 w-3.5" />
            </button>
        </span>
    );
}

export function AgentWiringChips({
    variant = 'agent',
    triggers,
    tools,
    onAdd,
    onWiredNodeConfigPatch,
    onWiredNodeCredentialsChange,
    getWiredNodeData,
    workflowId,
}: AgentWiringChipsProps) {
    const { deleteElements } = useReactFlow();
    const [palette, setPalette] = useState<
        { role: 'trigger' | 'tool'; configNode?: PaletteConfigNode } | null
    >(null);
    if (!triggers.length && !tools.length && !onAdd) return null;

    const canConfigure = !!getWiredNodeData;
    const removeEdge = (edgeId: string) => deleteElements({ edges: [{ id: edgeId }] });

    return (
        <div className="mt-2 space-y-3">
            {variant === 'agent' && (
            <div className="space-y-1.5">
                <div className="text-xs text-muted-foreground leading-relaxed">
                    {triggers.length > 0
                        ? 'This agent runs whenever one of these triggers fires. The fired event is delivered to the agent along with the message above.'
                        : 'Add a trigger to run this agent automatically — the fired event is delivered along with the message above.'}
                </div>
                <div className="flex flex-wrap gap-2">
                    {triggers.map(t => (
                        <Chip
                            key={t.edgeId}
                            nodeType={t.nodeType}
                            label={t.label || getNodeDisplayName(t.nodeType)}
                            badge={t.operation}
                            chipTitle="Configure trigger credentials"
                            onOpen={
                                canConfigure && getNodeCredentialInfo(t.nodeType)
                                    ? () =>
                                          setPalette({
                                              role: 'trigger',
                                              configNode: { nodeId: t.nodeId, nodeType: t.nodeType, role: 'trigger' },
                                          })
                                    : undefined
                            }
                            onRemove={() => removeEdge(t.edgeId)}
                            removeTitle="Disconnect this trigger from the agent"
                        />
                    ))}
                    {onAdd && (
                        <button
                            type="button"
                            onClick={() => setPalette({ role: 'trigger' })}
                            className="inline-flex items-center gap-1.5 rounded-md border border-dashed border-border dark:border-zinc-700 bg-card dark:bg-transparent px-2.5 py-1.5 text-[12px] text-muted-foreground transition-colors hover:border-muted-foreground/40 dark:hover:border-zinc-500 hover:text-foreground"
                        >
                            <Plus className="h-3.5 w-3.5" />
                            Add trigger
                        </button>
                    )}
                </div>
            </div>
            )}

            <div className={variant === 'agent' ? 'space-y-1.5 pt-2' : 'space-y-1.5'}>
                <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-muted-foreground">
                    Tools
                    <FieldRequirementBadge isRequired={false} />
                </div>
                {tools.length === 0 && (
                    <div className="text-xs text-muted-foreground leading-relaxed">
                        {variant === 'mcp'
                            ? 'Add services whose actions this server exposes — you pick exactly which. Wired tools serve to agents on the canvas and to external MCP clients.'
                            : 'Add a service to let the agent act on it — you pick exactly which actions it may call.'}
                    </div>
                )}
                <div className="flex flex-wrap gap-2">
                    {tools.map(t => (
                        <Chip
                            key={t.edgeId}
                            nodeType={t.nodeType}
                            label={t.label || getNodeDisplayName(t.nodeType)}
                            badge={
                                t.nodeType === 'mcp-server' ? 'MCP server'
                                : t.nodeType === 'alarm' ? '4 alarm tools'
                                : t.nodeType === 'filesystem' ? 'sandbox + upload_file'
                                : t.nodeType === 'tool' ? 'custom tool'
                                : `${t.operations.length} action${t.operations.length === 1 ? '' : 's'}`
                            }
                            chipTitle="Configure credentials and allowed actions"
                            onOpen={
                                canConfigure
                                    ? () =>
                                          setPalette({
                                              role: 'tool',
                                              configNode: { nodeId: t.nodeId, nodeType: t.nodeType, role: 'tool' },
                                          })
                                    : undefined
                            }
                            onRemove={() => removeEdge(t.edgeId)}
                            removeTitle="Disconnect this tool from the agent"
                        />
                    ))}
                    {onAdd && (
                        <button
                            type="button"
                            onClick={() => setPalette({ role: 'tool' })}
                            className="inline-flex items-center gap-1.5 rounded-md border border-dashed border-border dark:border-zinc-700 bg-card dark:bg-transparent px-2.5 py-1.5 text-[12px] text-muted-foreground transition-colors hover:border-muted-foreground/40 dark:hover:border-zinc-500 hover:text-foreground"
                        >
                            <Plus className="h-3.5 w-3.5" />
                            Add tool
                        </button>
                    )}
                </div>
            </div>

            {palette && (
                <AgentWiringPalette
                    open
                    wiringRole={palette.role}
                    configNode={palette.configNode}
                    onClose={() => setPalette(null)}
                    onPick={(nodeType, operation) =>
                        onAdd ? onAdd(nodeType, palette.role, operation) : undefined
                    }
                    onWiredNodeConfigPatch={onWiredNodeConfigPatch}
                    onWiredNodeCredentialsChange={onWiredNodeCredentialsChange}
                    getWiredNodeData={getWiredNodeData}
                    workflowId={workflowId}
                />
            )}
        </div>
    );
}
