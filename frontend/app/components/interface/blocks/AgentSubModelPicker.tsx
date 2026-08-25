// Compact sub-model picker for CLI harness agents (Codex, Claude Code,
// OpenCode, OpenClaw, Hermes). Each harness exposes its own sub-model
// field (codex_model, claude_code_model, opencode_model, openclaw_model,
// hermes_agent_model) loaded via the same `workflow:node:load_options`
// channel the canvas node config uses. We surface it in the chat
// settings sidebar so users can switch the underlying model without
// leaving the chat surface.
//
// Visually deliberately smaller / denser than AgentModelPicker (which
// is a big header anchor) — sidebar density matters.

import { useState, useEffect, useMemo, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { ChevronDown, Search, Check, Loader2 } from 'lucide-react';
import {
    sendEventAsync,
    WorkflowNodeLoadOptionsRequest,
} from '~/lib/socket-sender';
import type {
    WorkflowNodeLoadOptionsResponse,
    FieldOption,
} from '~/types/socket-events.generated';
import { cn } from '~/lib/utils';
import { fuzzyFilter } from '~/utils/fuzzySearch';
import { useAnchoredPopover } from './useAnchoredPopover';

interface AgentSubModelPickerProps {
    fieldName: string;
    selectedModelId: string;
    onSelect: (modelId: string) => void;
    disabled?: boolean;
}

// Per-field module cache so reopening the popover or remounting the block
// is instant. Keyed by the agent's sub-model field name (codex_model, …).
const optionsCache = new Map<string, FieldOption[]>();
const inflightLoads = new Map<string, Promise<FieldOption[]>>();

function loadOptionsFor(fieldName: string): Promise<FieldOption[]> {
    const cached = optionsCache.get(fieldName);
    if (cached) return Promise.resolve(cached);
    const inflight = inflightLoads.get(fieldName);
    if (inflight) return inflight;
    const p = (async () => {
        try {
            const resp = (await sendEventAsync(
                WorkflowNodeLoadOptionsRequest.create({
                    node_type: 'agent',
                    field_name: fieldName,
                    credential_id: '',
                })
            )) as WorkflowNodeLoadOptionsResponse;
            const opts = (resp?.options || []) as FieldOption[];
            optionsCache.set(fieldName, opts);
            return opts;
        } finally {
            inflightLoads.delete(fieldName);
        }
    })();
    inflightLoads.set(fieldName, p);
    return p;
}

export function AgentSubModelPicker({
    fieldName,
    selectedModelId,
    onSelect,
    disabled,
}: AgentSubModelPickerProps) {
    const [options, setOptions] = useState<FieldOption[]>(
        () => optionsCache.get(fieldName) ?? []
    );
    const [loading, setLoading] = useState(() => !optionsCache.has(fieldName));
    const [query, setQuery] = useState('');

    // Compact left-anchored popover under the trigger, min 320px wide.
    const computePos = useCallback(
        (rect: DOMRect) => ({
            top: rect.bottom + 4,
            left: rect.left,
            width: Math.max(rect.width, 320),
        }),
        []
    );
    const { open, setOpen, triggerRef, panelRef, pos } =
        useAnchoredPopover<HTMLButtonElement>(computePos);

    // Eager prefetch + refetch when the field changes (CLI harness switch).
    useEffect(() => {
        let cancelled = false;
        const cached = optionsCache.get(fieldName);
        if (cached) {
            setOptions(cached);
            setLoading(false);
            return;
        }
        setLoading(true);
        setOptions([]);
        loadOptionsFor(fieldName)
            .then((opts) => {
                if (!cancelled) setOptions(opts);
            })
            .catch((err) =>
                console.warn('[AgentSubModelPicker] load failed', err)
            )
            .finally(() => {
                if (!cancelled) setLoading(false);
            });
        return () => {
            cancelled = true;
        };
    }, [fieldName]);

    const selectedOption = useMemo(
        () => options.find((o) => o.value === selectedModelId) || null,
        [options, selectedModelId]
    );
    const displayLabel = selectedOption?.label || selectedModelId || 'Select…';

    const filtered = useMemo(
        () =>
            fuzzyFilter(options, query, (o) => [
                { text: o.label.toLowerCase(), weight: 1, fuzzy: true },
                { text: o.value.toLowerCase(), weight: 0.6, fuzzy: true },
            ]),
        [options, query]
    );

    return (
        <>
            <button
                ref={triggerRef}
                type="button"
                disabled={disabled}
                onClick={() => setOpen((o) => !o)}
                data-testid="agent-sub-model-trigger"
                className="group w-full flex items-center justify-between gap-2 rounded-lg border border-border bg-sunken hover:border-border dark:hover:border-zinc-700 transition-colors px-3 py-2 text-left disabled:opacity-50 disabled:cursor-not-allowed"
            >
                <span className="text-sm text-foreground truncate min-w-0">
                    {displayLabel}
                </span>
                <ChevronDown className="w-3.5 h-3.5 text-muted-foreground dark:text-zinc-500 shrink-0 group-hover:text-foreground/80 transition-colors" />
            </button>

            {open &&
                pos &&
                createPortal(
                    <div
                        ref={panelRef}
                        style={{
                            top: pos.top,
                            left: pos.left,
                            width: pos.width,
                        }}
                        className="fixed z-[60] rounded-xl border border-border bg-popover/95 dark:bg-zinc-950/95 backdrop-blur-md shadow-2xl overflow-hidden"
                        data-testid="agent-sub-model-panel"
                    >
                        <div className="px-3 py-2 border-b border-border dark:border-zinc-900 flex items-center gap-2">
                            <Search className="w-3.5 h-3.5 text-muted-foreground dark:text-zinc-500 shrink-0" />
                            <input
                                autoFocus
                                value={query}
                                onChange={(e) => setQuery(e.target.value)}
                                placeholder="Search…"
                                className="flex-1 bg-transparent outline-none text-xs text-foreground placeholder:text-[hsl(var(--placeholder))]"
                            />
                            {loading ? (
                                <Loader2 className="w-3.5 h-3.5 text-muted-foreground dark:text-zinc-500 animate-spin shrink-0" />
                            ) : null}
                        </div>
                        <div className="max-h-[300px] overflow-y-auto scrollbar-subtle py-1">
                            {filtered.length === 0 ? (
                                <div className="px-3 py-4 text-center text-xs text-muted-foreground/70 dark:text-zinc-600">
                                    {loading ? 'Loading' : 'No matches'}
                                </div>
                            ) : (
                                filtered.map((opt) => {
                                    const isSelected =
                                        selectedModelId === opt.value;
                                    return (
                                        <button
                                            key={opt.value}
                                            type="button"
                                            onClick={() => {
                                                onSelect(opt.value);
                                                setOpen(false);
                                                setQuery('');
                                            }}
                                            className={cn(
                                                'w-full flex items-center gap-2 px-3 py-1.5 text-left transition-colors',
                                                isSelected
                                                    ? 'bg-foreground/[0.06]'
                                                    : 'hover:bg-foreground/[0.03]'
                                            )}
                                        >
                                            <div className="flex-1 min-w-0">
                                                <div className="text-xs text-foreground truncate">
                                                    {opt.label}
                                                </div>
                                                {opt.value !== opt.label ? (
                                                    <div className="text-[10px] text-muted-foreground dark:text-zinc-500 truncate font-mono">
                                                        {opt.value}
                                                    </div>
                                                ) : null}
                                            </div>
                                            {isSelected ? (
                                                <Check className="w-3.5 h-3.5 text-foreground/80 shrink-0" />
                                            ) : null}
                                        </button>
                                    );
                                })
                            )}
                        </div>
                    </div>,
                    document.body
                )}
        </>
    );
}

/** Map a primary model id (the value of `config.model`) to the CLI harness
 *  sub-model field it exposes, if any. Returns null for regular LLMs. */
export function getCliSubModelField(model: string | undefined): {
    fieldName: string;
    label: string;
    configKey: string;
} | null {
    switch (model) {
        case 'codex':
            return {
                fieldName: 'codex_model',
                configKey: 'codex_model',
                label: 'Codex Model',
            };
        case 'claude-code':
            return {
                fieldName: 'claude_code_model',
                configKey: 'claude_code_model',
                label: 'Claude Code Model',
            };
        case 'opencode':
            return {
                fieldName: 'opencode_model',
                configKey: 'opencode_model',
                label: 'OpenCode Model',
            };
        case 'openclaw':
            return {
                fieldName: 'openclaw_model',
                configKey: 'openclaw_model',
                label: 'OpenClaw Model',
            };
        case 'hermes':
            return {
                fieldName: 'hermes_agent_model',
                configKey: 'hermes_agent_model',
                label: 'Hermes Model',
            };
        default:
            return null;
    }
}
