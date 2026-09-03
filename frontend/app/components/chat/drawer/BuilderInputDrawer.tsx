// Drawer component for the agentic builder to request user input mid-conversation.
// Shows one input at a time (step-by-step wizard) for MCQ choices, credential
// connections, and config fields (with schema-driven widget selection).
// Blocks the builder until the user completes all steps.

import { useState, useCallback, useRef, useEffect, useMemo } from 'react';
import { CheckCircle2, ArrowRight, ChevronLeft, Plus, Link2, Check } from 'lucide-react';
import { cn } from '~/lib/utils';
import { NodeCredentials } from '~/components/workflow/NodeCredentials';
import { DynamicOptionsField } from '~/components/workflow/DynamicOptionsField';
import type { InputRequest } from '~/components/workflow/workflowGeneratorMock';
import { AgentEnvVarsSection } from '~/components/workflow/AgentEnvVarsSection';
import { AGENT_ENV_CREDENTIAL_TYPE } from '~/components/workflow/agentEnvVars';
import { getFieldAffordance } from './builderInputAffordances';
import { MULTI_PREFIX, encodeMultiValue, flattenMultiValue, parseMultiValue } from './multiSelectValue';

// ============================================================================
// Types
// ============================================================================

export interface BuilderInputDrawerProps {
    /** Batch of input requests from the agentic builder */
    inputs: InputRequest[];
    /** Optional title shown at the top of the drawer */
    title?: string;
    /** Called when the user submits all values */
    onSubmit: (values: Record<string, string>) => void;
    /** Called when the user dismisses (optional — omit to prevent dismissal) */
    onDismiss?: () => void;
    /** Called when the user picks a field affordance (e.g. "Create new
     *  spreadsheet"); routes the message to the same input_response handler
     *  with `message` set. The bridge folds in any fields already answered in
     *  the form (via onValuesChange) so the agent gets the partial answers plus
     *  the user's words — the user never has to repeat themselves. */
    onSubmitMessage?: (message: string) => void;
    /** Called whenever the in-progress answers change, with the cleaned values.
     *  The bridge mirrors these so a free-form chatbox reply mid-wizard can
     *  carry the partially-filled form along with the typed message. */
    onValuesChange?: (values: Record<string, string>) => void;
    /** Mint (or reuse) a public input-bridge link for this ask and resolve to
     *  its URL — anyone holding it can answer without a NoClick account. When
     *  provided, a small link button renders next to the title so the user can
     *  hand these questions to whoever actually has the answers. */
    onShare?: () => Promise<string | null>;
    /** Render inside a host that already shows the ask's title and provider
     *  (the Dashboard's queue row): no header or step dots, no padding, and a
     *  hairline footer carrying Back · step counter · Copy link · Skip · Continue. */
    embedded?: boolean;
}

// ============================================================================
// Helpers
// ============================================================================

function isRequired(input: InputRequest): boolean {
    if (input.type === 'credential' || input.type === 'env') return input.required;
    if (input.fieldSchema && 'default' in input.fieldSchema) return false;
    return input.required;
}

// ============================================================================
// Sub-components
// ============================================================================

/** Small link icon next to the drawer title: mints the public input-bridge
 *  link for this ask and copies it — so the user can hand the questions to
 *  whoever actually has the answers (they need no NoClick account). */
