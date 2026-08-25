// AgentToolOperationsPicker renders the operation allowlist for an integration
// node wired to an AI agent's bottom handle as a tool provider. Selected
// operations are stored at config.agent_tool_operations and become callable
// node_op tools for the agent (backend: nodes/agent/node_op_tools.py).
// Visual + keyboard language mirrors OperationPicker (search-first, sectioned
// rows with the node glyph, ↑↓ navigate / ↵ toggle).
//
// Resource scoping: ops with scopable fields (x-dynamic-options +
// x-resource-type) expose an inline accordion under the row to pin specific
// resource IDs — the persisted entry switches from a bare string to
// {operation, field_scopes} so backend enforcement in
// tool_execution._enforce_field_scopes gates calls to those resources.

import { useEffect, useMemo, useRef, useState } from 'react';
import { AlertCircle, ArrowUpRight, Check, ChevronDown, GitBranch, Info, Loader2, Lock, Search, SlidersHorizontal, Wrench, X } from 'lucide-react';
import { Checkbox } from '~/components/ui/checkbox';
import { BrandIcon } from '~/components/shared/BrandIcon';
import { usePickerKeyboardNav } from '~/hooks/usePickerKeyboardNav';
import { scoreFields } from '~/utils/fuzzySearch';
import {
    getAgentToolOperations,
    operationName,
    type AgentToolOperation,
    type AgentToolOperationEntry,
    type AgentToolScopableField,
} from '~/utils/nodeSchemas';
import { getNodeMetadata } from './nodes/nodeRegistry';
import { sendEventAsync } from '~/lib/socket-sender';
import { WorkflowNodeLoadOptionsRequest } from '~/types/socket-events.generated';
import type { WorkflowNodeLoadOptionsResponse } from '~/types/socket-events.generated';

interface AgentToolOperationsPickerProps {
    nodeType: string;
    /** Currently allowlisted operations (config.agent_tool_operations). Mixed
     *  shape: bare strings for unscoped ops, {operation, field_scopes} for
     *  resource-pinned ops. Existing callers passing legacy string[] still
     *  work — the picker treats every entry uniformly. */
    selectedOperations: AgentToolOperationEntry[] | string[];
    onChange: (operations: AgentToolOperationEntry[]) => void;
    /** Node requires credentials that aren't connected — tool calls will fail. */
    credentialsMissing?: boolean;
    /** Jump to the credentials tab. */
    onConnectCredentials?: () => void;
    /** Sandbox repo mounts (config.agent_sandbox_repos). */
    sandboxMounts?: { repo: string; branch: string }[];
    onSandboxMountsChange?: (mounts: { repo: string; branch: string }[]) => void;
    /** Credential id used to load repo options for the mount picker. AND to
     *  load resource options for the per-op scope panel below (same field
     *  loader path; backend resolves via the credential bound on the provider
     *  node). */
    mountCredentialId?: string;
    /** Skip the what-is-this intro banner (hosts that provide their own
     *  context, e.g. the AgentWiringPalette config step). */
    hideIntro?: boolean;
    /** Consumer kinds this provider feeds (agent / mcp-server) — drives the
     *  intro banner copy. Defaults to agent phrasing. */
    consumerTypes?: Array<'agent' | 'mcp-server'>;
}

// Provider types whose credentials can materialize environment in the agent's
// bash sandbox at boot (backend: WorkflowNode.get_sandbox_setup overrides).
// field: the node's load_field_options field that lists mountable repos.
// Exported so palette/panel hosts know when to wire the mount props.
export const SANDBOX_MOUNT_TYPES: Record<string, { field: string }> = {
    'automation-github-rest': { field: 'repository' },
};

// Operation-name prefixes treated as non-mutating for the "Read-only" quick
// select. Heuristic over generated op names — covers list/get/search/etc.
const READ_PREFIXES = new Set(['list', 'get', 'search', 'fetch', 'read', 'query', 'count', 'check']);

const isReadOperation = (op: string) => READ_PREFIXES.has(op.split('_')[0]);

