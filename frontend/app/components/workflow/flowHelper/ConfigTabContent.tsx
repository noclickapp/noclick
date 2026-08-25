import { Node } from '@xyflow/react';
import {
    AlertCircle,
    CheckCircle2,
    ChevronDown,
    Loader2,
    Sparkles,
} from 'lucide-react';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { InlineTextEditor } from '~/components/ui/InlineTextEditor';
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '~/components/ui/dropdown-menu';
import { EVENTS } from '~/lib/analytics-events';
import { useAnalytics } from '~/lib/analytics';
import { getFieldErrorMap, parseExecutionError } from '~/utils/pydanticErrorParser';
import { getDefaultLabelFromType } from '../nodes/base/NodeLabel';
import { AgentToolOperationsPicker } from '../AgentToolOperationsPicker';
import { hasUnconnectedCredentials, providerCredentialsMissing } from '../NodeCredentials';
import { NodeConfig } from '../NodeConfig';
import { NodeExecutionErrorBanner } from './NodeExecutionErrorBanner';

type AutofillMode = 'full' | 'operation' | 'fields' | 'single_field';
type AutofillStatus = { nodeId: string | null; mode: AutofillMode | null; targetField: string | null };
type ConfigView = 'configuration' | 'settings';
type ValidationState = { validating: boolean; valid: boolean };

interface ConfigTabContentProps {
    selectedNode: Node | null;
    onNodeDataUpdate?: (nodeId: string, newData: Record<string, any>) => void;
    onInjectIteration?: (nodeId: string, fieldKey: string) => void;
    fieldHoldsArrayRef?: (value: unknown) => boolean;
    workflowId?: string;
    workflowVariables?: Record<string, any>;
    onVariableValueChange?: (name: string, value: string) => void;
    /** Nested config fields extracted from selectedNode.data.config (authoritative user/AI-editable fields). */
    nodeConfig: Record<string, any>;
    /** Credential IDs with {{vars.*}} references resolved to actual UUIDs for dynamic option loaders. */
    credentialIds: Record<string, string>;
    onSwitchToCredentials: () => void;
    onAutofill?: (nodeId: string, mode: AutofillMode, targetField?: string) => Promise<void>;
    isAutofilling?: boolean;
    autofillStatus?: AutofillStatus;
    /** Added for parity with the old inline handler — currently a no-op. */
    onValidationChange: (valid: boolean) => void;
    onConfigChange: (newConfig: Record<string, any>, sourceNodeId?: string) => void;
    /** When the selected node matches this id, the config panel scrolls to the top so the user lands on a fresh form. */
    freshlyDroppedNodeId?: string | null;
    onConsumeFreshlyDroppedNode?: () => void;
    /** Auto-focus the operation picker when it opens. False during keyboard
     *  node-traversal so it doesn't trap arrow navigation. */
    autoFocusOperationPicker?: boolean;
    showInputPrompt?: boolean;
    onShowInputPrompt?: () => void;
    showOutputPrompt?: boolean;
    onShowOutputPrompt?: () => void;
    /** Node is wired to an AI agent's bottom handle as a tool provider — its
     *  config view becomes the operation allowlist instead of the normal form. */
    agentToolProviderMode?: boolean;
    /** Consumer kinds the provider feeds (agent / mcp-server) — banner copy. */
    toolProviderConsumerTypes?: Array<'agent' | 'mcp-server'>;
    /** Global content rendered ABOVE the config form — not tied to any
     *  schema field (e.g. the MCP node's connect-externally affordance). */
    headerSlot?: ReactNode;
    /** Extra content rendered under named schema fields (NodeConfig
     *  pass-through), e.g. the agent's trigger chips under `message`. */
    fieldAddons?: Record<string, ReactNode>;
}

// Autofill dropdown menu items. Structurally identical save for mode / copy /
// disabled-when-no-operation, so we render them in a loop.
const AUTOFILL_ITEMS: Array<{
    mode: AutofillMode;
    label: string;
    description: string;
    /** When true, the item is disabled if no operation is selected on the node. */
    requiresOperation: boolean;
}> = [
    { mode: 'full', label: 'Autofill everything', description: 'Re-pick operation + fill all fields', requiresOperation: false },
    { mode: 'fields', label: 'Fill all fields', description: 'Keep current operation', requiresOperation: true },
];