function ShareAskButton({ onShare, label }: { onShare: () => Promise<string | null>; label?: string }) {
    const [state, setState] = useState<'idle' | 'busy' | 'copied'>('idle');
    const click = async () => {
        if (state === 'busy') return;
        setState('busy');
        try {
            const url = await onShare();
            if (url) {
                await navigator.clipboard.writeText(url);
                setState('copied');
                setTimeout(() => setState('idle'), 2000);
                return;
            }
        } catch { /* fall through to idle */ }
        setState('idle');
    };
    const icon = state === 'copied'
        ? <Check className="h-3.5 w-3.5 text-emerald-500" />
        : <Link2 className={cn('h-3.5 w-3.5', state === 'busy' && 'animate-pulse')} />;
    return (
        <button
            type="button"
            onClick={() => void click()}
            data-testid="builder-ask-share"
            title="Copy a public link so anyone can answer these questions (no login)"
            className={label
                ? 'inline-flex shrink-0 items-center gap-1.5 text-[12.5px] text-foreground/70 dark:text-foreground/50 transition-colors hover:text-foreground'
                : 'shrink-0 rounded-md p-1 text-muted-foreground dark:text-zinc-500 transition-colors hover:bg-foreground/[0.06] hover:text-foreground'}
        >
            {icon}
            {label && (state === 'copied' ? 'Copied' : label)}
        </button>
    );
}

// Prefix for "other" freetext values — distinguishes them from option IDs
const OTHER_PREFIX = 'other:';

/** Strip the "other:" prefix, flatten "multi:" encodings to comma-joined
 *  answers, and trim every value — the shape the backend input_response
 *  handler expects. Drops keys that clean to empty so partial submits never
 *  carry blank answers. */
function cleanValues(values: Record<string, string>): Record<string, string> {
    const out: Record<string, string> = {};
    for (const [k, v] of Object.entries(values)) {
        const cleaned = v.startsWith(MULTI_PREFIX)
            ? flattenMultiValue(v)
            : v.startsWith(OTHER_PREFIX)
                ? v.slice(OTHER_PREFIX.length).trim()
                : v.trim();
        if (cleaned) out[k] = cleaned;
    }
    return out;
}

/** MCQ selection with an "Other" option that expands into a text input.
 *  `multiple` (from <ask multiple="true">) renders checkboxes that toggle, with
 *  picks accumulated in a MULTI_PREFIX-encoded value (flattened to a
 *  comma-joined answer on submit); default is single-choice radios. */
function SelectionInput({
    options,
    value,
    onChange,
    multiple,
}: {
    options: { id: string; label: string }[];
    value: string | undefined;
    onChange: (value: string) => void;
    multiple?: boolean;
}) {
    const multi = multiple ? parseMultiValue(value) : null;
    const isOther = multi ? multi.other !== null : !!value && value.startsWith(OTHER_PREFIX);
    const otherText = multi ? (multi.other ?? '') : (isOther && value ? value.slice(OTHER_PREFIX.length) : '');
    const otherInputRef = useRef<HTMLInputElement>(null);

    // Auto-focus the text input when "Other" is selected
    useEffect(() => {
        if (isOther && otherInputRef.current) {
            otherInputRef.current.focus();
        }
    }, [isOther]);

    const isSelected = (id: string) => (multi ? multi.selected.includes(id) : value === id);
    const pick = (id: string) => {
        if (!multi) { onChange(id); return; }
        const selected = multi.selected.includes(id)
            ? multi.selected.filter(s => s !== id)
            : [...multi.selected, id];
        onChange(encodeMultiValue({ ...multi, selected }));
    };
    const pickOther = () => {
        if (!multi) { if (!isOther) onChange(OTHER_PREFIX); return; }
        onChange(encodeMultiValue({ ...multi, other: multi.other === null ? '' : null }));
    };
    const setOtherText = (text: string) => {
        if (!multi) { onChange(OTHER_PREFIX + text); return; }
        onChange(encodeMultiValue({ ...multi, other: text }));
    };

    // Checkbox square for multi, radio dot for single — the affordance that
    // tells the user whether several options can be picked.
    const indicator = (selected: boolean) => multiple ? (
        <div className={cn(
            "w-3.5 h-3.5 rounded-[4px] border-2 shrink-0 flex items-center justify-center",
            selected ? "border-foreground bg-foreground" : "border-foreground/30"
        )}>
            {selected && <Check className="w-2.5 h-2.5 text-background" strokeWidth={3} />}
        </div>
    ) : (
        <div className={cn(
            "w-3 h-3 rounded-full border-2 shrink-0",
            selected ? "border-foreground bg-foreground" : "border-foreground/30"
        )} />
    );

    return (
        <div className="space-y-1.5">
            {multiple && (
                <p className="text-[11px] text-muted-foreground dark:text-zinc-500">Select all that apply</p>
            )}
            {options.map(option => (
                <button
                    key={option.id}
                    onClick={e => { e.stopPropagation(); pick(option.id); }}
                    className={cn(
                        "w-full flex items-center gap-2 px-3 py-2 rounded-lg border text-left text-sm outline-none",
                        isSelected(option.id)
                            ? "border-foreground/30 bg-foreground/10 text-foreground"
                            : "border-border dark:border-white/[0.06] bg-foreground/[0.02] text-muted-foreground dark:text-white/60 hover:bg-foreground/[0.05] hover:border-border dark:hover:border-foreground/10"
                    )}
                >
                    {indicator(isSelected(option.id))}
                    {option.label}
                </button>
            ))}
            {/* Other option */}
            <button
                onClick={e => { e.stopPropagation(); pickOther(); }}
                className={cn(
                    "w-full flex items-center gap-2 px-3 py-2 rounded-lg border text-left text-sm outline-none",
                    isOther
                        ? "border-foreground/30 bg-foreground/10 text-foreground"
                        : "border-border dark:border-white/[0.06] bg-foreground/[0.02] text-muted-foreground dark:text-white/60 hover:bg-foreground/[0.05] hover:border-border dark:hover:border-foreground/10"
                )}
            >
                {indicator(isOther)}
                {isOther ? (
                    <input
                        ref={otherInputRef}
                        type="text"
                        value={otherText}
                        onChange={e => setOtherText(e.target.value)}
                        onClick={e => e.stopPropagation()}
                        placeholder="Type your answer"
                        className="flex-1 bg-transparent text-foreground text-sm outline-none placeholder:text-[hsl(var(--placeholder))]"
                    />
                ) : (
                    'Other'
                )}
            </button>
        </div>
    );
}