export function AgentToolOperationsPicker({
    nodeType,
    selectedOperations,
    onChange,
    credentialsMissing = false,
    onConnectCredentials,
    sandboxMounts,
    onSandboxMountsChange,
    mountCredentialId,
    hideIntro = false,
    consumerTypes,
}: AgentToolOperationsPickerProps) {
    const [search, setSearch] = useState('');
    const [showSelectedOnly, setShowSelectedOnly] = useState(false);
    const listRef = useRef<HTMLDivElement>(null);

    const operations = useMemo(() => getAgentToolOperations(nodeType), [nodeType]);

    // Normalize mixed (string | {operation, field_scopes}) entries into a
    // map keyed by operation name; values carry per-field scope arrays for
    // scoped ops and an empty object for unscoped ones. All downstream UI
    // works off this map.
    const entriesByOp = useMemo(() => {
        const out = new Map<string, Record<string, string[]>>();
        for (const e of selectedOperations as AgentToolOperationEntry[]) {
            if (typeof e === 'string') out.set(e, {});
            else if (e?.operation) out.set(e.operation, e.field_scopes ?? {});
        }
        return out;
    }, [selectedOperations]);

    const selected = useMemo(() => new Set(entriesByOp.keys()), [entriesByOp]);
    const meta = getNodeMetadata(nodeType);
    const readOps = useMemo(
        () => operations.filter(op => isReadOperation(op.operation)).map(op => op.operation),
        [operations],
    );
    const selectionHasDynamicFields = useMemo(
        () => operations.some(op => selected.has(op.operation) && op.hasDynamicFields),
        [operations, selected],
    );

    // Ops the user has expanded to edit scope on, transient UI state only
    // (closing the panel doesn't change the allowlist). The accordion starts
    // collapsed — its header is the affordance.
    const [expandedScopes, setExpandedScopes] = useState<Set<string>>(new Set());
    // Remembers an op's field_scopes across uncheck/recheck cycles so the
    // user doesn't lose pinned resources by accidentally toggling the op off
    // and back on. Stashed on uncheck, restored on recheck, dropped on
    // explicit chip removal (since the user is deliberately clearing).
    const scopesMemoryRef = useRef<Map<string, Record<string, string[]>>>(new Map());
    const toggleScopeExpanded = (operation: string) =>
        setExpandedScopes(prev => {
            const next = new Set(prev);
            if (next.has(operation)) next.delete(operation);
            else next.add(operation);
            return next;
        });

    // Relevance score per operation for the current query (null while empty, so
    // the list stays in schema order for browsing). Fuzzy-matches the display
    // name + raw operation value, plus category/description for recall — so
    // "msg send" or "snd" still find "Send Message".
    const scored = useMemo(() => {
        const q = search.trim();
        if (!q) return null;
        const scores = new Map<string, number>();
        for (const op of operations) {
            const fields = [
                { text: op.displayName.toLowerCase(), weight: 1, fuzzy: true },
                { text: op.operation.replace(/[_-]+/g, ' ').toLowerCase(), weight: 0.6, fuzzy: true },
            ];
            if (op.keywords) fields.push({ text: op.keywords.toLowerCase(), weight: 0.6, fuzzy: true });
            if (op.category) fields.push({ text: op.category.toLowerCase(), weight: 0.4, fuzzy: false });
            if (op.description) fields.push({ text: op.description.toLowerCase(), weight: 0.25, fuzzy: false });
            const score = scoreFields(fields, q);
            if (score !== null) scores.set(op.operation, score);
        }
        return scores;
    }, [operations, search]);

    // View filter: narrow the visible list to just the allowlisted operations
    // so a handful of selections among 200+ are visible at a glance. Gated on a
    // non-empty selection so Clear never strands the user on an empty list.
    const selectedOnly = showSelectedOnly && selected.size > 0;

    const filtered = useMemo(() => {
        const matched = scored ? operations.filter(op => scored.has(op.operation)) : operations;
        return selectedOnly ? matched.filter(op => selected.has(op.operation)) : matched;
    }, [operations, scored, selectedOnly, selected]);

    // Group by category (uncategorized last). No query → schema order; with a
    // query → ops sorted best-first within each group and groups floated up by
    // their strongest match, so the top of the list is the best result.
    const grouped = useMemo(() => {
        const groups = new Map<string, AgentToolOperation[]>();
        for (const op of filtered) {
            const key = op.category ?? 'Other';
            const list = groups.get(key) ?? [];
            list.push(op);
            groups.set(key, list);
        }
        const entries = [...groups.entries()];
        if (!scored) return entries;
        const best = (ops: AgentToolOperation[]) =>
            ops.reduce((max, op) => Math.max(max, scored.get(op.operation) ?? 0), 0);
        for (const [, ops] of entries) {
            ops.sort(
                (a, b) =>
                    (scored.get(b.operation) ?? 0) - (scored.get(a.operation) ?? 0) ||
                    a.displayName.localeCompare(b.displayName),
            );
        }
        entries.sort((a, b) => best(b[1]) - best(a[1]));
        return entries;
    }, [filtered, scored]);

    /** Flat reading order across sections — canonical for keyboard nav. */
    const flatOps = useMemo(() => grouped.flatMap(([, ops]) => ops), [grouped]);

    // Persist in schema order so the tool list is stable across edits. An op
    // with a non-empty field_scopes serializes as the scoped object form;
    // otherwise as the bare string (matches validate_agent_tool_operations).
    const persistEntries = (nextEntries: Map<string, Record<string, string[]>>) => {
        const out: AgentToolOperationEntry[] = [];
        for (const op of operations) {
            if (!nextEntries.has(op.operation)) continue;
            const scopes = nextEntries.get(op.operation) ?? {};
            // Drop empty scope arrays — they mean "constrain to nothing" which
            // would block the agent from using the op at all (counterintuitive
            // UX). Empty across-the-board collapses back to the unscoped form.
            const trimmed: Record<string, string[]> = {};
            for (const [field, ids] of Object.entries(scopes)) {
                if (Array.isArray(ids) && ids.length > 0) trimmed[field] = ids;
            }
            if (Object.keys(trimmed).length > 0) {
                out.push({ operation: op.operation, field_scopes: trimmed });
            } else {
                out.push(op.operation);
            }
        }
        onChange(out);
    };

    // Sugar for callsites that only flip the selected set (no scope edits).
    // Preserves whatever scopes are CURRENTLY active for each op kept in the
    // set — quick-selects (Read-only / All / Clear) don't wipe pins on ops
    // that survive the operation.
    const persistSet = (next: Set<string>) => {
        const m = new Map<string, Record<string, string[]>>();
        for (const op of next) {
            // Restore from memory if this op is being re-added (was previously
            // unchecked); else use the current scopes if it's already selected.
            const fromMemory = !selected.has(op) ? scopesMemoryRef.current.get(op) : undefined;
            m.set(op, fromMemory ?? entriesByOp.get(op) ?? {});
        }
        persistEntries(m);
    };

    const toggle = (operation: string) => {
        const next = new Set(selected);
        if (next.has(operation)) {
            // Unchecking: snapshot current scopes into memory so a later
            // recheck restores them. Empty scopes don't need saving.
            const current = entriesByOp.get(operation) ?? {};
            if (Object.keys(current).length > 0) {
                scopesMemoryRef.current.set(operation, current);
            }
            next.delete(operation);
        } else {
            next.add(operation);
        }
        persistSet(next);
    };

    const setOperationScope = (
        operation: string,
        field: string,
        nextIds: string[],
    ) => {
        const m = new Map(entriesByOp);
        const current = { ...(m.get(operation) ?? {}) };
        if (nextIds.length === 0) {
            delete current[field];
        } else {
            current[field] = nextIds;
        }
        m.set(operation, current);
        persistEntries(m);
    };

    // Shared picker scaffolding (highlight, gated scrollIntoView, triple-stop
    // key capture); linear up/down strategy for this single-column list.
    const { highlightedIndex: highlighted, setHighlightedIndex: setHighlighted, handleKeyDown } =
        usePickerKeyboardNav({
            itemCount: flatOps.length,
            containerRef: listRef,
            resolveNext: (direction, current) =>
                direction === 'down'
                    ? Math.min(current + 1, flatOps.length - 1)
                    : direction === 'up'
                      ? Math.max(current - 1, 0)
                      : null,
            onCommit: (index) => {
                if (flatOps[index]) toggle(flatOps[index].operation);
            },
        });

    // While typing, keep the highlight on the top-ranked result so ↵ toggles
    // the best match.
    useEffect(() => {
        if (search.trim()) setHighlighted(0);
    }, [search, setHighlighted]);

    if (operations.length === 0) {
        return (
            <div className="text-sm text-muted-foreground dark:text-zinc-500 py-4 text-center">
                This node has no actions that can be exposed to an agent.
            </div>
        );
    }

    return (
        <div className="space-y-3">
            {!hideIntro && (
                <div className="flex items-start gap-2 px-3 py-2.5 rounded-lg bg-foreground/[0.04] border border-border dark:border-white/[0.06]">
                    <Wrench className="w-4 h-4 text-muted-foreground mt-0.5 flex-shrink-0" />
                    <div className="text-xs text-muted-foreground leading-relaxed">
                        {consumerTypes?.includes('mcp-server') && !consumerTypes.includes('agent')
                            ? <>This node is connected to an MCP server as a tool provider. Pick the actions the server exposes — each becomes a tool that connected agents and external MCP clients can call with its own arguments, using this node&apos;s credentials.</>
                            : consumerTypes?.includes('mcp-server')
                              ? <>This node provides tools to an AI agent and an MCP server. Pick the allowed actions — each becomes a tool callable with its own arguments, using this node&apos;s credentials.</>
                              : <>This node is connected to an AI agent as a tool. Pick the actions the agent is allowed to run — each becomes a tool the agent can call with its own arguments, using this node&apos;s credentials.</>}
                    </div>
                </div>
            )}

            {/* Same anatomy as NodeConfig's incomplete-fields banner, with the
                connect link promoted to its own line. */}
            {credentialsMissing && (
                <div className="px-3 py-2.5 rounded-lg bg-amber-100 dark:bg-amber-500/15 border border-amber-300 dark:border-amber-400/40">
                    <div className="space-y-1">
                        <div className="flex items-center gap-2">
                            <div className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full bg-amber-400/25 ring-1 ring-amber-500/30 dark:bg-amber-400/15 dark:ring-amber-300/30">
                                <AlertCircle className="h-3.5 w-3.5 text-amber-600 dark:text-amber-300" />
                            </div>
                            <div className="text-sm font-semibold leading-5 text-amber-900 dark:text-amber-100">
                                No credentials connected
                            </div>
                        </div>
                        <p className="pl-8 text-xs leading-4 text-amber-900/90 dark:text-amber-100/90">
                            The agent&apos;s tool calls will fail until you connect one.
                        </p>
                        {onConnectCredentials && (
                            <button
                                type="button"
                                onClick={onConnectCredentials}
                                className="ml-8 inline-flex items-center gap-1 text-sm font-semibold text-amber-700 dark:text-amber-50 hover:text-amber-800 dark:hover:text-foreground underline underline-offset-2 transition-colors"
                            >
                                Connect credentials
                                <ArrowUpRight className="h-3.5 w-3.5" />
                            </button>
                        )}
                    </div>
                </div>
            )}

            {SANDBOX_MOUNT_TYPES[nodeType] && onSandboxMountsChange && (
                <SandboxMountSection
                    nodeType={nodeType}
                    optionsField={SANDBOX_MOUNT_TYPES[nodeType].field}
                    mounts={sandboxMounts ?? []}
                    onChange={onSandboxMountsChange}
                    credentialId={mountCredentialId}
                />
            )}

            {/* Search — same prominent affordance as OperationPicker */}
            <div className="flex items-center gap-2.5 px-2 py-1">
                <Search className="h-5 w-5 text-muted-foreground flex-shrink-0" />
                <input
                    type="text"
                    value={search}
                    onChange={e => setSearch(e.target.value)}
                    onKeyDown={handleKeyDown}
                    placeholder="Search actions to allow the agent to run…"
                    className="flex-1 bg-transparent text-base text-foreground placeholder:text-[hsl(var(--placeholder))] focus:outline-none py-1"
                />
                <span className="text-[11px] text-muted-foreground dark:text-zinc-500 whitespace-nowrap flex-shrink-0">
                    {selected.size} selected
                </span>
            </div>

            {/* Keyboard hints + quick selects */}
            <div className="px-1 pb-2 border-b border-border dark:border-white/[0.06] flex items-center justify-between gap-3 flex-wrap">
                <div className="text-[10px] text-muted-foreground dark:text-zinc-500 flex items-center gap-3">
                    <span>
                        <kbd className="px-1 py-0.5 bg-foreground/[0.06] rounded">↑↓</kbd> navigate
                    </span>
                    <span>
                        <kbd className="px-1 py-0.5 bg-foreground/[0.06] rounded">↵</kbd> toggle
                    </span>
                </div>
                <div className="flex items-center justify-start gap-1.5 flex-wrap">
                    {selected.size > 0 && (
                        <button
                            type="button"
                            onClick={() => setShowSelectedOnly(v => !v)}
                            aria-pressed={selectedOnly}
                            title={selectedOnly ? 'Show all actions' : 'Show only selected actions'}
                            className={`inline-flex items-center gap-1 whitespace-nowrap text-[11px] font-medium px-2 py-0.5 rounded-md border transition-colors ${
                                selectedOnly
                                    ? 'text-foreground bg-foreground/[0.12] border-foreground/[0.2]'
                                    : 'text-muted-foreground hover:text-foreground border-foreground/[0.08] hover:bg-foreground/[0.06]'
                            }`}
                        >
                            {selectedOnly && <Check className="h-3 w-3" />}
                            Show selected
                            <span className={selectedOnly ? 'text-muted-foreground dark:text-zinc-300' : 'text-muted-foreground/70 dark:text-zinc-500'}>
                                ({selected.size})
                            </span>
                        </button>
                    )}
                    <span className="text-[10px] text-muted-foreground/70 dark:text-zinc-600 uppercase tracking-wider mr-0.5">Select</span>
                    {readOps.length > 0 && (
                        <QuickSelectButton
                            label="Read-only"
                            title="List/get/search actions — no mutations"
                            onClick={() => persistSet(new Set(readOps))}
                        />
                    )}
                    <QuickSelectButton
                        label="All"
                        title={`All ${operations.length} actions — including destructive ones`}
                        onClick={() => persistSet(new Set(operations.map(op => op.operation)))}
                    />
                    <QuickSelectButton label="Clear" onClick={() => persistSet(new Set())} />
                </div>
            </div>

            <div ref={listRef} className="space-y-3 max-h-[420px] overflow-y-auto scrollbar-subtle pr-1">
                {grouped.map(([category, ops]) => (
                    <section key={category}>
                        {grouped.length > 1 && (
                            <div className="px-1 mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-1.5 sticky top-0 bg-card/95 py-0.5 z-10">
                                <span>{category}</span>
                                <span className="text-muted-foreground dark:text-zinc-500 font-normal normal-case tracking-normal">
                                    {ops.length}
                                </span>
                            </div>
                        )}
                        <div className="flex flex-col gap-px">
                            {ops.map(op => {
                                const flatPos = flatOps.indexOf(op);
                                const isHighlighted = flatPos === highlighted;
                                const isChecked = selected.has(op.operation);
                                const opScopes = entriesByOp.get(op.operation) ?? {};
                                const scopableCount = op.scopableFields.length;
                                const scopedFieldCount = Object.keys(opScopes).filter(
                                    f => (opScopes[f]?.length ?? 0) > 0,
                                ).length;
                                const expanded = expandedScopes.has(op.operation);
                                const showScopeRow = isChecked && scopableCount > 0;
                                return (
                                    <div key={op.operation} className="flex flex-col">
                                        <button
                                            type="button"
                                            data-flat-index={flatPos}
                                            onClick={() => toggle(op.operation)}
                                            onMouseEnter={() => setHighlighted(flatPos)}
                                            onMouseDown={e => e.preventDefault()}
                                            className={`flex items-center gap-2.5 px-2 py-1.5 rounded text-left transition-colors ${
                                                isHighlighted
                                                    ? 'bg-foreground/[0.10]'
                                                    : isChecked
                                                      ? 'bg-foreground/[0.04]'
                                                      : 'hover:bg-foreground/[0.04]'
                                            }`}
                                        >
                                            <Checkbox
                                                checked={isChecked}
                                                tabIndex={-1}
                                                className="h-3.5 w-3.5 rounded border-muted-foreground/40 dark:border-white/25 data-[state=checked]:bg-primary data-[state=checked]:border-primary data-[state=checked]:text-primary-foreground pointer-events-none flex-shrink-0 [&_svg]:h-3 [&_svg]:w-3"
                                            />
                                            {meta?.Icon && (
                                                <BrandIcon
                                                    Icon={meta.Icon}
                                                    iconColor={meta.iconColor}
                                                    className="h-3.5 w-3.5 flex-shrink-0"
                                                />
                                            )}
                                            <span
                                                className={`text-[12px] leading-tight flex-shrink-0 ${
                                                    isChecked || isHighlighted ? 'text-foreground' : 'text-foreground/80'
                                                }`}
                                            >
                                                {op.displayName}
                                            </span>
                                            {op.description && (
                                                <span className="text-[11px] text-muted-foreground dark:text-zinc-500 leading-tight truncate min-w-0">
                                                    {op.description}
                                                </span>
                                            )}
                                            {showScopeRow && scopedFieldCount > 0 && (
                                                <span
                                                    className="ml-auto flex-shrink-0 inline-flex items-center gap-1 text-[10px] font-medium text-muted-foreground"
                                                    title="Limited to specific resources"
                                                >
                                                    <Lock className="w-2.5 h-2.5" />
                                                    Limited
                                                </span>
                                            )}
                                        </button>
                                        {showScopeRow && (
                                            <ScopeAccordion
                                                op={op}
                                                expanded={expanded}
                                                onToggleExpanded={() => toggleScopeExpanded(op.operation)}
                                                scopes={opScopes}
                                                onChangeScope={(field, ids) =>
                                                    setOperationScope(op.operation, field, ids)
                                                }
                                                nodeType={nodeType}
                                                credentialId={mountCredentialId}
                                            />
                                        )}
                                    </div>
                                );
                            })}
                        </div>
                    </section>
                ))}
                {filtered.length === 0 && (
                    <div className="px-2 py-8 text-center text-sm text-muted-foreground dark:text-zinc-500">
                        {search.trim()
                            ? <>No {selectedOnly ? 'selected ' : ''}actions match &quot;{search}&quot;</>
                            : 'No actions selected yet'}
                    </div>
                )}
            </div>

            {selectionHasDynamicFields && (
                <div className="flex items-start gap-2 px-3 py-2 rounded-lg bg-foreground/[0.03] border border-border dark:border-white/[0.05]">
                    <Info className="w-3.5 h-3.5 text-muted-foreground dark:text-zinc-500 mt-0.5 flex-shrink-0" />
                    <div className="text-[11px] text-muted-foreground dark:text-zinc-500 leading-relaxed">
                        Some selected actions take IDs (teams, spreadsheets, …). A lookup
                        tool is included automatically so the agent can discover valid
                        values on its own.
                    </div>
                </div>
            )}

        </div>
    );
}