export function ConfigTabContent({
    selectedNode,
    onNodeDataUpdate,
    onInjectIteration,
    fieldHoldsArrayRef,
    workflowId,
    workflowVariables,
    onVariableValueChange,
    nodeConfig,
    credentialIds,
    onSwitchToCredentials,
    onAutofill,
    isAutofilling,
    autofillStatus,
    onValidationChange,
    onConfigChange,
    freshlyDroppedNodeId,
    onConsumeFreshlyDroppedNode,
    autoFocusOperationPicker = true,
    showInputPrompt = false,
    onShowInputPrompt,
    showOutputPrompt = false,
    onShowOutputPrompt,
    agentToolProviderMode = false,
    toolProviderConsumerTypes,
    headerSlot,
    fieldAddons,
}: ConfigTabContentProps) {
    const { logActivity } = useAnalytics();
    const [configActiveView, setConfigActiveView] = useState<ConfigView>('configuration');
    const [nodeValidationState, setNodeValidationState] = useState<ValidationState>({ validating: false, valid: true });

    // Read freshlyDroppedNodeId / consumer through refs so consuming the
    // signal doesn't retrigger the reset effect.
    const freshlyDroppedNodeIdRef = useRef(freshlyDroppedNodeId);
    const onConsumeFreshlyDroppedNodeRef = useRef(onConsumeFreshlyDroppedNode);
    useEffect(() => {
        freshlyDroppedNodeIdRef.current = freshlyDroppedNodeId;
        onConsumeFreshlyDroppedNodeRef.current = onConsumeFreshlyDroppedNode;
    }, [freshlyDroppedNodeId, onConsumeFreshlyDroppedNode]);

    // Reset view + validation when the selected node changes. A freshly
    // drag-dropped node consumes its one-shot flag and scrolls the panel back
    // to the top so the user lands on a clean config form even if they were
    // scrolled down before.
    useEffect(() => {
        setConfigActiveView('configuration');
        if (selectedNode?.id && selectedNode.id === freshlyDroppedNodeIdRef.current) {
            onConsumeFreshlyDroppedNodeRef.current?.();
            requestAnimationFrame(() => {
                document.querySelector('[data-flow-helper-scroll="true"]')?.scrollTo({ top: 0 });
            });
        }
        setNodeValidationState({ validating: false, valid: true });
    }, [selectedNode?.id]);

    if (!selectedNode) {
        return (
            <div className="flex items-center justify-center h-full">
                <div className="text-center text-muted-foreground dark:text-zinc-500 text-sm">
                    Select a node to view its configuration
                </div>
            </div>
        );
    }

    const defaultLabel = getDefaultLabelFromType(selectedNode.type || '');
    const executionError = selectedNode.data?.error;
    const fieldErrors = executionError
        ? getFieldErrorMap(
              parseExecutionError(
                  typeof executionError === 'string'
                      ? executionError
                      : JSON.stringify(executionError)
              )
          )
        : undefined;

    return (
        <div className="space-y-4">
            <NodeExecutionErrorBanner node={selectedNode} />

            {/* Label, ID, config-view toggle, autofill + validation status.
                Stacked so the centered view toggle never collides with the
                label/name or autofill controls on narrow panels. */}
            <div className="space-y-2">
                {!agentToolProviderMode && (
                    <div className="flex justify-center">
                        <ConfigViewToggle value={configActiveView} onChange={setConfigActiveView} />
                    </div>
                )}
                <div className="flex flex-wrap items-start justify-between gap-x-2 gap-y-1">
                    <div className="min-w-0 flex-1">
                        <div className="text-[11px] text-muted-foreground dark:text-zinc-500 uppercase tracking-wider mb-1">Label</div>
                        <InlineTextEditor
                            value={String(selectedNode.data?.label || defaultLabel)}
                            placeholder={defaultLabel}
                            onSave={(newLabel) => {
                                if (!onNodeDataUpdate) return;
                                // Clear custom label when user types the default value back
                                const labelToSave = newLabel === defaultLabel ? undefined : newLabel || undefined;
                                onNodeDataUpdate(selectedNode.id, { label: labelToSave });
                            }}
                            isDefaultValue={!selectedNode.data?.label}
                            maxWidth={300}
                            inputClassName="!text-foreground !px-0 !py-0"
                            spanClassName="!text-foreground !px-0 !py-0"
                        />
                    </div>

                    {configActiveView === 'configuration' && !agentToolProviderMode && (
                        <div className="flex items-center gap-2 flex-shrink-0">
                            {onAutofill && (
                                <AutofillDropdown
                                    isAutofilling={!!isAutofilling}
                                    hasOperation={!!selectedNode.data?.operation}
                                    onSelect={(mode) => {
                                        logActivity(EVENTS.NODE_AUTOFILL_INVOKED, {
                                            mode,
                                            node_id: selectedNode.id,
                                            node_type: selectedNode.type,
                                            workflow_id: workflowId,
                                        });
                                        onAutofill(selectedNode.id, mode);
                                    }}
                                />
                            )}
                            <ValidationStatusBadge state={nodeValidationState} />
                        </div>
                    )}
                </div>
            </div>

            {/* Tool-provider mode: the node is wired to an agent's bottom handle,
                so the config form is replaced by the operation allowlist. */}
            {agentToolProviderMode ? (
                <AgentToolOperationsPicker
                    key={selectedNode.id}
                    nodeType={selectedNode.type || 'default'}
                    consumerTypes={toolProviderConsumerTypes}
                    selectedOperations={
                        Array.isArray(nodeConfig.agent_tool_operations)
                            ? (nodeConfig.agent_tool_operations as string[])
                            : []
                    }
                    onChange={(ops) =>
                        onConfigChange({ ...nodeConfig, agent_tool_operations: ops }, selectedNode.id)
                    }
                    sandboxMounts={
                        Array.isArray(nodeConfig.agent_sandbox_repos)
                            ? (nodeConfig.agent_sandbox_repos as { repo?: string; branch?: string }[]).map(m => ({
                                  repo: typeof m?.repo === 'string' ? m.repo : '',
                                  branch: typeof m?.branch === 'string' ? m.branch : '',
                              }))
                            : []
                    }
                    onSandboxMountsChange={(mounts) =>
                        onConfigChange({ ...nodeConfig, agent_sandbox_repos: mounts }, selectedNode.id)
                    }
                    mountCredentialId={
                        Object.entries(credentialIds).find(([k, v]) => k !== 'credential_type' && v)?.[1]
                    }
                    credentialsMissing={providerCredentialsMissing(
                        selectedNode.type || '',
                        credentialIds,
                        selectedNode.data as Record<string, any>,
                    )}
                    onConnectCredentials={onSwitchToCredentials}
                />
            ) : (<>
            {headerSlot}
            {/* Configuration form — auto-generated from JSON schema. key={selectedNode.id}
                forces a fresh localConfig state when the user switches nodes. */}
            <NodeConfig
                key={selectedNode.id}
                nodeType={selectedNode.type || 'default'}
                config={nodeConfig}
                onChange={onConfigChange}
                onInjectIteration={onInjectIteration}
                fieldHoldsArrayRef={fieldHoldsArrayRef}
                operation={selectedNode.data?.operation as string | undefined}
                onOperationChange={(op) => {
                    if (onNodeDataUpdate) onNodeDataUpdate(selectedNode.id, { operation: op });
                }}
                onValidationChange={onValidationChange}
                onSwitchToCredentials={onSwitchToCredentials}
                credentialIds={credentialIds}
                workflowId={workflowId}
                nodeId={selectedNode.id}
                workflowVariables={workflowVariables}
                onVariableValueChange={onVariableValueChange}
                fieldErrors={fieldErrors}
                activeView={configActiveView}
                onActiveViewChange={setConfigActiveView}
                onValidationStateChange={setNodeValidationState}
                onAutofillField={onAutofill ? (fieldKey) => onAutofill(selectedNode.id, 'single_field', fieldKey) : undefined}
                onAutofillOperation={onAutofill ? () => onAutofill(selectedNode.id, 'operation') : undefined}
                isAutofilling={isAutofilling}
                autofillingFieldKey={
                    autofillStatus?.nodeId === selectedNode.id && autofillStatus?.mode === 'single_field'
                        ? autofillStatus.targetField
                        : null
                }
                isAutofillingOperation={autofillStatus?.nodeId === selectedNode.id && autofillStatus?.mode === 'operation'}
                autoFocusOperationPicker={autoFocusOperationPicker}
                showInputPrompt={showInputPrompt}
                onShowInputPrompt={onShowInputPrompt}
                showOutputPrompt={showOutputPrompt}
                onShowOutputPrompt={onShowOutputPrompt}
                fieldAddons={fieldAddons}
            />
            </>)}

        </div>
    );
}

