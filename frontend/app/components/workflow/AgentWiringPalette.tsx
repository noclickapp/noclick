// Command-palette modal for wiring triggers and tools to an AI agent. Visual
// language mirrors command/CommandPalette.tsx (same surface, rows, footer).
// Steps: service list (trigger services show a count of their trigger types;
// multi-trigger services drill into a second menu to pick the specific
// trigger), and tool config (the operation allowlist renders INSIDE the
// palette — both right after adding a tool and when editing an existing one).
// Reused by the agent chat sidebar and the canvas config panel.

import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { ArrowLeft, CornerDownLeft, Search, Wrench, Zap } from 'lucide-react';
import { BrandIcon } from '~/components/shared/BrandIcon';
import { usePickerKeyboardNav } from '~/hooks/usePickerKeyboardNav';
import { AgentToolOperationsPicker, SANDBOX_MOUNT_TYPES } from './AgentToolOperationsPicker';
import { NodeConfig } from './NodeConfig';
import { NodeCredentials, providerCredentialsMissing } from './NodeCredentials';
import { getNodeDisplayName, getNodeMetadata } from './nodes/nodeRegistry';
import { getAgentWirableCatalog, getNodeCredentialInfo, STRUCTURAL_AGENT_TOOL_TYPES, type TriggerOperation } from '~/utils/nodeSchemas';
import { fuzzyFilter } from '~/utils/fuzzySearch';
import { filterNodeServices, type NodeServiceTarget } from '~/utils/nodeServiceSearch';

/** Existing wired node to edit — opens the palette directly in the config
 *  step (credentials for triggers; credentials + allowlist + mounts for
 *  tools). Values are read LIVE via getWiredNodeData, never snapshotted. */
export interface PaletteConfigNode {
    nodeId: string;
    nodeType: string;
    role: 'trigger' | 'tool';
}

/** Live view of a wired node, re-read every render so credential OAuth
 *  completions and auto-selections show up without reopening. */
export interface WiredNodeData {
    nodeData: Record<string, unknown>;
    config: Record<string, unknown>;
    credentialIds: Record<string, string>;
}

export interface AgentWiringPaletteProps {
    open: boolean;
    wiringRole: 'trigger' | 'tool';
    onClose: () => void;
    /** Create the node + edge. Returns the new node id so the flow can
     *  continue into the in-palette config step. */
    onPick: (nodeType: string, operation?: string) => string | void;
    /** When set, the palette opens directly in the config step for this node. */
    configNode?: PaletteConfigNode | null;
    /** Patch a wired node's config (allowlist, sandbox mounts). */
    onWiredNodeConfigPatch?: (nodeId: string, config: Record<string, unknown>) => void;
    /** Patch a wired node's credentialIds (config step credential picker). */
    onWiredNodeCredentialsChange?: (nodeId: string, credentialIds: Record<string, string>) => void;
    /** Live accessor for a wired node's data. */
    getWiredNodeData?: (nodeId: string) => WiredNodeData | null;
    /** Workflow context — load_value config fields (webhook URLs, …) need it. */
    workflowId?: string;
}

export interface ServiceEntry extends NodeServiceTarget {
    triggerOps: TriggerOperation[];
}

/**
 * The palette's service rows for a role, alphabetical by display name. Rows
 * carry the registry's own label/description/keywords so the palette names
 * services the way the node palette does and searches the same aliases — the
 * type-derived label alone left e.g. Schedule reachable only by typing
 * "trigger cron". Exported so tests exercise the real registry-backed rows.
 */
export function buildWiringServices(role: 'trigger' | 'tool'): ServiceEntry[] {
    const catalog = getAgentWirableCatalog();
    const wirable =
        role === 'trigger'
            ? catalog.triggers.map(e => ({ nodeType: e.nodeType, triggerOps: e.triggerOps }))
            : catalog.tools.map(nodeType => ({ nodeType, triggerOps: [] as TriggerOperation[] }));
    return wirable
        .map(e => {
            const meta = getNodeMetadata(e.nodeType);
            return {
                ...e,
                label: getNodeDisplayName(e.nodeType),
                description: meta?.description,
                keywords: meta?.keywords,
            };
        })
        .sort((a, b) => a.label.localeCompare(b.label));
}