// ScopeAccordion — collapsible affordance directly below a checked op row,
// indented to align with the op label (skipping the checkbox column).
// Resting state: a single subtle row that reads either "Limit to specific
// X" (call to action) or "Limited to N X" (current state) — clicks
// to expand the per-field picker. No extra wrapper card; the visual weight
// comes from indentation + a slight left rail, matching the rest of the
// picker's tight, no-chrome language.
function ScopeAccordion({
    op,
    expanded,
    onToggleExpanded,
    scopes,
    onChangeScope,
    nodeType,
    credentialId,
}: {
    op: AgentToolOperation;
    expanded: boolean;
    onToggleExpanded: () => void;
    scopes: Record<string, string[]>;
    onChangeScope: (field: string, ids: string[]) => void;
    nodeType: string;
    credentialId?: string;
}) {
    const totalPinned = Object.values(scopes).reduce((n, ids) => n + ids.length, 0);
    const fieldNoun = op.scopableFields.length === 1
        ? op.scopableFields[0].label.toLowerCase()
        : 'resources';
    return (
        <div>
            <button
                type="button"
                onClick={onToggleExpanded}
                onMouseDown={e => e.preventDefault()}
                className="group flex items-center gap-1.5 w-full text-left px-1.5 py-0.5 text-[11px] text-zinc-500 hover:text-foreground dark:hover:text-zinc-200 transition-colors rounded"
            >
                <ChevronDown
                    className={`w-3 h-3 flex-shrink-0 transition-transform ${
                        expanded ? '' : '-rotate-90'
                    }`}
                />
                <SlidersHorizontal className="w-3 h-3 flex-shrink-0 text-zinc-600 group-hover:text-foreground/70 dark:group-hover:text-zinc-400 transition-colors" />
                <span className="truncate">
                    {totalPinned > 0
                        ? <>Limited to <span className="text-foreground dark:text-zinc-200">{totalPinned}</span> {pluralize(fieldNoun, totalPinned)}</>
                        : <>Limit to specific {pluralize(fieldNoun, 2)}</>}
                </span>
            </button>
            {expanded && (
                <div className="pb-1 space-y-2">
                    {/* Parent fields rendered before dependents — the picker
                        gates a dependent on its parent's scope, so visually
                        ordering parent-first makes the dependency obvious. */}
                    {[...op.scopableFields]
                        .sort((a, b) => Number(!!a.dependsOn) - Number(!!b.dependsOn))
                        .map((field, idx) => {
                            const parent = field.dependsOn
                                ? op.scopableFields.find(f => f.field === field.dependsOn)
                                : undefined;
                            return (
                                <ResourceScopePicker
                                    key={field.field}
                                    nodeType={nodeType}
                                    field={field}
                                    // Hide the field title when this op has
                                    // just one scopable field — the accordion
                                    // header already names it.
                                    showFieldLabel={op.scopableFields.length > 1}
                                    isFirst={idx === 0}
                                    selectedIds={scopes[field.field] ?? []}
                                    onChange={ids => onChangeScope(field.field, ids)}
                                    credentialId={credentialId}
                                    parentScope={parent ? scopes[parent.field] ?? [] : undefined}
                                    parentLabel={parent?.label}
                                />
                            );
                        })}
                </div>
            )}
        </div>
    );
}