/** Compute overlay for a node from earlier wizard steps' answers — credentials
 * and config field values picked in prior steps for the same node get merged
 * into the snapshot so the next step's DynamicOptionsField can actually load
 * (e.g., picking a credential in step 1 lets step 2's spreadsheet picker load
 * the user's spreadsheets; picking a spreadsheet in step 2 lets step 3's
 * sheet_name picker load the tabs inside it). */
function getOverridesForNode(
    nodeId: string,
    upToStep: number,
    inputs: InputRequest[],
    values: Record<string, string>
): { credentialIds: Record<string, string>; nodeConfig: Record<string, any> } {
    const credentialIds: Record<string, string> = {};
    const nodeConfig: Record<string, any> = {};
    for (let i = 0; i < upToStep; i++) {
        const inp = inputs[i];
        const val = values[inp.id];
        if (!val || inp.nodeId !== nodeId) continue;
        if (inp.type === 'credential' && inp.credentialType) {
            credentialIds[inp.credentialType] = val;
        } else if (inp.type === 'config' && inp.fieldKey) {
            nodeConfig[inp.fieldKey] = val;
        }
    }
    return { credentialIds, nodeConfig };
}

/** Field-bound config ask — merges the backend's snapshot with overrides from
 * earlier wizard steps so dependent pickers (depends_on, credential-loaded
 * options) work end-to-end within a single wizard. Routes to the right widget
 * based on the field's JSON schema. */
