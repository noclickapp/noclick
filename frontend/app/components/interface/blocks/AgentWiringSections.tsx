// Triggers + Tools sections of the agent chat sidebar: list the trigger and
// tool-provider nodes wired to this agent on the canvas, and let interface
// users add/remove them without leaving the chat. Adding and configuring both
// happen in the shared AgentWiringPalette (command-palette modal): adding a
// tool flows straight into its allowlist config step, and clicking a wired
// tool row reopens that step.

import { useState } from 'react';
import { Plus, Settings2, Wrench, X, Zap } from 'lucide-react';
import { BrandIcon } from '~/components/shared/BrandIcon';
import { AgentWiringPalette, type PaletteConfigNode, type WiredNodeData } from '~/components/workflow/AgentWiringPalette';
import { getNodeCredentialInfo } from '~/utils/nodeSchemas';
import { getNodeDisplayName, getNodeMetadata } from '~/components/workflow/nodes/nodeRegistry';
import { useCachedCredentialList } from '~/hooks/useCachedCredentialList';
import { attachedCredentialsHealth } from '~/lib/credentialHealth';
import type { AgentTriggerSource, AgentWiredTool } from '~/utils/nodeSchemas';
import type { AgentWiring } from '../types';

interface AgentWiringSectionsProps {
    wiring?: AgentWiring;
    isReadOnly?: boolean;
    onAdd?: (nodeType: string, role: 'trigger' | 'tool', operation?: string) => string | void;
    onRemove?: (edgeId: string, nodeId: string) => void;
    onWiredNodeConfigPatch?: (nodeId: string, config: Record<string, unknown>) => void;
    onWiredNodeCredentialsChange?: (nodeId: string, credentialIds: Record<string, string>) => void;
    getWiredNodeData?: (nodeId: string) => WiredNodeData | null;
    workflowId?: string;
}

const nodeLabel = (label: string, nodeType: string) =>
    label || getNodeDisplayName(nodeType);

function NodeGlyph({ nodeType, className = 'h-4 w-4' }: { nodeType: string; className?: string }) {
    const meta = getNodeMetadata(nodeType);
    if (!meta?.Icon) return null;
    return <BrandIcon Icon={meta.Icon} iconColor={meta.iconColor} className={`${className} flex-shrink-0`} />;
}

function SectionHeader({
    icon,
    title,
    onAdd,
}: {
    icon: React.ReactNode;
    title: string;
    onAdd?: () => void;
}) {
    return (
        <div className="flex items-center justify-between mb-2">
            <label className="flex items-center gap-1.5 text-[11px] uppercase tracking-wider text-muted-foreground dark:text-zinc-500">
                {icon}
                {title}
            </label>
            {onAdd && (
                <button
                    type="button"
                    onClick={onAdd}
                    className="flex items-center gap-1 text-[11px] font-medium text-muted-foreground hover:text-foreground px-1.5 py-0.5 rounded-md hover:bg-foreground/[0.06] transition-colors"
                >
                    <Plus className="h-3 w-3" />
                    Add
                </button>
            )}
        </div>
    );
}