// ResourceScopePicker — chips-style autocomplete for pinning specific resource
// IDs to an op's field. Empty chip list = unscoped (persistEntries collapses
// an empty field_scopes back to a bare string). The user types to filter, the
// dropdown shows non-pinned options below the input, and clicking one adds a
// chip. Backspace from an empty input removes the last chip. Esc closes the
// dropdown.
//
// Multi-level resources: when the loader needs a parent (depends_on, e.g.
// sheet_name needs spreadsheet_id), this picker reads the parent field's
// scope from the same op and either gates the picker ("Pin {parent} first")
// or fans out the loader call across every pinned parent value and dedupes
// results.
function ResourceScopePicker({
    nodeType,
    field,
    showFieldLabel,
    isFirst,
    selectedIds,
    onChange,
    credentialId,
    parentScope,
    parentLabel,
}: {
    nodeType: string;
    field: AgentToolScopableField;
    showFieldLabel: boolean;
    isFirst: boolean;
    selectedIds: string[];
    onChange: (ids: string[]) => void;
    credentialId?: string;
    /** When field.dependsOn is set: the parent field's currently pinned IDs
     *  on this op. Undefined = field is independent. */
    parentScope?: string[];
    /** Human-readable parent field label for the disabled-state hint. */
    parentLabel?: string;
}) {
    const isDependent = !!field.dependsOn;
    const parentIsScoped = !!(parentScope && parentScope.length > 0);
    const canLoad = !!credentialId && (!isDependent || parentIsScoped);

    const [search, setSearch] = useState('');
    const [open, setOpen] = useState(false);
    const [options, setOptions] = useState<{ value: string; label: string }[]>([]);
    const [loading, setLoading] = useState(false);
    const [loadError, setLoadError] = useState<string | null>(null);
    const [highlighted, setHighlighted] = useState(0);
    // Sticky map of resolved labels: once the loader returns a friendly name
    // for an ID, we remember it across renders so chips never regress to
    // showing a raw ID (e.g. when a search filters the result set or the
    // dropdown is closed). Survives the lifetime of the picker.
    const [labelCache, setLabelCache] = useState<Record<string, string>>({});
    const inputRef = useRef<HTMLInputElement>(null);
    const containerRef = useRef<HTMLDivElement>(null);
    const seqRef = useRef(0);
    const parentKey = parentScope ? parentScope.join('|') : '';
    // Pinned chips with unresolved labels → triggers a one-time background
    // load on mount so chips never sit on a raw ID after the picker opens.
    const cacheKeysCount = Object.keys(labelCache).length;
    const hasUnresolvedChips = useMemo(
        () => selectedIds.some(id => !labelCache[id]),
        [selectedIds, cacheKeysCount],
    );

    // Debounced load — fires when the dropdown opens, when the search query
    // changes, when the parent scope shifts, OR when there are pinned chips
    // whose labels we haven't resolved yet (background load to populate the
    // chip text on first paint).
    useEffect(() => {
        if (!canLoad) return;
        if (!open && !hasUnresolvedChips) return;
        const seq = ++seqRef.current;
        setLoading(true);
        setLoadError(null);
        const timer = setTimeout(async () => {
            try {
                const loadOnce = async (parentValue?: string) => {
                    const response = (await sendEventAsync(
                        WorkflowNodeLoadOptionsRequest.create({
                            request_id: `scope-${field.field}-${Date.now()}-${parentValue ?? ''}`,
                            node_type: nodeType,
                            field_name: field.loaderField,
                            credential_id: credentialId,
                            search: search.trim() || undefined,
                            context: parentValue && field.dependsOn
                                ? { [field.dependsOn]: parentValue }
                                : undefined,
                        }),
                    )) as WorkflowNodeLoadOptionsResponse;
                    if (!response?.success || !response.options) {
                        throw new Error(response?.message || 'Failed to load options');
                    }
                    return response.options.map(o => ({
                        value: String(o.value),
                        label: String(o.label ?? o.value),
                    }));
                };
                const results = isDependent && parentScope
                    ? (await Promise.all(parentScope.map(p => loadOnce(p)))).flat()
                    : await loadOnce();
                if (seq !== seqRef.current) return;
                // Dedupe by value. Two parents may share an option name (e.g.
                // both spreadsheets have a "Sheet1"); pinning that name
                // implicitly allows it in any pinned parent.
                const seen = new Set<string>();
                const deduped: { value: string; label: string }[] = [];
                for (const o of results) {
                    if (!seen.has(o.value)) {
                        seen.add(o.value);
                        deduped.push(o);
                    }
                }
                setOptions(deduped);
                // Persist any new label resolutions to the sticky cache so
                // chips keep their friendly name even after a paginated load
                // pushes them out of the current options list.
                setLabelCache(prev => {
                    let changed = false;
                    const next = { ...prev };
                    for (const opt of deduped) {
                        if (opt.label && opt.label !== opt.value && next[opt.value] !== opt.label) {
                            next[opt.value] = opt.label;
                            changed = true;
                        }
                    }
                    return changed ? next : prev;
                });
            } catch (e) {
                if (seq === seqRef.current) {
                    setLoadError(e instanceof Error ? e.message : 'Failed to load options');
                }
            } finally {
                if (seq === seqRef.current) setLoading(false);
            }
        }, 200);
        return () => clearTimeout(timer);
    }, [search, credentialId, nodeType, field.loaderField, field.dependsOn, open, canLoad, isDependent, parentKey, hasUnresolvedChips]);

    // Close the dropdown on outside-click. We use composedPath() instead of
    // containerRef.current.contains(e.target) because selecting a dropdown
    // option re-renders synchronously and REMOVES the clicked row from the
    // DOM before the event bubbles to document — at which point .contains()
    // returns false for the orphaned target and the dropdown spuriously
    // closes. composedPath snapshots the DOM lineage at dispatch time, so
    // it correctly identifies inside-clicks even after mid-event DOM churn.
    useEffect(() => {
        if (!open) return;
        const onDown = (e: MouseEvent) => {
            const path = typeof e.composedPath === 'function' ? e.composedPath() : [];
            if (containerRef.current && path.includes(containerRef.current)) return;
            // Fallback for environments without composedPath (older Safari).
            if (containerRef.current?.contains(e.target as Node)) return;
            setOpen(false);
        };
        document.addEventListener('mousedown', onDown);
        return () => document.removeEventListener('mousedown', onDown);
    }, [open]);

    // Map id → label so chips show the friendly name. Sticky label cache
    // takes precedence (survives across loader pages); fresh options layer
    // on top; raw id is the last-resort fallback for resources the loader
    // has never returned (renamed/moved/deleted, or behind pagination).
    const labelById = useMemo(() => {
        const m = new Map(options.map(o => [o.value, o.label]));
        return (id: string) => m.get(id) ?? labelCache[id] ?? id;
    }, [options, labelCache]);

    // Dropdown contents: loaded options minus already-pinned ones (no point
    // showing what the user just added).
    const dropdownOptions = useMemo(
        () => options.filter(o => !selectedIds.includes(o.value)),
        [options, selectedIds],
    );

    // Reset highlight when the dropdown changes shape — keeps Enter targeting
    // the top of the list instead of a stale row that may have scrolled off.
    useEffect(() => {
        setHighlighted(0);
    }, [search, dropdownOptions.length]);

    const addId = (id: string) => {
        if (!id || selectedIds.includes(id)) return;
        onChange([...selectedIds, id]);
        setSearch('');
        // Keep the dropdown open and the input focused so the user can chain
        // multiple selections without re-clicking. requestAnimationFrame
        // beats the focus-after-re-render race in React 18 strict mode.
        setOpen(true);
        requestAnimationFrame(() => inputRef.current?.focus());
    };
    const removeId = (id: string) => onChange(selectedIds.filter(x => x !== id));

    const handleKeyDown: React.KeyboardEventHandler<HTMLInputElement> = e => {
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            setOpen(true);
            setHighlighted(h => Math.min(h + 1, Math.max(0, dropdownOptions.length - 1)));
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            setHighlighted(h => Math.max(0, h - 1));
        } else if (e.key === 'Enter') {
            const target = dropdownOptions[highlighted];
            if (target) {
                e.preventDefault();
                addId(target.value);
            }
        } else if (e.key === 'Backspace' && !search && selectedIds.length > 0) {
            e.preventDefault();
            removeId(selectedIds[selectedIds.length - 1]);
        } else if (e.key === 'Escape') {
            setOpen(false);
        }
    };

    const hint = isDependent && !parentIsScoped
        ? `Pin ${(parentLabel ?? 'the parent field').toLowerCase()} first to limit ${pluralize(field.label.toLowerCase(), 2)}.`
        : selectedIds.length > 0
          ? `${selectedIds.length} pinned · the agent can only act on ${selectedIds.length === 1 ? 'this one' : 'these'}.`
          : `Empty = allow any. Type to search and add ${pluralize(field.label.toLowerCase(), 2)}.`;

    return (
        <div className={isFirst ? 'pt-1' : 'pt-2 border-t border-foreground/[0.04]'}>
            {showFieldLabel && (
                <div className="flex items-center gap-2 px-0.5 pb-1.5">
                    <span className="text-[11px] font-semibold text-zinc-300">{field.label}</span>
                    {isDependent && parentLabel && (
                        <span className="text-[10px] text-zinc-600">
                            within {parentLabel.toLowerCase()}
                        </span>
                    )}
                </div>
            )}
            {!credentialId ? (
                <div className="flex items-start gap-1.5 text-[11px] text-zinc-500 px-0.5">
                    <Info className="w-3 h-3 mt-0.5 flex-shrink-0" />
                    <span>Connect a credential on this node to load resources to limit.</span>
                </div>
            ) : (
                <div ref={containerRef} className="relative">
                    {/* Chips row — pinned resources, rendered ABOVE the search
                        input so the search box stays clean. Empty when no
                        chips so the input takes the full first line.
                        Clicking the chip area (but not a chip's X button —
                        those stopPropagation) dismisses the dropdown, since
                        the row is logically "outside" the search affordance. */}
                    {selectedIds.length > 0 && (
                        <div
                            className="flex flex-wrap items-center gap-1 pb-1.5"
                            onMouseDown={() => setOpen(false)}
                        >
                            {selectedIds.map(id => (
                                <ResourceChip
                                    key={id}
                                    label={labelById(id)}
                                    value={id}
                                    onRemove={() => removeId(id)}
                                />
                            ))}
                            <button
                                type="button"
                                onMouseDown={e => {
                                    // stopPropagation so the chip-row close
                                    // handler doesn't fire (it'd be redundant
                                    // anyway, but kept tidy).
                                    e.preventDefault();
                                    e.stopPropagation();
                                    onChange([]);
                                }}
                                className="ml-1 text-[10px] text-muted-foreground hover:text-foreground dark:text-zinc-500 dark:hover:text-zinc-200 transition-colors px-1 py-0.5 rounded"
                                title="Remove all pinned resources"
                            >
                                Clear all
                            </button>
                        </div>
                    )}
                    {/* Search input — single-purpose, just a text field with
                        a chevron + spinner. The dropdown anchors below it. */}
                    <div
                        className={`relative flex items-center gap-1.5 px-2 py-1.5 rounded-md bg-foreground/[0.03] border transition-colors ${
                            open ? 'border-foreground/[0.18]' : 'border-foreground/[0.06]'
                        } ${isDependent && !parentIsScoped ? 'opacity-50' : ''}`}
                    >
                        <Search className="w-3 h-3 text-zinc-500 flex-shrink-0 pointer-events-none" />
                        <input
                            ref={inputRef}
                            type="text"
                            value={search}
                            onChange={e => {
                                setSearch(e.target.value);
                                setOpen(true);
                            }}
                            onFocus={() => setOpen(true)}
                            onKeyDown={handleKeyDown}
                            disabled={isDependent && !parentIsScoped}
                            placeholder={
                                selectedIds.length > 0
                                    ? `Add more ${pluralize(field.label.toLowerCase(), 2)}…`
                                    : `Add ${pluralize(field.label.toLowerCase(), 2)} to limit…`
                            }
                            className="flex-1 min-w-0 bg-transparent text-[11px] text-foreground dark:text-zinc-100 placeholder:text-[hsl(var(--placeholder))] dark:placeholder:text-zinc-600 focus:outline-none"
                        />
                        {loading && (
                            <Loader2 className="w-3 h-3 text-zinc-500 animate-spin flex-shrink-0" />
                        )}
                        {!loading && canLoad && (
                            <button
                                type="button"
                                onMouseDown={e => {
                                    e.preventDefault();
                                    setOpen(v => !v);
                                    inputRef.current?.focus();
                                }}
                                className="flex-shrink-0 text-zinc-500 hover:text-zinc-300 transition-colors"
                                aria-label={open ? 'Close suggestions' : 'Open suggestions'}
                                tabIndex={-1}
                            >
                                <ChevronDown
                                    className={`w-3 h-3 transition-transform ${open ? 'rotate-180' : ''}`}
                                />
                            </button>
                        )}
                    </div>
                    {open && canLoad && (
                        <div className="absolute z-30 left-0 right-0 mt-1 max-h-48 overflow-y-auto scrollbar-subtle rounded-md border border-border dark:border-white/[0.08] bg-popover shadow-xl">
                            {loadError ? (
                                <div className="px-2 py-1.5 text-[11px] text-amber-700 dark:text-amber-300/80">{loadError}</div>
                            ) : dropdownOptions.length === 0 ? (
                                <div className="px-2 py-1.5 text-[11px] text-zinc-500">
                                    {loading
                                        ? 'Loading…'
                                        : search.trim()
                                          ? `No matches for "${search}"`
                                          : selectedIds.length > 0 && options.length > 0
                                            ? 'All loaded options pinned.'
                                            : `No ${pluralize(field.label.toLowerCase(), 2)} available.`}
                                </div>
                            ) : (
                                dropdownOptions.map((opt, idx) => (
                                    <DropdownOptionRow
                                        key={opt.value}
                                        opt={opt}
                                        highlighted={idx === highlighted}
                                        onHover={() => setHighlighted(idx)}
                                        onSelect={() => addId(opt.value)}
                                    />
                                ))
                            )}
                        </div>
                    )}
                    <div className="text-[10px] text-zinc-600 px-0.5 pt-1.5 leading-snug">
                        {hint}
                    </div>
                </div>
            )}
        </div>
    );
}