function PaletteRow({
    index,
    active,
    onHover,
    onSelect,
    icon,
    label,
    detail,
    badge,
}: {
    index: number;
    active: boolean;
    onHover: () => void;
    onSelect: () => void;
    icon: React.ReactNode;
    label: string;
    detail?: string;
    badge?: string;
}) {
    return (
        <button
            type="button"
            data-flat-index={index}
            onMouseMove={onHover}
            onClick={onSelect}
            className={`group flex w-full items-center gap-3 rounded-lg px-2.5 py-2 text-left transition-colors ${
                active ? 'bg-foreground/[0.08]' : 'hover:bg-foreground/[0.04]'
            }`}
        >
            {icon}
            {/* When a detail is present (trigger-ops rows) the name takes its
                natural width and the description flex-grows + truncates, so the
                action name is never the one clipped. With no detail (service
                rows) the name flex-fills to push the trailing badge right. */}
            <span className={`min-w-0 truncate text-[13px] text-foreground ${detail ? '' : 'flex-1'}`}>{label}</span>
            {detail && <span className="min-w-0 flex-1 truncate text-[11px] text-muted-foreground dark:text-zinc-500">{detail}</span>}
            {badge && (
                <span className="shrink-0 rounded-full border border-border dark:border-white/[0.08] bg-foreground/[0.04] px-1.5 py-px text-[10px] text-muted-foreground tabular-nums">
                    {badge}
                </span>
            )}
            <CornerDownLeft
                className={`h-3.5 w-3.5 shrink-0 text-muted-foreground/70 dark:text-zinc-600 transition-opacity ${
                    active ? 'opacity-100' : 'opacity-0'
                }`}
            />
        </button>
    );
}