const CONFIG_VIEW_LABELS: Record<ConfigView, string> = {
    configuration: 'Configuration',
    settings: 'Settings',
};

function ConfigViewToggle({ value, onChange }: { value: ConfigView; onChange: (v: ConfigView) => void }) {
    return (
        <div className="flex items-center gap-0.5 rounded-lg border border-border bg-muted p-0.5 dark:border-foreground/[0.08] dark:bg-foreground/[0.02]">
            {(['configuration', 'settings'] as const).map((view) => (
                <button
                    key={view}
                    type="button"
                    onClick={() => onChange(view)}
                    className={`px-3 py-1 rounded-md text-[11px] font-medium uppercase tracking-wider transition-all ${
                        value === view
                            ? 'bg-card text-foreground shadow-sm dark:bg-foreground/[0.10] dark:shadow-none'
                            : 'text-muted-foreground dark:text-zinc-500 hover:text-foreground/80 hover:bg-foreground/[0.04]'
                    }`}
                >
                    {CONFIG_VIEW_LABELS[view]}
                </button>
            ))}
        </div>
    );
}

function AutofillDropdown({
    isAutofilling,
    hasOperation,
    onSelect,
}: {
    isAutofilling: boolean;
    hasOperation: boolean;
    onSelect: (mode: AutofillMode) => void;
}) {
    return (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>
                <button
                    type="button"
                    disabled={isAutofilling}
                    className="flex items-center gap-1 px-2 py-1 rounded-md text-[11px] font-medium text-muted-foreground hover:text-foreground hover:bg-accent dark:hover:bg-zinc-800/50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    title="AI autofill this node"
                >
                    {isAutofilling ? <Loader2 className="h-3 w-3 animate-spin" /> : <Sparkles className="h-3 w-3" />}
                    <span>Autofill</span>
                    <ChevronDown className="h-3 w-3 opacity-70" />
                </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent
                align="end"
                sideOffset={6}
                className="min-w-[240px] p-1.5 bg-popover/98 backdrop-blur-xl border border-border dark:border-white/10 shadow-xl dark:shadow-black/40 rounded-lg"
            >
                {AUTOFILL_ITEMS.map((item, idx) => (
                    <div key={item.mode}>
                        {idx > 0 && <DropdownMenuSeparator className="my-1 bg-foreground/[0.06]" />}
                        <DropdownMenuItem
                            onClick={() => onSelect(item.mode)}
                            disabled={isAutofilling || (item.requiresOperation && !hasOperation)}
                            className="flex items-center gap-2 px-2.5 py-2 rounded-md cursor-pointer text-foreground/80 focus:text-foreground focus:bg-foreground/[0.06] hover:text-foreground hover:bg-foreground/[0.06] disabled:opacity-40 disabled:cursor-not-allowed"
                        >
                            <Sparkles className="h-3.5 w-3.5 text-muted-foreground" />
                            <div className="flex flex-col">
                                <span className="text-sm">{item.label}</span>
                                <span className="text-[10px] text-muted-foreground dark:text-zinc-500">{item.description}</span>
                            </div>
                        </DropdownMenuItem>
                    </div>
                ))}
            </DropdownMenuContent>
        </DropdownMenu>
    );
}

function ValidationStatusBadge({ state }: { state: ValidationState }) {
    if (state.validating) {
        return (
            <>
                <Loader2 className="h-3 w-3 text-muted-foreground dark:text-zinc-500 animate-spin" />
                <span className="text-xs text-muted-foreground dark:text-zinc-500">Validating...</span>
            </>
        );
    }
    if (state.valid) {
        return (
            <>
                <CheckCircle2 className="h-4 w-4 text-green-600 dark:text-green-500" />
                <span className="text-xs text-green-600 dark:text-green-500">Valid</span>
            </>
        );
    }
    return (
        <>
            <AlertCircle className="h-4 w-4 text-amber-600 dark:text-amber-500" />
            <span className="text-xs text-amber-600 dark:text-amber-500">Incomplete</span>
        </>
    );
}