// ResourceChip — a pinned resource ID. Shows label; raw id appears in the
// title tooltip when label ≠ value. X button removes the chip (mousedown
// guarded so the chip-container click handler doesn't refocus the input
// after a remove and reopen the dropdown immediately).
function ResourceChip({
    label,
    value,
    onRemove,
}: {
    label: string;
    value: string;
    onRemove: () => void;
}) {
    return (
        <span
            className="inline-flex items-center gap-1 max-w-full bg-foreground/[0.06] hover:bg-foreground/[0.08] rounded px-1.5 py-0.5 text-[11px] text-foreground/80 dark:text-zinc-200 transition-colors"
            title={label !== value ? value : undefined}
        >
            <span className="truncate max-w-[200px]">{label}</span>
            <button
                type="button"
                data-chip-remove
                onMouseDown={e => {
                    e.preventDefault();
                    e.stopPropagation();
                    onRemove();
                }}
                className="flex items-center justify-center w-3.5 h-3.5 rounded-sm hover:bg-foreground/[0.12] text-muted-foreground hover:text-foreground dark:text-zinc-400 dark:hover:text-zinc-100 transition-colors"
                aria-label={`Remove ${label}`}
            >
                <X className="w-2.5 h-2.5" />
            </button>
        </span>
    );
}