function FieldBoundConfigInput({
    input,
    value,
    onChange,
    overrides,
}: {
    input: InputRequest;
    value: string | undefined;
    onChange: (value: string) => void;
    overrides: { credentialIds: Record<string, string>; nodeConfig: Record<string, any> };
}) {
    const credentialIds = { ...(input.credentialIds || {}), ...overrides.credentialIds };
    const config = { ...(input.nodeConfig || {}), ...overrides.nodeConfig };

    const schema = input.fieldSchema || {};
    const hasDynamicOptions = !!schema['x-dynamic-options'];
    const enumValues = schema.enum as (string | number)[] | undefined;
    const enumNames = schema.enumNames as string[] | undefined;

    // DynamicOptionsField calls onChange with both the field key and a separate
    // `${fieldKey}__label` key for label persistence on the actual node config.
    // The drawer doesn't write back to the node (the brain applies the answer
    // via <field> in its next turn), so we ignore the label writes.
    const handleDynamicChange = useCallback((key: string, val: string) => {
        if (key === input.fieldKey) onChange(val);
    }, [input.fieldKey, onChange]);

    if (hasDynamicOptions && input.fieldKey && input.nodeType) {
        return (
            <DynamicOptionsField
                fieldKey={input.fieldKey}
                prop={schema}
                value={value || ''}
                onChange={handleDynamicChange}
                nodeType={input.nodeType}
                credentialIds={credentialIds}
                config={config}
            />
        );
    }

    if (enumValues && enumValues.length > 0) {
        const options = enumValues.map((v, i) => ({
            id: String(v),
            label: String(enumNames?.[i] ?? v),
        }));
        return <SelectionInput options={options} value={value} onChange={onChange} />;
    }

    return (
        <input
            type="text"
            value={value || ''}
            onChange={e => onChange(e.target.value)}
            onClick={e => e.stopPropagation()}
            placeholder={schema['ui:placeholder'] || `Enter ${input.fieldKey || 'value'}...`}
            className="w-full px-3 py-2 rounded-lg border border-border dark:border-white/[0.08] bg-foreground/[0.03] text-foreground text-sm outline-none placeholder:text-[hsl(var(--placeholder))] focus:border-foreground/20 focus:bg-foreground/[0.05]"
        />
    );
}

/** Renders the input body based on type — no card wrapper, shown inline in the step view */
function InputBody({
    input,
    value,
    onChange,
    credentialIds,
    onCredentialIdsChange,
    overrides,
}: {
    input: InputRequest;
    value: string | undefined;
    onChange: (value: string) => void;
    /** Full credentialIds record for NodeCredentials (controlled component) */
    credentialIds?: Record<string, string>;
    onCredentialIdsChange?: (ids: Record<string, string>) => void;
    overrides: { credentialIds: Record<string, string>; nodeConfig: Record<string, any> };
}) {
    return (
        <div role="presentation" onClick={e => e.stopPropagation()} onKeyDown={e => e.stopPropagation()}>
            {input.type === 'credential' && input.nodeType && (
                <NodeCredentials
                    nodeType={input.nodeType}
                    // Config-sensitive credential forms (agent: harness/sub-model
                    // pick the fields; mcp-server: server_url) read the node's
                    // config snapshot off the request.
                    nodeData={{ config: { ...(input.nodeConfig || {}), ...overrides.nodeConfig } }}
                    credentialIds={credentialIds}
                    onChange={(newIds) => {
                        onCredentialIdsChange?.(newIds);
                        const firstId = Object.values(newIds).find(id => id && id.trim());
                        if (firstId) onChange(firstId);
                    }}
                    compact
                />
            )}

            {input.type === 'selection' && input.options && (
                <SelectionInput options={input.options} value={value} onChange={onChange} multiple={input.multiple} />
            )}

            {input.type === 'config' && (
                <FieldBoundConfigInput input={input} value={value} onChange={onChange} overrides={overrides} />
            )}

            {input.type === 'text' && (
                <input
                    type="text"
                    value={value || ''}
                    onChange={e => onChange(e.target.value)}
                    onClick={e => e.stopPropagation()}
                    placeholder={input.fieldSchema?.['ui:placeholder'] || 'Enter value...'}
                    className="w-full px-3 py-2 rounded-lg border border-border dark:border-white/[0.08] bg-foreground/[0.03] text-foreground text-sm outline-none placeholder:text-[hsl(var(--placeholder))] focus:border-foreground/20 focus:bg-foreground/[0.05]"
                />
            )}

            {input.type === 'env' && (
                <EnvInput input={input} value={value} onChange={onChange} />
            )}
        </div>
    );
}