export function AgentWiringSections({
    wiring,
    isReadOnly,
    onAdd,
    onRemove,
    onWiredNodeConfigPatch,
    onWiredNodeCredentialsChange,
    getWiredNodeData,
    workflowId,
}: AgentWiringSectionsProps) {
    // null = closed; configNode set = palette opens straight in the config
    // step for that wired node (credentials; + allowlist/mounts for tools).
    const [palette, setPalette] = useState<
        { role: 'trigger' | 'tool'; configNode?: PaletteConfigNode } | null
    >(null);

    const triggers: AgentTriggerSource[] = wiring?.triggers ?? [];
    const tools: AgentWiredTool[] = wiring?.tools ?? [];
    // Attached-credential health (revoked/deleted) — a dead credential must be
    // called out explicitly, not sit behind the same dot as "none connected".
    const credentialList = useCachedCredentialList();
    const canEdit = !isReadOnly && !!onAdd;

    return (
        <>
            <section data-testid="agent-chat-triggers-section">
                <SectionHeader
                    icon={<Zap className="h-3 w-3 text-amber-600 dark:text-amber-400" fill="currentColor" />}
                    title="Triggers"
                    onAdd={canEdit ? () => setPalette({ role: 'trigger' }) : undefined}
                />
                {triggers.length === 0 && (
                    <p className="text-[11px] text-muted-foreground/70 dark:text-zinc-600 leading-relaxed">
                        No triggers connected. Add one to run this agent automatically when
                        an external event fires — the event is delivered as its message.
                    </p>
                )}
                <div className="space-y-1.5">
                    {triggers.map(t => (
                        <div
                            key={t.edgeId}
                            className="flex items-center gap-2 rounded-lg border border-border bg-sunken px-2.5 py-2"
                        >
                            <button
                                type="button"
                                disabled={!canEdit || !getNodeCredentialInfo(t.nodeType)}
                                onClick={() =>
                                    setPalette({
                                        role: 'trigger',
                                        configNode: { nodeId: t.nodeId, nodeType: t.nodeType, role: 'trigger' },
                                    })
                                }
                                title={getNodeCredentialInfo(t.nodeType) ? 'Configure trigger credentials' : undefined}
                                className="flex min-w-0 flex-1 items-center gap-2 text-left disabled:cursor-default"
                            >
                                <NodeGlyph nodeType={t.nodeType} />
                                <div className="min-w-0 flex-1">
                                    <div className="text-xs text-foreground truncate">{nodeLabel(t.label, t.nodeType)}</div>
                                    {t.operation && (
                                        <div className="text-[10px] text-muted-foreground dark:text-zinc-500 truncate">{t.operation}</div>
                                    )}
                                </div>
                            </button>
                            {canEdit && onRemove && (
                                <button
                                    type="button"
                                    onClick={() => onRemove(t.edgeId, t.nodeId)}
                                    title="Disconnect this trigger"
                                    className="rounded p-0.5 text-muted-foreground dark:text-zinc-500 hover:bg-foreground/[0.08] hover:text-foreground transition-colors"
                                >
                                    <X className="h-3.5 w-3.5" />
                                </button>
                            )}
                        </div>
                    ))}
                </div>
            </section>

            <section data-testid="agent-chat-tools-section">
                <SectionHeader
                    icon={<Wrench className="h-3 w-3" />}
                    title="Tools"
                    onAdd={canEdit ? () => setPalette({ role: 'tool' }) : undefined}
                />
                {tools.length === 0 && (
                    <p className="text-[11px] text-muted-foreground/70 dark:text-zinc-600 leading-relaxed">
                        No tools connected. Add a service to let the agent act on it —
                        you choose exactly which actions it may call.
                    </p>
                )}
                <div className="space-y-1.5">
                    {tools.map(t => {
                        const credHealth = t.credentialsMissing
                            ? 'ok' // "none connected" has its own indicator below
                            : attachedCredentialsHealth(t.credentialIds, credentialList);
                        return (
                        <div
                            key={t.edgeId}
                            className="flex items-center gap-2 rounded-lg border border-border bg-sunken px-2.5 py-2"
                        >
                            <button
                                type="button"
                                onClick={() =>
                                    setPalette({
                                        role: 'tool',
                                        configNode: { nodeId: t.nodeId, nodeType: t.nodeType, role: 'tool' },
                                    })
                                }
                                title="Configure which actions the agent may call"
                                className="flex min-w-0 flex-1 items-center gap-2 text-left"
                            >
                                <NodeGlyph nodeType={t.nodeType} />
                                <span className="min-w-0 flex-1 text-xs text-foreground truncate">
                                    {nodeLabel(t.label, t.nodeType)}
                                </span>
                                {t.credentialsMissing && (
                                    <span
                                        className="flex items-center gap-1 flex-shrink-0"
                                        title="No credentials connected — the agent's calls to this tool will fail"
                                    >
                                        <span className="h-1.5 w-1.5 rounded-full bg-amber-400" />
                                        <span className="text-[10px] font-medium text-amber-600 dark:text-amber-400">
                                            Connect
                                        </span>
                                    </span>
                                )}
                                {credHealth !== 'ok' && (
                                    <span
                                        data-testid="agent-tool-credential-broken"
                                        className="flex items-center gap-1 flex-shrink-0"
                                        title={
                                            credHealth === 'revoked'
                                                ? 'The attached credential was disconnected or revoked — the agent\'s calls will fail until you reconnect it'
                                                : 'The attached credential no longer exists — the agent\'s calls will fail until you reconnect it'
                                        }
                                    >
                                        <span className="h-1.5 w-1.5 rounded-full bg-red-500 dark:bg-red-400" />
                                        <span className="text-[10px] font-medium text-red-600 dark:text-red-400">
                                            {credHealth === 'revoked' ? 'Revoked' : 'Reconnect'}
                                        </span>
                                    </span>
                                )}
                                <span className="text-[10px] text-muted-foreground dark:text-zinc-500 tabular-nums flex-shrink-0">
                                    {t.nodeType === 'mcp-server' ? 'MCP server' : `${t.operations.length} action${t.operations.length === 1 ? '' : 's'}`}
                                </span>
                                <Settings2 className="h-3 w-3 text-muted-foreground/70 dark:text-zinc-600 flex-shrink-0" />
                            </button>
                            {canEdit && onRemove && (
                                <button
                                    type="button"
                                    onClick={() => onRemove(t.edgeId, t.nodeId)}
                                    title="Disconnect this tool"
                                    className="rounded p-0.5 text-muted-foreground dark:text-zinc-500 hover:bg-foreground/[0.08] hover:text-foreground transition-colors"
                                >
                                    <X className="h-3.5 w-3.5" />
                                </button>
                            )}
                        </div>
                        );
                    })}
                </div>
            </section>

            {onAdd && palette && (
                <AgentWiringPalette
                    open
                    wiringRole={palette.role}
                    configNode={palette.configNode}
                    onClose={() => setPalette(null)}
                    onPick={(nodeType, operation) => onAdd(nodeType, palette.role, operation)}
                    onWiredNodeConfigPatch={onWiredNodeConfigPatch}
                    onWiredNodeCredentialsChange={onWiredNodeCredentialsChange}
                    getWiredNodeData={getWiredNodeData}
                    workflowId={workflowId}
                />
            )}
        </>
    );
}