// DropdownOptionRow — one row in the autocomplete dropdown. Mousedown adds
// the value (not click — click fires AFTER mousedown, which would steal
// focus and close the dropdown via the outside-click handler).
function DropdownOptionRow({
    opt,
    highlighted,
    onHover,
    onSelect,
}: {
    opt: { value: string; label: string };
    highlighted: boolean;
    onHover: () => void;
    onSelect: () => void;
}) {
    const showValue = opt.label !== opt.value;
    return (
        <button
            type="button"
            // preventDefault + stopPropagation = mousedown stays inside the
            // dropdown; input never blurs, container's outside-click handler
            // never fires. The user can chain multiple selections without the
            // dropdown collapsing under them.
            onMouseDown={e => {
                e.preventDefault();
                e.stopPropagation();
                onSelect();
            }}
            onMouseEnter={onHover}
            className={`flex items-center gap-2 w-full text-left px-2 py-1 transition-colors ${
                highlighted ? 'bg-foreground/[0.06] dark:bg-white/[0.08]' : 'hover:bg-foreground/[0.04] dark:hover:bg-white/[0.04]'
            }`}
        >
            <span className={`text-[11px] truncate ${highlighted ? 'text-foreground dark:text-zinc-100' : 'text-foreground/80 dark:text-zinc-300'}`}>
                {opt.label}
            </span>
            {showValue && (
                <span className="text-[10px] text-muted-foreground dark:text-zinc-600 truncate font-mono ml-auto pl-2">
                    {opt.value}
                </span>
            )}
        </button>
    );
}