export function AgentWiringPalette({
    open,
    wiringRole,
    onClose,
    onPick,
    configNode: configNodeProp,
    onWiredNodeConfigPatch,
    onWiredNodeCredentialsChange,
    getWiredNodeData,
    workflowId,
}: AgentWiringPaletteProps) {
    const [search, setSearch] = useState('');
    // Drill-in state: a multi-trigger service whose specific trigger is being
    // picked, or a tool whose allowlist is being configured in-palette.
    const [opsService, setOpsService] = useState<ServiceEntry | null>(null);
    const [configNode, setConfigNode] = useState<PaletteConfigNode | null>(null);
    const listRef = useRef<HTMLDivElement>(null);
    const searchRef = useRef<HTMLInputElement>(null);

    const services = useMemo<ServiceEntry[]>(
        () => (open ? buildWiringServices(wiringRole) : []),
        [open, wiringRole],
    );

    const step: 'list' | 'trigger-ops' | 'node-config' = configNode
        ? 'node-config'
        : opsService
          ? 'trigger-ops'
          : 'list';

    // Visible rows for the two navigable steps. Token-based fuzzy match (shared
    // with the operation picker) so multi-word / reordered queries work — e.g.
    // "pull opened" surfaces "On Pull Request Opened".
    const rows = useMemo(() => {
        if (step === 'trigger-ops' && opsService) {
            return fuzzyFilter(opsService.triggerOps, search, op => [
                { text: op.displayName.toLowerCase(), weight: 1, fuzzy: true },
                { text: op.operation.replace(/[_-]+/g, ' ').toLowerCase(), weight: 0.6, fuzzy: true },
                { text: op.keywords.toLowerCase(), weight: 0.6, fuzzy: true },
                { text: op.description.toLowerCase(), weight: 0.4 },
            ]);
        }
        // Services match on identity first, then on the actions they expose in
        // this role, so "issue" finds Linear and "schedule" finds Schedule.
        if (step === 'list') return filterNodeServices(services, search, wiringRole);
        return [];
    }, [step, opsService, services, search, wiringRole]);

    // After creating the node, continue into the in-palette config step:
    // tools get credentials + allowlist; triggers get credentials + their
    // operation's config fields (webhook URL, form picker, schedule, …).
    const continueToConfig = (newId: string | void, nodeType: string, role: 'trigger' | 'tool') => {
        if (typeof newId !== 'string' || !getWiredNodeData) {
            onClose();
            return;
        }
        setConfigNode({ nodeId: newId as string, nodeType, role });
        setOpsService(null);
        setSearch('');
    };

    const commitIndex = (index: number) => {
        const row = rows[index];
        if (!row) return;
        if (step === 'trigger-ops') {
            const newId = onPick(opsService!.nodeType, (row as TriggerOperation).operation);
            continueToConfig(newId, opsService!.nodeType, 'trigger');
            return;
        }
        const service = row as ServiceEntry;
        if (wiringRole === 'trigger') {
            if (service.triggerOps.length > 1) {
                setOpsService(service);
                setSearch('');
                return;
            }
            const newId = onPick(service.nodeType, service.triggerOps[0]?.operation);
            continueToConfig(newId, service.nodeType, 'trigger');
            return;
        }
        const newId = onPick(service.nodeType);
        continueToConfig(newId, service.nodeType, 'tool');
    };

    const { highlightedIndex, setHighlightedIndex, resetNavigation, handleKeyDown } =
        usePickerKeyboardNav({
            itemCount: rows.length,
            containerRef: listRef,
            resolveNext: (direction, current) =>
                direction === 'down'
                    ? Math.min(current + 1, rows.length - 1)
                    : direction === 'up'
                      ? Math.max(current - 1, 0)
                      : null,
            onCommit: commitIndex,
        });

    const goBack = () => {
        setOpsService(null);
        setSearch('');
        setHighlightedIndex(0);
    };

    // Reset on every open; honor the open-directly-in-config-mode prop.
    useEffect(() => {
        if (open) {
            setSearch('');
            setOpsService(null);
            setConfigNode(configNodeProp ?? null);
            setHighlightedIndex(0);
            resetNavigation();
            // Focus after the portal commits (autoFocus is lint-blocked).
            requestAnimationFrame(() => searchRef.current?.focus());
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [open, configNodeProp]);

    // Escape closes (or steps back) from ANYWHERE in the palette. Focus often
    // leaves the search input — checkbox toggles, credential pickers, and the
    // config step has no input at all — so a document-level CAPTURE listener
    // owns the key while the palette is open. It also shields the canvas's
    // own Escape behaviors (node deselect) underneath the modal.
    useEffect(() => {
        if (!open) return;
        const onKey = (e: KeyboardEvent) => {
            if (e.key !== 'Escape') return;
            // Dialogs stacked above the palette (credential delete/share/request)
            // own Escape — closing the palette here would unmount them mid-flow.
            if (document.querySelector('[role="dialog"][data-state="open"], [role="alertdialog"][data-state="open"]')) return;
            e.preventDefault();
            e.stopPropagation();
            e.stopImmediatePropagation();
            if (opsService) goBack();
            else onClose();
        };
        document.addEventListener('keydown', onKey, true);
        return () => document.removeEventListener('keydown', onKey, true);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [open, opsService, onClose]);

    if (!open || typeof document === 'undefined') return null;

    const headerIcon =
        wiringRole === 'trigger' ? (
            <Zap className="h-4 w-4 shrink-0 text-amber-600 dark:text-amber-400" fill="currentColor" />
        ) : (
            <Wrench className="h-4 w-4 shrink-0 text-muted-foreground" />
        );

    // Live view of the node under configuration — re-read every render so
    // credential changes (incl. async OAuth/auto-select) show immediately.
    const live = configNode && getWiredNodeData ? getWiredNodeData(configNode.nodeId) : null;
    const liveOps = Array.isArray(live?.config?.agent_tool_operations)
        ? (live!.config.agent_tool_operations as string[])
        : [];
    const liveMounts = Array.isArray(live?.config?.agent_sandbox_repos)
        ? (live!.config.agent_sandbox_repos as { repo?: string; branch?: string }[]).map(m => ({
              repo: typeof m?.repo === 'string' ? m.repo : '',
              branch: typeof m?.branch === 'string' ? m.branch : '',
          }))
        : [];
    const liveCredIds = live?.credentialIds ?? {};
    const takesCredentials = configNode ? !!getNodeCredentialInfo(configNode.nodeType) : false;

    return createPortal(
        // eslint-disable-next-line jsx-a11y/no-static-element-interactions
        <div
            className="fixed inset-0 z-[65] bg-black/40"
            onMouseDown={e => {
                if (e.target === e.currentTarget) onClose();
            }}
        >
            {/* role=dialog also tells FlowCanvas's canvas-level Escape handler
                to leave the key to us while the palette is open.
                z-[65]/[66] sits above the ChatDrawer (z-[61]) but BELOW shared
                dialogs (z-[70], dialog.tsx) so popups launched from the config
                step (credential delete/share/request) stack on top. */}
            <div
                role="dialog"
                aria-modal="true"
                aria-label={wiringRole === 'trigger' ? 'Add trigger' : 'Add tool'}
                className="fixed left-1/2 top-[12vh] z-[66] w-[92vw] max-w-xl -translate-x-1/2 overflow-hidden rounded-xl border border-border dark:border-white/10 bg-background dark:bg-[#0a0a0b] shadow-2xl dark:shadow-black/60"
            >
                {step === 'node-config' && configNode ? (
                    <>
                        <div className="flex items-center gap-2.5 border-b border-border dark:border-white/[0.06] px-4 py-3">
                            {(() => {
                                const meta = getNodeMetadata(configNode.nodeType);
                                return meta?.Icon ? (
                                    <BrandIcon Icon={meta.Icon} iconColor={meta.iconColor} className="h-4 w-4 shrink-0" />
                                ) : (
                                    headerIcon
                                );
                            })()}
                            <span className="flex-1 text-sm text-foreground">
                                {getNodeDisplayName(configNode.nodeType)}
                                <span className="ml-2 text-xs text-muted-foreground dark:text-zinc-500">
                                    {configNode.role === 'tool'
                                        ? 'credentials + the actions the agent may call'
                                        : 'configure the trigger'}
                                </span>
                            </span>
                            <button
                                type="button"
                                onClick={onClose}
                                className="shrink-0 rounded-md bg-foreground/[0.06] px-2.5 py-1 text-xs font-medium text-foreground transition-colors hover:bg-foreground/[0.1]"
                            >
                                Done
                            </button>
                        </div>
                        <div className="max-h-[60vh] space-y-4 overflow-y-auto scrollbar-subtle px-4 py-3">
                            {/* mcp-server's auth form references "the server URL
                                above" — its Configuration must render first. */}
                            {configNode.nodeType !== 'mcp-server' && takesCredentials && onWiredNodeCredentialsChange && (
                                <section>
                                    <div className="mb-2 text-[11px] uppercase tracking-wider text-muted-foreground dark:text-zinc-500">
                                        Credentials
                                    </div>
                                    <NodeCredentials
                                        nodeType={configNode.nodeType}
                                        nodeData={live?.nodeData ?? {}}
                                        credentialIds={liveCredIds}
                                        onChange={ids => onWiredNodeCredentialsChange(configNode.nodeId, ids)}
                                        compact
                                    />
                                </section>
                            )}
                            {(configNode.role === 'trigger' || STRUCTURAL_AGENT_TOOL_TYPES.has(configNode.nodeType)) && (
                                <section>
                                    <div className="mb-2 text-[11px] uppercase tracking-wider text-muted-foreground dark:text-zinc-500">
                                        Configuration
                                    </div>
                                    {/* Per-type explainer for the structural tool providers —
                                        their tool surfaces are fixed (not an allowlist), so a
                                        short note replaces the action picker we'd otherwise
                                        render below. */}
                                    {configNode.nodeType === 'mcp-server' && (
                                        <p className="mb-2 text-xs leading-relaxed text-muted-foreground">
                                            Set a server URL to give the agent an external MCP
                                            server&apos;s tools — or leave it empty and wire tool
                                            nodes into this node&apos;s bottom handle on the canvas
                                            to host your own.
                                        </p>
                                    )}
                                    {configNode.nodeType === 'alarm' && (
                                        <p className="mb-2 text-xs leading-relaxed text-zinc-400">
                                            Lets the agent wake itself up later. Adds four tools:
                                            <code className="mx-1 rounded bg-foreground/[0.06] px-1 py-px text-[11px]">schedule_alarm</code>,
                                            <code className="mx-1 rounded bg-foreground/[0.06] px-1 py-px text-[11px]">list_alarms</code>,
                                            <code className="mx-1 rounded bg-foreground/[0.06] px-1 py-px text-[11px]">cancel_alarm</code>, and
                                            <code className="mx-1 rounded bg-foreground/[0.06] px-1 py-px text-[11px]">update_alarm</code>.
                                        </p>
                                    )}
                                    {configNode.nodeType === 'filesystem' && (
                                        <p className="mb-2 text-xs leading-relaxed text-zinc-400">
                                            Mounts a persistent sandbox volume for the agent&apos;s
                                            bash environment and adds an
                                            <code className="mx-1 rounded bg-foreground/[0.06] px-1 py-px text-[11px]">upload_file</code>
                                            tool so the agent can publish files to a public URL.
                                        </p>
                                    )}
                                    {configNode.nodeType === 'tool' && (
                                        <p className="mb-2 text-xs leading-relaxed text-zinc-400">
                                            Exposes a custom tool whose call runs this node&apos;s
                                            downstream subgraph on the canvas. The agent calls it
                                            with the parameters you define below.
                                        </p>
                                    )}
                                    {/* The canonical schema-driven form — same renderer as the
                                        canvas panel, with the operation locked (for triggers) so
                                        the popup can't switch it. */}
                                    <NodeConfig
                                        key={configNode.nodeId}
                                        nodeType={configNode.nodeType}
                                        config={(live?.config ?? {}) as Record<string, unknown>}
                                        onChange={(cfg, sourceNodeId) => {
                                            if (sourceNodeId && sourceNodeId !== configNode.nodeId) return;
                                            onWiredNodeConfigPatch?.(configNode.nodeId, cfg);
                                        }}
                                        operation={
                                            ((live?.nodeData?.operation ?? live?.config?.operation) as string | undefined) ?? undefined
                                        }
                                        credentialIds={liveCredIds}
                                        nodeId={configNode.nodeId}
                                        workflowId={workflowId}
                                        hideOperationPicker
                                    />
                                </section>
                            )}
                            {configNode.nodeType === 'mcp-server' && takesCredentials && onWiredNodeCredentialsChange && (
                                <section>
                                    <div className="mb-2 text-[11px] uppercase tracking-wider text-muted-foreground dark:text-zinc-500">
                                        Credentials
                                    </div>
                                    <NodeCredentials
                                        nodeType={configNode.nodeType}
                                        nodeData={live?.nodeData ?? {}}
                                        credentialIds={liveCredIds}
                                        onChange={ids => onWiredNodeCredentialsChange(configNode.nodeId, ids)}
                                        compact
                                    />
                                </section>
                            )}
                            {/* Operation allowlist is for the ~58 integration-op providers only —
                                the structural types (tool / mcp-server / alarm / filesystem) emit
                                their tool surfaces from their own NodeConfig above. */}
                            {configNode.role === 'tool' && !STRUCTURAL_AGENT_TOOL_TYPES.has(configNode.nodeType) && (
                                <AgentToolOperationsPicker
                                    nodeType={configNode.nodeType}
                                    selectedOperations={liveOps}
                                    onChange={ops =>
                                        onWiredNodeConfigPatch?.(configNode.nodeId, { agent_tool_operations: ops })
                                    }
                                    credentialsMissing={providerCredentialsMissing(
                                        configNode.nodeType,
                                        liveCredIds,
                                        live?.nodeData,
                                    )}
                                    hideIntro
                                    sandboxMounts={SANDBOX_MOUNT_TYPES[configNode.nodeType] ? liveMounts : undefined}
                                    onSandboxMountsChange={
                                        SANDBOX_MOUNT_TYPES[configNode.nodeType] && onWiredNodeConfigPatch
                                            ? mounts =>
                                                  onWiredNodeConfigPatch(configNode.nodeId, {
                                                      agent_sandbox_repos: mounts,
                                                  })
                                            : undefined
                                    }
                                    mountCredentialId={
                                        Object.entries(liveCredIds).find(
                                            ([k, v]) => k !== 'credential_type' && v,
                                        )?.[1]
                                    }
                                />
                            )}
                        </div>
                    </>
                ) : (
                    <>
                        <div className="flex items-center gap-2.5 border-b border-border dark:border-white/[0.06] px-4 py-1">
                            {step === 'trigger-ops' ? (
                                <button
                                    type="button"
                                    onClick={goBack}
                                    title="Back to services"
                                    className="shrink-0 rounded p-1 text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground"
                                >
                                    <ArrowLeft className="h-4 w-4" />
                                </button>
                            ) : (
                                <Search className="h-4 w-4 shrink-0 text-muted-foreground dark:text-zinc-500" />
                            )}
                            {step === 'trigger-ops' && opsService && (
                                <span className="flex shrink-0 items-center gap-1.5 rounded-md bg-foreground/[0.06] px-2 py-1 text-xs text-foreground/80">
                                    {(() => {
                                        const meta = getNodeMetadata(opsService.nodeType);
                                        return meta?.Icon ? (
                                            <BrandIcon Icon={meta.Icon} iconColor={meta.iconColor} className="h-3.5 w-3.5" />
                                        ) : null;
                                    })()}
                                    {opsService.label}
                                </span>
                            )}
                            <input
                                ref={searchRef}
                                type="text"
                                value={search}
                                onChange={e => setSearch(e.target.value)}
                                onKeyDown={e => {
                                    // Escape is owned by the document-capture
                                    // listener above (works without focus too).
                                    if (e.key === 'Backspace' && search === '' && step === 'trigger-ops') {
                                        goBack();
                                        return;
                                    }
                                    handleKeyDown(e);
                                }}
                                placeholder={
                                    step === 'trigger-ops'
                                        ? 'Pick the trigger…'
                                        : wiringRole === 'trigger'
                                          ? 'Search triggers — the agent runs when one fires…'
                                          : 'Search services to give the agent tools…'
                                }
                                className="h-12 w-full bg-transparent text-sm text-foreground placeholder:text-[hsl(var(--placeholder))] focus:outline-none"
                            />
                        </div>
                        <div ref={listRef} className="max-h-[38vh] overflow-y-auto scrollbar-subtle p-1.5">
                            {rows.length === 0 && (
                                <div className="px-3 py-8 text-center text-sm text-muted-foreground dark:text-zinc-500">No matches.</div>
                            )}
                            {step === 'list' &&
                                (rows as ServiceEntry[]).map((s, idx) => {
                                    const meta = getNodeMetadata(s.nodeType);
                                    return (
                                        <PaletteRow
                                            key={s.nodeType}
                                            index={idx}
                                            active={idx === highlightedIndex}
                                            onHover={() => setHighlightedIndex(idx)}
                                            onSelect={() => commitIndex(idx)}
                                            icon={
                                                meta?.Icon ? (
                                                    <BrandIcon Icon={meta.Icon} iconColor={meta.iconColor} className="h-[18px] w-[18px] shrink-0" />
                                                ) : (
                                                    <span className="h-[18px] w-[18px] shrink-0" />
                                                )
                                            }
                                            label={s.label}
                                            badge={
                                                wiringRole === 'trigger' && s.triggerOps.length > 1
                                                    ? `${s.triggerOps.length} triggers`
                                                    : undefined
                                            }
                                        />
                                    );
                                })}
                            {step === 'trigger-ops' &&
                                (rows as TriggerOperation[]).map((op, idx) => (
                                    <PaletteRow
                                        key={op.operation}
                                        index={idx}
                                        active={idx === highlightedIndex}
                                        onHover={() => setHighlightedIndex(idx)}
                                        onSelect={() => commitIndex(idx)}
                                        icon={<Zap className="h-[18px] w-[18px] shrink-0 p-0.5 text-amber-600 dark:text-amber-400" fill="currentColor" />}
                                        label={op.displayName}
                                        detail={op.description}
                                    />
                                ))}
                        </div>
                        <div className="flex items-center gap-4 border-t border-border dark:border-white/[0.06] px-4 py-2.5 text-[11px] text-muted-foreground dark:text-zinc-500">
                            <span className="flex items-center gap-1.5">
                                <kbd className="rounded border border-border dark:border-white/10 px-1 py-px text-[10px]">↑↓</kbd> navigate
                            </span>
                            <span className="flex items-center gap-1.5">
                                <kbd className="rounded border border-border dark:border-white/10 px-1 py-px text-[10px]">↵</kbd> select
                            </span>
                            <span className="flex items-center gap-1.5">
                                <kbd className="rounded border border-border dark:border-white/10 px-1 py-px text-[10px]">esc</kbd>{' '}
                                {step === 'trigger-ops' ? 'back' : 'close'}
                            </span>
                        </div>
                    </>
                )}
            </div>
        </div>,
        document.body,
    );
}