/** Env-var request body — reuses the SAME AgentEnvVarsSection the agent config
 *  panel uses (picker + create-with-add-vars + prefill), so the two surfaces are
 *  identical. It writes to a credentialIds map; here that map is local and the
 *  attached agent_env id becomes the ask answer. */
function EnvInput({
    input,
    value,
    onChange,
}: {
    input: InputRequest;
    value: string | undefined;
    onChange: (value: string) => void;
}) {
    // AgentEnvVarsSection is credentialIds-controlled; keep a local map and lift
    // the attached agent_env id out as the answer.
    const [credentialIds, setCredentialIds] = useState<Record<string, string>>(
        value ? { [AGENT_ENV_CREDENTIAL_TYPE]: value } : {},
    );
    return (
        <AgentEnvVarsSection
            credentialIds={credentialIds}
            onCredentialIdsChange={ids => {
                setCredentialIds(ids);
                onChange(ids[AGENT_ENV_CREDENTIAL_TYPE] || '');
            }}
            requestedEnvVars={input.envKeys}
        />
    );
}

// ============================================================================
// Main Drawer — step-by-step wizard
// ============================================================================

export function BuilderInputDrawer({ inputs, title, onSubmit, onDismiss, onSubmitMessage, onValuesChange, onShare, embedded = false }: BuilderInputDrawerProps) {
    // Seed initial values from each input's defaultValue (e.g., when drafter
    // extracted a real value from the user's prompt — the user just confirms
    // instead of picking from scratch).
    const [values, setValues] = useState<Record<string, string>>(() => {
        const initial: Record<string, string> = {};
        for (const inp of inputs) {
            if (inp.defaultValue) {
                initial[inp.id] = inp.defaultValue;
            } else if (inp.type === 'credential' && inp.credentialIds) {
                // A credential already selected on the node arrives via the
                // credentialIds snapshot, not defaultValue — and NodeCredentials
                // won't re-fire onChange for it. Seed values here (mirroring the
                // onChange firstId pick) so the step counts as answered and
                // Continue enables without the user re-picking.
                const preselected = Object.values(inp.credentialIds).find(id => id && id.trim());
                if (preselected) initial[inp.id] = preselected;
            }
        }
        return initial;
    });
    const [step, setStep] = useState(0);
    // Track full credentialIds per input (NodeCredentials is a controlled component)
    const [credentialIdsMap, setCredentialIdsMap] = useState<Record<string, Record<string, string>>>({});

    const handleChange = useCallback((inputId: string, value: string) => {
        setValues(prev => ({ ...prev, [inputId]: value }));
    }, []);

    const current = inputs[step];
    const isLast = step === inputs.length - 1;
    const currentValue = current ? values[current.id] : undefined;
    const currentRequired = current ? isRequired(current) : false;
    const currentOverrides = useMemo(
        () => current ? getOverridesForNode(current.nodeId, step, inputs, values) : { credentialIds: {}, nodeConfig: {} },
        [current, step, inputs, values],
    );
    const isFilled = (v: string | undefined) => {
        if (!v) return false;
        if (v.startsWith(MULTI_PREFIX)) return !!flattenMultiValue(v);
        if (v.startsWith(OTHER_PREFIX)) return v.length > OTHER_PREFIX.length;
        return !!v.trim();
    };
    const canAdvance = !currentRequired || isFilled(currentValue);

    // Mirror the in-progress answers to the bridge so a free-form chatbox reply
    // mid-wizard carries the partially-filled form alongside the typed message.
    useEffect(() => {
        onValuesChange?.(cleanValues(values));
    }, [values, onValuesChange]);

    const handleNext = () => {
        if (isLast) {
            onSubmit(cleanValues(values));
        } else {
            setStep(s => s + 1);
        }
    };

    const handleBack = () => {
        if (step > 0) setStep(s => s - 1);
    };

    // Skip the current question. Mid-wizard this just advances to the next step
    // (the current answer is left empty). On the last step it's terminal: submit
    // whatever was answered so far, but if the user skipped every question,
    // dismiss instead so the brain gets the explicit "user declined" signal
    // rather than a confusing empty answer list (which can trigger a re-ask).
    const handleSkip = () => {
        if (!isLast) {
            setStep(s => s + 1);
            return;
        }
        const anyFilled = inputs.some(inp => isFilled(values[inp.id]));
        if (anyFilled) handleNext();
        else onDismiss?.();
    };

    if (!current) return null;

    // An embedded host already shows the title, so a question whose label
    // repeats it is not labelled a second time.
    const showLabel = !embedded || (!!current.label && current.label !== title);

    return (
        <div className={cn('flex flex-col', !embedded && 'h-full')}>
            {/* Header — the drawer's own; an embedded host renders its own. */}
            {!embedded && <div className="px-4 pt-4 pb-2 shrink-0">
                {/* Title row */}
                <div className="flex items-center justify-between">
                    <div className="flex items-center gap-1.5 min-w-0">
                        <h3 className="text-sm font-semibold text-foreground truncate">
                            {title || 'Setup Required'}
                        </h3>
                        {onShare && <ShareAskButton onShare={onShare} />}
                    </div>
                    <div className="flex items-center gap-3">
                        {step > 0 && (
                            <button
                                onClick={handleBack}
                                className="flex items-center gap-0.5 text-xs text-muted-foreground dark:text-zinc-500 hover:text-foreground transition-colors"
                            >
                                <ChevronLeft className="w-3.5 h-3.5" />
                                Back
                            </button>
                        )}
                        {onDismiss && (
                            <button
                                onClick={handleSkip}
                                className="text-xs text-muted-foreground dark:text-zinc-500 hover:text-foreground transition-colors"
                            >
                                Skip
                            </button>
                        )}
                    </div>
                </div>
                {/* Step dots row */}
                <div className="flex items-center gap-1.5 mt-2">
                    {inputs.map((input, i) => (
                        <div
                            key={input.id}
                            className={cn(
                                "w-1.5 h-1.5 rounded-full transition-all",
                                i === step
                                    ? "bg-foreground w-3"
                                    : isFilled(values[input.id])
                                        ? "bg-emerald-500"
                                        : "bg-muted-foreground/50 dark:bg-zinc-600"
                            )}
                        />
                    ))}
                    <span className="text-xs text-muted-foreground dark:text-zinc-500 ml-1">
                        Step {step + 1} of {inputs.length}
                    </span>
                </div>
            </div>}

            {/* Current input — scrollable, takes remaining space */}
            <div className={cn('flex-1 min-h-0 overflow-y-auto scrollbar-subtle', !embedded && 'px-4 py-3')}>
                {/* Label + description */}
                {(showLabel || current.description) && (
                    <div className="mb-3">
                        {showLabel && (
                            <div className="flex items-center gap-2">
                                <span className="text-[13px] font-medium text-foreground">
                                    {current.label}
                                    {currentRequired && <span className="text-red-600 dark:text-red-400 ml-1">*</span>}
                                </span>
                                {isFilled(currentValue) && (
                                    <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500 shrink-0" />
                                )}
                            </div>
                        )}
                        {current.description && (
                            <p className={cn('text-xs text-muted-foreground', showLabel && 'mt-1')}>{current.description}</p>
                        )}
                    </div>
                )}

                {/* Input body — keyed by input id so step changes remount the
                 *  widget tree. Without this, components like
                 *  DynamicOptionsField are reused positionally across steps
                 *  and leak internal state (e.g. step 1's loaded spreadsheet
                 *  options show up under step 2's Slack-channel picker). */}
                <InputBody
                    key={current.id}
                    input={current}
                    value={currentValue}
                    onChange={v => handleChange(current.id, v)}
                    credentialIds={{
                        ...(current.credentialIds || {}),
                        ...(credentialIdsMap[current.id] || {}),
                    }}
                    onCredentialIdsChange={ids =>
                        setCredentialIdsMap(prev => ({ ...prev, [current.id]: ids }))
                    }
                    overrides={currentOverrides}
                />

                {/* Field affordance — alternative answer that delegates to the
                 *  agent (e.g. "Create new spreadsheet"). Only rendered for
                 *  fields registered in FIELD_AFFORDANCES. */}
                {(() => {
                    const affordance = getFieldAffordance(current);
                    if (!affordance || !onSubmitMessage) return null;
                    return (
                        <div className="mt-3">
                            <div className="flex items-center gap-2 my-2 text-[11px] text-muted-foreground dark:text-zinc-500">
                                <div className="flex-1 h-px bg-foreground/[0.06]" />
                                <span>or</span>
                                <div className="flex-1 h-px bg-foreground/[0.06]" />
                            </div>
                            <button
                                onClick={e => { e.stopPropagation(); onSubmitMessage(affordance.message); }}
                                className="w-full flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg border border-border dark:border-white/[0.08] bg-foreground/[0.02] text-sm text-foreground/80 hover:bg-foreground/[0.05] hover:border-foreground/[0.15] transition-all"
                            >
                                <Plus className="w-3.5 h-3.5" />
                                {affordance.label}
                            </button>
                        </div>
                    );
                })()}
            </div>

            {/* Footer — always visible at bottom */}
            {embedded ? (
                <div className="mt-5 flex items-center gap-4">
                    {step > 0 && (
                        <button
                            type="button"
                            onClick={handleBack}
                            className="inline-flex items-center gap-0.5 text-[12.5px] text-foreground/70 dark:text-foreground/50 transition-colors hover:text-foreground"
                        >
                            <ChevronLeft className="h-3.5 w-3.5" />
                            Back
                        </button>
                    )}
                    {inputs.length > 1 && (
                        <span className="text-[11.5px] tabular-nums text-foreground/60 dark:text-foreground/40">
                            {step + 1} of {inputs.length}
                        </span>
                    )}
                    <span className="ml-auto flex items-center gap-4">
                        {onShare && <ShareAskButton onShare={onShare} label="Copy link" />}
                        {onDismiss && (
                            <button type="button" onClick={handleSkip} className="text-[12.5px] text-foreground/70 dark:text-foreground/50 transition-colors hover:text-foreground">
                                Skip
                            </button>
                        )}
                        <button
                            type="button"
                            onClick={handleNext}
                            disabled={!canAdvance}
                            className={cn(
                                'inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[12.5px] font-medium transition-colors',
                                canAdvance ? 'bg-primary text-primary-foreground hover:bg-primary/90' : 'cursor-not-allowed bg-foreground/10 text-foreground/60 dark:text-foreground/40'
                            )}
                        >
                            {isLast ? 'Continue' : 'Next'}
                            <ArrowRight className="h-3.5 w-3.5" />
                        </button>
                    </span>
                </div>
            ) : (
                <div className="px-4 py-3 border-t border-border dark:border-foreground/[0.06] flex items-center gap-2 shrink-0">
                    <button
                        onClick={handleNext}
                        disabled={!canAdvance}
                        className={cn(
                            "flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium transition-all",
                            canAdvance
                                ? "bg-primary text-primary-foreground hover:bg-primary/90 cursor-pointer"
                                : "bg-foreground/10 text-foreground/60 dark:text-foreground/40 cursor-not-allowed"
                        )}
                    >
                        {isLast ? 'Continue' : 'Next'}
                        <ArrowRight className="w-4 h-4" />
                    </button>
                </div>
            )}
        </div>
    );
}