// English pluralization sugar — the scope copy reads "Limit to specific
// document" vs "documents" depending on count. Falls back to a trailing "s"
// when the word isn't a special case; the only field labels in play today
// are short nouns, so this is enough.
function pluralize(noun: string, count: number): string {
    if (count === 1) return noun;
    if (noun.endsWith('s')) return noun;
    if (noun.endsWith('y')) return noun.slice(0, -1) + 'ies';
    return noun + 's';
}

type RepoMount = { repo: string; branch: string };

// Mount editor: one row per repository (combobox + branch + remove), plus an
// "Add repository" affordance. Rows write straight to
// config.agent_sandbox_repos; empty-repo drafts are ignored at runtime
// (normalize_sandbox_repos skips them).
function SandboxMountSection({
    nodeType,
    optionsField,
    mounts,
    onChange,
    credentialId,
}: {
    nodeType: string;
    optionsField: string;
    mounts: RepoMount[];
    onChange: (mounts: RepoMount[]) => void;
    credentialId?: string;
}) {
    const updateRow = (index: number, row: RepoMount) =>
        onChange(mounts.map((m, i) => (i === index ? row : m)));
    const removeRow = (index: number) => onChange(mounts.filter((_, i) => i !== index));

    return (
        <div className="pb-3 border-b border-border dark:border-white/[0.06] space-y-2">
            <div className="flex items-center gap-2 px-1">
                <GitBranch className="w-3.5 h-3.5 text-muted-foreground flex-shrink-0" />
                <span className="text-xs font-semibold text-foreground/80">Mount repositories</span>
                <span className="text-[10px] text-muted-foreground/70 dark:text-zinc-600 uppercase tracking-wider">Optional</span>
            </div>
            <div className="px-1 text-[11px] text-muted-foreground dark:text-zinc-500 leading-relaxed">
                Clone repositories into the agent&apos;s sandbox with push access at
                the start of every run. Working trees are wiped after the run
                unless a filesystem node is attached — the agent should commit,
                push, and open pull requests via its tools.
            </div>
            {mounts.map((mount, i) => (
                <RepoMountRow
                    key={i}
                    nodeType={nodeType}
                    optionsField={optionsField}
                    mount={mount}
                    onChange={row => updateRow(i, row)}
                    onRemove={() => removeRow(i)}
                    credentialId={credentialId}
                />
            ))}
            <div className="px-1">
                <button
                    type="button"
                    onClick={() => onChange([...mounts, { repo: '', branch: '' }])}
                    className="text-[11px] font-medium text-muted-foreground hover:text-foreground px-2 py-1 rounded-md border border-border dark:border-white/[0.08] hover:bg-foreground/[0.06] transition-colors"
                >
                    + Add repository
                </button>
            </div>
        </div>
    );
}

// Searchable repo combobox for one mount row. Loads options through the
// node's own load_field_options (same socket op DynamicOptionsField uses) so
// the dropdown shows the repos the connected credential can actually access;
// free-typed owner/name values are kept as-is.
function RepoMountRow({
    nodeType,
    optionsField,
    mount,
    onChange,
    onRemove,
    credentialId,
}: {
    nodeType: string;
    optionsField: string;
    mount: RepoMount;
    onChange: (mount: RepoMount) => void;
    onRemove: () => void;
    credentialId?: string;
}) {
    const [open, setOpen] = useState(false);
    const [loading, setLoading] = useState(false);
    const [options, setOptions] = useState<string[]>([]);
    const [optionsError, setOptionsError] = useState<string | null>(null);
    const seqRef = useRef(0);
    const { repo, branch } = mount;

    // Debounced load keyed on the typed query; runs only while the dropdown
    // is open. Stale responses are dropped by sequence number.
    useEffect(() => {
        if (!open || !credentialId) return;
        const seq = ++seqRef.current;
        setLoading(true);
        setOptionsError(null);
        const timer = setTimeout(async () => {
            try {
                const response = (await sendEventAsync(
                    WorkflowNodeLoadOptionsRequest.create({
                        request_id: `mount-repo-${Date.now()}`,
                        node_type: nodeType,
                        field_name: optionsField,
                        credential_id: credentialId,
                        search: repo.trim() || undefined,
                    }),
                )) as WorkflowNodeLoadOptionsResponse;
                if (seq !== seqRef.current) return;
                if (response?.success && response.options) {
                    setOptions(response.options.map(o => String(o.value)));
                } else {
                    setOptionsError(response?.message || 'Failed to load repositories');
                }
            } catch {
                if (seq === seqRef.current) setOptionsError('Failed to load repositories');
            } finally {
                if (seq === seqRef.current) setLoading(false);
            }
        }, 250);
        return () => clearTimeout(timer);
    }, [open, repo, credentialId, nodeType, optionsField]);

    return (
        <div className="flex gap-2 px-1 items-center">
            <div className="relative flex-1 min-w-0">
                <input
                    type="text"
                    value={repo}
                    onChange={e => {
                        onChange({ repo: e.target.value, branch });
                        setOpen(true);
                    }}
                    onFocus={() => setOpen(true)}
                    onBlur={() => setTimeout(() => setOpen(false), 150)}
                    placeholder={credentialId ? 'Search repositories…' : 'owner/repository'}
                    className="w-full bg-foreground/[0.04] border border-border dark:border-white/[0.08] rounded-md px-2.5 py-1.5 text-xs text-foreground placeholder:text-[hsl(var(--placeholder))] focus:outline-none focus:border-foreground/[0.2]"
                />
                {loading && (
                    /* Centering lives on the wrapper: animate-spin's keyframes
                       write `transform: rotate(...)`, which would clobber a
                       -translate-y-1/2 on the same element (icon bobs instead
                       of spinning). */
                    <span className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center pointer-events-none">
                        <Loader2 className="w-3 h-3 text-muted-foreground dark:text-zinc-500 animate-spin" />
                    </span>
                )}
                {open && credentialId && (options.length > 0 || optionsError) && (
                    <div className="absolute z-30 left-0 right-0 mt-1 max-h-48 overflow-y-auto scrollbar-subtle rounded-md border border-border/80 dark:border-zinc-700/80 bg-card shadow-xl">
                        {optionsError ? (
                            <div className="px-2.5 py-2 text-[11px] text-muted-foreground dark:text-zinc-500">{optionsError}</div>
                        ) : (
                            options.map(name => (
                                <button
                                    key={name}
                                    type="button"
                                    onMouseDown={e => e.preventDefault()}
                                    onClick={() => {
                                        onChange({ repo: name, branch });
                                        setOpen(false);
                                    }}
                                    className={`block w-full text-left px-2.5 py-1.5 text-xs transition-colors ${
                                        name === repo
                                            ? 'text-foreground bg-foreground/[0.08]'
                                            : 'text-foreground/80 hover:bg-foreground/[0.06]'
                                    }`}
                                >
                                    {name}
                                </button>
                            ))
                        )}
                    </div>
                )}
            </div>
            <input
                type="text"
                value={branch}
                onChange={e => onChange({ repo, branch: e.target.value })}
                placeholder="branch (default)"
                className="w-28 bg-foreground/[0.04] border border-border dark:border-white/[0.08] rounded-md px-2.5 py-1.5 text-xs text-foreground placeholder:text-[hsl(var(--placeholder))] focus:outline-none focus:border-foreground/[0.2]"
            />
            <button
                type="button"
                onClick={onRemove}
                title="Remove repository"
                className="flex-shrink-0 w-6 h-6 flex items-center justify-center rounded-md text-muted-foreground dark:text-zinc-500 hover:text-red-400 hover:bg-foreground/[0.06] transition-colors text-sm leading-none"
            >
                ×
            </button>
        </div>
    );
}

function QuickSelectButton({
    label,
    title,
    onClick,
}: {
    label: string;
    title?: string;
    onClick: () => void;
}) {
    return (
        <button
            type="button"
            onClick={onClick}
            title={title}
            className="text-[11px] font-medium text-muted-foreground hover:text-foreground px-2 py-0.5 rounded-md border border-border dark:border-white/[0.08] hover:bg-foreground/[0.06] transition-colors whitespace-nowrap"
        >
            {label}
        </button>
    );
}
