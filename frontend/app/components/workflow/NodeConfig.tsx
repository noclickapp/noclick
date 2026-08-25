// NodeConfig component handles auto-generating configuration UI from JSON Schema.
// It validates both on the frontend (instant feedback with AJV) and backend (security).

import { useEffect, useState, useCallback, useRef, useMemo, type ReactNode, type JSX } from 'react';
import Ajv2020 from 'ajv/dist/2020';
import { useAnalytics } from '~/lib/analytics';
import { EVENTS } from '~/lib/analytics-events';
import addFormats from 'ajv-formats';
import { CheckCircle2, AlertCircle, Braces, Loader2, ChevronDown, ChevronRight, ArrowUpRight, Sparkles, Repeat2 } from 'lucide-react';
import { hasListReference } from '~/lib/listReferences';
import { sendEventAsync } from '~/lib/socket-sender';
import { useDebounce } from '~/hooks/useDebounce';
import type { WorkflowNodeValidateConfigResponse } from '~/types/socket-events.generated';
import { WorkflowNodeValidateConfigRequest } from '~/types/socket-events.generated';
import { DynamicOptionsField } from './DynamicOptionsField';
import { DroppableTextField, getInsertReferenceForField } from './DroppableTextField';
import { useReferenceAutocomplete } from './ReferenceAutocompleteContext';
import { OperationPicker } from './OperationPicker';
import { getNodeMetadata } from './nodes/nodeRegistry';
import { SearchableEnumField } from './SearchableEnumField';
import { MultiSelectEnumField } from './MultiSelectEnumField';
import { renderSchemaWidget } from './schemaWidgetRegistry';
import { getOptionDisplayName } from '~/utils/operationHelpers';
import { NODE_SCHEMAS } from '~/utils/nodeSchemas';
import { BANNER_PULSE_CYCLES, pulseElement } from '~/lib/pulseHighlight';
import { hasUnconnectedCredentials } from './NodeCredentials';
import { useAgentCredentialsRequired } from '~/hooks/useAgentCredentialsRequired';
import { CopyLinkButton } from '~/components/ui/CopyLinkButton';
import { buildNodeDeepLink } from '~/utils/workflowNavigation';
import { getRequireOneOfGroups } from '~/utils/schemaFieldExtractor';
import { evaluateRequireOneOf, describeRequireOneOfGroup } from '~/utils/workflowNodeValidation';
import { NodeSettings } from './NodeSettings';
import { FieldRequirementBadge, isFieldFilled } from './FieldRequirementBadge';

// Initialize AJV for frontend validation (Draft 2020-12)
// IMPORTANT: Use Ajv2020 class for draft-2020-12 schemas
const ajv = new Ajv2020({
    allErrors: true,
    strict: false,  // Allow non-standard keywords like "ui:widget"
    validateFormats: true,  // Enable format validation (email, uri, etc.)
    coerceTypes: true,  // Coerce strings to booleans/numbers (e.g., "true" -> true)
});
addFormats(ajv);

/** The amber "complete required fields" callout.
 *
 *  Pulses on mount and whenever it starts describing a different node, so it
 *  registers however the user arrived: clicking the node on the canvas, opening
 *  the panel, or stepping here with the IncompleteNodeNavigator arrows. Driving
 *  it off the banner's own lifecycle rather than the navigator means there is
 *  one mechanism instead of two, and no guessing about when the panel has
 *  finished mounting.
 *
 *  `nodeId` is the effect key, not decoration — the element survives a change
 *  of selected node, so keying on it is what makes the arrows re-pulse. */
function IncompleteConfigBanner({
    nodeId,
    children,
}: {
    nodeId?: string;
    children: React.ReactNode;
}) {
    const ref = useRef<HTMLDivElement>(null);
    useEffect(() => {
        if (ref.current) pulseElement(ref.current, { cycles: BANNER_PULSE_CYCLES });
    }, [nodeId]);

    return (
        <div
            ref={ref}
            data-incomplete-banner={nodeId ?? ''}
            className="px-3 py-2.5 rounded-lg bg-amber-100 border border-amber-300 dark:bg-amber-500/15 dark:border-amber-400/40"
        >
            {children}
        </div>
    );
}

/** Scrolls to a config field by key and pulses its control region. Returns
 *  false when the field isn't in the DOM (e.g. inside a collapsed section).
 *  The pulse targets [data-field-control] — not the whole field block — so it
 *  doesn't ring the label, which looks bad for tall controls like a code editor. */
function highlightConfigField(fieldKey: string, opts?: { focus?: boolean }): boolean {
    const fieldElement = document.querySelector(`[data-field-key="${fieldKey}"]`) ??
        document.getElementById(`field-${fieldKey}`);
    if (!fieldElement) return false;
    fieldElement.scrollIntoView({ behavior: 'smooth', block: 'center' });
    pulseElement(fieldElement.querySelector('[data-field-control]') ?? fieldElement);
    if (opts?.focus) {
        const input = fieldElement.querySelector('input, textarea, select');
        if (input instanceof HTMLElement) setTimeout(() => input.focus(), 300);
    }
    return true;
}

interface NodeConfigProps{
    nodeType: string;
    config: Record<string, any>;
    onChange: (config: Record<string, any>, sourceNodeId?: string) => void;  // sourceNodeId prevents race conditions when switching nodes
    /** Inject an iteration node to loop a scalar field's list ([]) reference over each item. */
    onInjectIteration?: (nodeId: string, fieldKey: string) => void;
    /** True if the field value is a plain `{{node.path}}` ref that resolves to an
     *  array (the non-`[]` case). Computed by the parent, which has node outputs. */
    fieldHoldsArrayRef?: (value: unknown) => boolean;
    /** Current operation (top-level node attribute, NOT part of config) */
    operation?: string;
    /** Callback when user changes operation via the selector */
    onOperationChange?: (operation: string) => void;
    onValidationChange?: (valid: boolean) => void;
    onSwitchToCredentials?: () => void;  // Callback to switch to credentials tab
    credentialIds?: Record<string, string>;  // Maps credential_type -> credential_id for dynamic options
    workflowId?: string;  // Required for loading dynamic values (e.g., webhook URL)
    nodeId?: string;  // Required for loading dynamic values
    fieldErrors?: Record<string, string[]>;  // Maps field paths to error messages (from execution errors)
    // Lifted state — when provided, the parent controls the Configuration/Settings toggle
    activeView?: 'configuration' | 'settings';
    onActiveViewChange?: (view: 'configuration' | 'settings') => void;
    // Lifted validation state — lets parent render the badge elsewhere in the UI
    onValidationStateChange?: (state: { validating: boolean; valid: boolean }) => void;
    // AI single-field autofill — wired to useCanvasWorkflowEdit.startAutofill
    onAutofillField?: (fieldKey: string) => void;
    // AI operation-only autofill — wired to startAutofill(node, 'operation')
    onAutofillOperation?: () => void;
    // True while any AI edit/autofill is streaming — disables per-field buttons
    isAutofilling?: boolean;
    // Field currently being autofilled (spins its sparkle, leaves others static)
    autofillingFieldKey?: string | null;
    // True when the active autofill is the operation picker (spins its sparkle)
    isAutofillingOperation?: boolean;
    /** Auto-focus the operation picker's search when it opens. False during
     *  keyboard node-traversal so the picker doesn't trap arrow navigation. */
    autoFocusOperationPicker?: boolean;
    showInputPrompt?: boolean;
    onShowInputPrompt?: () => void;
    showOutputPrompt?: boolean;
    onShowOutputPrompt?: () => void;
    /** Extra content rendered directly under a named schema field (key →
     *  node), e.g. the agent's trigger chips under `message`. Stays visible
     *  when the field is collapsed. */
    fieldAddons?: Record<string, ReactNode>;
    /** Render only the selected operation's fields — no OperationPicker. Used
     *  by hosts that own the operation choice (AgentWiringPalette's trigger
     *  config step), so the embedded form can't switch operations. */
    hideOperationPicker?: boolean;
    /** Render ONLY these config fields, and no validation banner: the host is
     *  a focused fix-it surface (the Setup tab's step) that already names the
     *  problem, so filled and irrelevant fields are noise there. Empty array =
     *  no fields (e.g. while the host is asking for the operation). */
    focusFields?: string[];
    /** Resolved workflow variables — with onVariableValueChange, a field whose
     *  whole value is {{vars.x}} renders the RESOLVED value and its editor
     *  writes through the variable, keeping the binding intact. */
    workflowVariables?: Record<string, any>;
    onVariableValueChange?: (name: string, value: string) => void;
}

interface ValidationError {
    message: string;
    fieldKey?: string;      // For field-related errors, the field key to scroll to
    fieldLabel?: string;    // Human-readable field name
    type: 'field' | 'credentials' | 'general';
}

interface ValidationResult {
    valid: boolean;
    errors: ValidationError[];
}

/**
 * Evaluate a ui:show-if condition against the current config.
 * Supports:
 *   { anyOf: [...] }         — passes if ANY sub-condition passes (OR compound)
 *   { field, contains }      — single substring match
 *   { field, containsAny }   — match ANY of the substrings (OR)
 *   { field, containsAll }   — match ALL of the substrings (AND) — pattern-based, future-proof
 *   { field, notContains }   — AND the field must NOT contain this string
 */
function evaluateShowIf(showIf: any, config: Record<string, any>): boolean {
    if (showIf.anyOf) {
        return (showIf.anyOf as any[]).some(sub => evaluateShowIf(sub, config));
    }
    const condVal = String(config[showIf.field] ?? '').toLowerCase();
    let passes: boolean;
    if (showIf.containsAny) {
        passes = (showIf.containsAny as string[]).some(s => condVal.includes(s.toLowerCase()));
    } else if (showIf.containsAll) {
        passes = (showIf.containsAll as string[]).every(s => condVal.includes(s.toLowerCase()));
    } else if (showIf.contains) {
        passes = condVal.includes(showIf.contains.toLowerCase());
    } else {
        return false;
    }
    if (!passes) return false;
    if (showIf.notContains) {
        if (condVal.includes((showIf.notContains as string).toLowerCase())) return false;
    }
    return true;
}

// Helper to detect discriminator field in anyOf options
// Returns the field name and mapping of const values to option indices
function detectDiscriminator(options: any[], resolveRef: (ref: string) => any): {
    fieldName: string | null;
    valueToOptionIndex: Map<string, number>;
    optionToValue: Map<number, string>;
} {
    const result = {
        fieldName: null as string | null,
        valueToOptionIndex: new Map<string, number>(),
        optionToValue: new Map<number, string>()
    };

    if (options.length < 2) return result;

    // Find fields with const values that exist in all options
    const firstOption = options[0].$ref ? resolveRef(options[0].$ref) : options[0];
    const firstProps = firstOption?.properties || {};

    for (const [fieldName, fieldProp] of Object.entries(firstProps) as [string, any][]) {
        // Check if this field has a const value
        const constValue = fieldProp?.const;
        if (!constValue) continue;

        // Check if all other options also have this field with const values
        let isDiscriminator = true;
        const values = new Map<string, number>();
        values.set(constValue, 0);

        for (let i = 1; i < options.length; i++) {
            const option = options[i].$ref ? resolveRef(options[i].$ref) : options[i];
            const prop = option?.properties?.[fieldName];
            if (!prop?.const) {
                isDiscriminator = false;
                break;
            }
            values.set(prop.const, i);
        }

        if (isDiscriminator && values.size === options.length) {
            result.fieldName = fieldName;
            result.valueToOptionIndex = values;
            // Create reverse mapping
            values.forEach((idx, val) => result.optionToValue.set(idx, val));
            break;
        }
    }

    return result;
}

export function NodeConfig({ nodeType, config, onChange, onInjectIteration, fieldHoldsArrayRef, operation: operationProp, onOperationChange, onValidationChange, onSwitchToCredentials, credentialIds = {}, workflowId, nodeId, fieldErrors = {}, activeView: propActiveView, onActiveViewChange, onValidationStateChange, onAutofillField, onAutofillOperation, isAutofilling, autofillingFieldKey, isAutofillingOperation, autoFocusOperationPicker = true, showInputPrompt = false, onShowInputPrompt, showOutputPrompt = false, onShowOutputPrompt, fieldAddons, hideOperationPicker = false, focusFields, workflowVariables, onVariableValueChange }: NodeConfigProps) {
    const { logActivity } = useAnalytics();
    // Per-field AI Fill button — rendered in every field-label row (regular,
    // collapsible widgets, and nested objects) so users see the same affordance
    // regardless of widget type.
    const renderAutofillButton = (fieldKey: string, fieldTitle?: string) => {
        if (!onAutofillField) return null;
        return (
            <button
                type="button"
                onClick={() => {
                    logActivity(EVENTS.NODE_AUTOFILL_INVOKED, {
                        mode: 'single_field',
                        field_key: fieldKey,
                        node_id: nodeId,
                        node_type: nodeType,
                        workflow_id: workflowId,
                    });
                    onAutofillField(fieldKey);
                }}
                disabled={isAutofilling}
                className="flex items-center gap-1 px-1.5 rounded text-[10px] font-medium bg-transparent text-muted-foreground hover:text-foreground hover:bg-muted dark:hover:bg-foreground/[0.06] border border-border dark:border-white/[0.08] hover:border-foreground/20 transition-colors disabled:cursor-not-allowed leading-[16px] whitespace-nowrap flex-shrink-0"
                title={`Autofill "${fieldTitle || fieldKey}" with AI`}
            >
                {autofillingFieldKey === fieldKey ? (
                    <Loader2 className="h-2.5 w-2.5 animate-spin" />
                ) : (
                    <Sparkles className={`h-2.5 w-2.5 ${isAutofilling ? 'opacity-40' : ''}`} />
                )}
                <span>AI Fill</span>
            </button>
        );
    };
    const [internalActiveView, setInternalActiveView] = useState<'configuration' | 'settings'>('configuration');
    const activeView = propActiveView ?? internalActiveView;
    const setActiveView = onActiveViewChange ?? setInternalActiveView;
    const [localConfig, setLocalConfig] = useState(config);
    const [isLoadingValues, setIsLoadingValues] = useState<Record<string, boolean>>({});
    // Ref to track loading state for guards (avoids callback recreation on state change)
    const isLoadingValuesRef = useRef<Record<string, boolean>>({});
    // Per-field memo of the (operation + credentialIds) key we last fetched
    // for. Gate the auto-load on a content-key change so we don't re-fetch on
    // every render-induced dep change (e.g. parent re-creating the
    // credentialIds object reference). Without this, ui:loadValue fields
    // re-fire at React render cadence, which thrashes server-side
    // subscription writes for app-fanout triggers like Slack/HubSpot.
    const lastFetchKeyRef = useRef<Record<string, string>>({});
    const [frontendValidation, setFrontendValidation] = useState<ValidationResult>({ valid: true, errors: [] });
    // Track collapsed state for collapsible sections (function_inputs, python_editor, nested objects)
    const [collapsedSections, setCollapsedSections] = useState<Record<string, boolean>>({});
    const [backendValidation, setBackendValidation] = useState<ValidationResult | null>(null);
    const [isValidatingBackend, setIsValidatingBackend] = useState(false);
    const [selectedOptionIndex, setSelectedOptionIndex] = useState<number>(0);
    const [focusedFieldKey, setFocusedFieldKey] = useState<string | null>(null);
    // Present inside a workflow (FlowHelperView wraps NodeConfig in the provider); null
    // elsewhere. Gates the "Add reference" affordance — only fields that can hold a
    // reference get it.
    const refAutocomplete = useReferenceAutocomplete();

    // Either-or ("require one of") constraints for the active operation. Drives
    // the amber "needs attention" badge on fields whose group isn't satisfied,
    // before the user runs and hits the backend guard.
    const requireOneOfGroups = useMemo(
        () => getRequireOneOfGroups(nodeType, selectedOptionIndex),
        [nodeType, selectedOptionIndex],
    );
    const requireOneOfAttention = useMemo(
        () => evaluateRequireOneOf(requireOneOfGroups, localConfig).attentionKeys,
        [requireOneOfGroups, localConfig],
    );
    // Picker is open by default for nodes that haven't picked an operation yet;
    // for nodes loading with an operation already set, we start in the compact
    // closed state (the user can hit "Change" to reopen).
    const [pickerOpenState, setPickerOpen] = useState<boolean>(!operationProp);
    // With the picker hidden the field area must never yield to it.
    const pickerOpen = pickerOpenState && !hideOperationPicker;

    // Debounce config for backend validation (300ms)
    const debouncedConfig = useDebounce(localConfig, 300);

    const agentCredentialsCheck = useAgentCredentialsRequired(
        nodeType === 'agent' ? (config?.model as string | undefined) : undefined,
        nodeType === 'agent' ? credentialIds : {},
        nodeType === 'agent' ? config : undefined
    );

    const rootSchema = NODE_SCHEMAS[nodeType];

    // Extract config schema from root schema
    // Root schema now has structure: { properties: { config: {...}, credentials: {...} } }
    // We need to extract the config sub-schema for rendering
    const schema = rootSchema?.properties?.config || rootSchema;

    // Frontend validation (instant) - validates only fields for the currently selected operation
    // This is handled later in the component after selectedOptionIndex is determined,
    // see the "Operation-aware frontend validation" useEffect below

    // Backend validation (debounced, security layer)
    useEffect(() => {
        const validateWithBackend = async () => {
            if (!schema) return;

            setIsValidatingBackend(true);
            try {
                const response = await sendEventAsync(
                    WorkflowNodeValidateConfigRequest.create({
                        node_type: nodeType,
                        config_data: debouncedConfig
                    })
                ) as WorkflowNodeValidateConfigResponse;

                if (response) {
                    setBackendValidation({
                        valid: response.valid,
                        errors: (response.errors || []).map(err => ({
                            message: err,
                            type: 'general' as const,
                        })),
                    });
                }
            } catch (error) {
                console.error('Backend validation error:', error);
                setBackendValidation({ valid: false, errors: [{ message: 'Validation service unavailable', type: 'general' }] });
            } finally {
                setIsValidatingBackend(false);
            }
        };

        validateWithBackend();
    }, [debouncedConfig, nodeType, schema]);

    // Notify parent of validation status
    useEffect(() => {
        // Use frontend validation for immediate feedback, backend is security layer
        if (onValidationChange) {
            onValidationChange(frontendValidation.valid);
        }
    }, [frontendValidation.valid, onValidationChange]);

    // Sync with external config changes (only on mount or when external config meaningfully changes)
    useEffect(() => {
        // Only update if config is actually different (deep comparison would be better, but this prevents most loops)
        const configString = JSON.stringify(config);
        const localConfigString = JSON.stringify(localConfig);
        if (configString !== localConfigString) {
            setLocalConfig(config);
        }
    }, [config]); // localConfig intentionally not in deps to avoid loops

    // Ref to track pending timeout for debounced parent notification
    const pendingUpdateRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    // Track config identity to detect node changes (clear pending updates from old node)
    const prevConfigRef = useRef<string | null>(null);

    // Clear pending timeout when node changes (detected by config prop reference change)
    // This prevents race conditions where old timeouts fire with stale closures
    useEffect(() => {
        const configId = JSON.stringify(config);
        if (prevConfigRef.current !== null && prevConfigRef.current !== configId) {
            // Config changed (different node selected) - cancel any pending updates from old node
            if (pendingUpdateRef.current) {
                clearTimeout(pendingUpdateRef.current);
                pendingUpdateRef.current = null;
            }
        }
        prevConfigRef.current = configId;

        // Cleanup on unmount
        return () => {
            if (pendingUpdateRef.current) {
                clearTimeout(pendingUpdateRef.current);
            }
        };
    }, [config]);

    // Reset to configuration view when the selected node changes
    useEffect(() => {
        setActiveView('configuration');
    }, [nodeId]);

    useEffect(() => {
        setFocusedFieldKey(null);
    }, [nodeId]);

    // Emit validation state to parent whenever it changes (for badge rendering in parent UI)
    useEffect(() => {
        onValidationStateChange?.({ validating: isValidatingBackend, valid: frontendValidation.valid });
    }, [isValidatingBackend, frontendValidation.valid, onValidationStateChange]);

    // Listen for deep-link field scroll events — scrolls to and highlights a specific config field
    useEffect(() => {
        const handleScrollToField = (event: CustomEvent<{ fieldKey: string }>) => {
            const { fieldKey } = event.detail;
            if (highlightConfigField(fieldKey)) return;
            // Field might be inside a collapsed section — expand it and retry.
            setCollapsedSections(prev => {
                // fieldKey may be nested (e.g. "hardware.gpu_type") — check the parent too.
                const parentKey = fieldKey.includes('.') ? fieldKey.split('.')[0] : fieldKey;
                if (prev[parentKey] !== true && prev[fieldKey] !== true) return prev;
                const updated = { ...prev };
                if (updated[parentKey] === true) updated[parentKey] = false;
                if (updated[fieldKey] === true) updated[fieldKey] = false;
                setTimeout(() => highlightConfigField(fieldKey), 100);
                return updated;
            });
        };

        document.addEventListener('noclick:field:scroll-to', handleScrollToField as EventListener);
        return () => {
            document.removeEventListener('noclick:field:scroll-to', handleScrollToField as EventListener);
        };
    }, []);

    // Update local config and notify parent
    // Uses functional update + debouncing to handle rapid successive updates
    // IMPORTANT: Captures config value and nodeId at schedule time to avoid race conditions
    const handleFieldChange = useCallback((key: string, value: any) => {
        setLocalConfig(prev => {
            const newConfig = { ...prev, [key]: value };

            // Debounce parent notification - only fires once after all rapid updates
            // Capture newConfig and nodeId directly (not via ref) to ensure correct data is sent
            // nodeId is captured here to prevent race conditions when switching nodes
            const capturedNodeId = nodeId;
            if (pendingUpdateRef.current) {
                clearTimeout(pendingUpdateRef.current);
            }
            pendingUpdateRef.current = setTimeout(() => {
                pendingUpdateRef.current = null;
                onChange(newConfig, capturedNodeId);
            }, 0);

            return newConfig;
        });
    }, [onChange, nodeId]);

    // Refetch a field's value from backend (used when widgets like NextRunWidget need fresh data)
    const handleFieldRefetch = useCallback(async (fieldName: string) => {
        if (!workflowId || !nodeId) return;

        // Prevent rapid refetches - skip if already loading this field (use ref to avoid callback recreation)
        if (isLoadingValuesRef.current[fieldName]) {
            console.debug(`[NodeConfig] Skipping refetch for ${fieldName} - already loading`);
            return;
        }

        // Update both ref (for guards) and state (for UI)
        isLoadingValuesRef.current[fieldName] = true;
        setIsLoadingValues(prev => ({ ...prev, [fieldName]: true }));
        try {
            const response = await sendEventAsync({
                event_name: 'workflow:node:load_value',
                node_type: nodeType,
                field_name: fieldName,
                workflow_id: workflowId,
                node_id: nodeId,
                // operation is a top-level node attribute, not part of config —
                // merge it in so operation-aware loaders (e.g. per-event
                // triggers) can resolve it from context.
                context: { ...localConfig, operation: operationProp },
            }) as { success: boolean; values?: Record<string, any>; message?: string };

            if (response?.success && response.values) {
                // Use functional update to avoid race conditions
                // Capture nodeId to prevent race conditions when switching nodes
                const capturedNodeId = nodeId;
                setLocalConfig(prev => {
                    const newConfig = { ...prev, ...response.values };
                    setTimeout(() => onChange(newConfig, capturedNodeId), 0);
                    return newConfig;
                });
            }
        } catch (error) {
            console.error(`Error refetching ${fieldName}:`, error);
        } finally {
            isLoadingValuesRef.current[fieldName] = false;
            setIsLoadingValues(prev => ({ ...prev, [fieldName]: false }));
        }
    }, [workflowId, nodeId, nodeType, localConfig, onChange]);

    // Resolve $refs from root schema's $defs (safe even when schema is null)
    const resolveRef = useCallback((ref: string) => {
        const path = ref.replace('#/$defs/', '');
        return rootSchema?.$defs?.[path] || rootSchema?.definitions?.[path] || schema?.$defs?.[path] || schema?.definitions?.[path];
    }, [rootSchema, schema]);

    // Extract config sub-schema first (schema structure is { properties: { config: {...} } })
    // Then resolve $ref if present (matches approach in schemaFieldRenderer.tsx)
    const configSchema = schema?.properties?.config || schema;
    const resolvedSchema = configSchema?.$ref ? resolveRef(configSchema.$ref) : configSchema;

    // Handle both oneOf and anyOf (Pydantic generates anyOf for Union types)
    const oneOfOptions = resolvedSchema?.oneOf || resolvedSchema?.anyOf || [];
    const hasOneOf = oneOfOptions.length > 0;

    // Detect discriminator field (e.g., "operation" with const values like "read", "write", "append")
    const discriminator = hasOneOf ? detectDiscriminator(oneOfOptions, resolveRef) : {
        fieldName: null,
        valueToOptionIndex: new Map(),
        optionToValue: new Map()
    };
    const hasDiscriminator = discriminator.fieldName !== null;

    // If every variant opts in via `x-flatten-union: true` at the class level, the schema
    // author wants the union treated as an implementation detail — no OperationPicker UI,
    // and all variant fields merged into one flat view so `ui:show-if` clauses on individual
    // fields drive visibility. Used by AgentNode where model_type is inferred from the model
    // string, not picked by the user. We deliberately do NOT key this off `ui:hidden` on the
    // discriminator field, because normal multi-op nodes also hide their const discriminator
    // inside each variant (the OperationPicker already represents it).
    const discriminatorHidden = hasDiscriminator && oneOfOptions.every((option: any) => {
        const resolved = option.$ref ? resolveRef(option.$ref) : option;
        return resolved?.['x-flatten-union'] === true;
    });

    // Hide operations incompatible with the selected credential type.
    // Operations declare supported credential types via "x-supported-credential-types" on the discriminator field.
    // If an operation has this array, it's only shown when a matching credential is selected.
    // Operations without the array are shown for all credential types (backward compatible).
    const hiddenOperationIndices = useMemo(() => {
        const hidden = new Set<number>();
        if (!hasDiscriminator) return hidden;

        // Get the set of selected credential types
        const selectedCredTypes = new Set(
            Object.entries(credentialIds)
                .filter(([_, id]) => id && id.trim() !== '')
                .map(([type]) => type)
        );
        if (selectedCredTypes.size === 0) return hidden;

        // Check if ANY operation has x-supported-credential-types — if none do, skip filtering entirely
        let anyRestricted = false;
        const operationRestrictions: (string[] | null)[] = oneOfOptions.map((option: any) => {
            const resolved = option.$ref ? resolveRef(option.$ref) : option;
            const operationProp = resolved?.properties?.[discriminator.fieldName!];
            const supported: string[] | undefined = operationProp?.['x-supported-credential-types'];
            if (supported) anyRestricted = true;
            return supported || null;
        });
        if (!anyRestricted) return hidden;

        operationRestrictions.forEach((supported, idx) => {
            if (!supported) return; // No restriction — always visible
            // Hide if none of the selected credential types are in the supported list
            const isCompatible = supported.some(type => selectedCredTypes.has(type));
            if (!isCompatible) hidden.add(idx);
        });
        return hidden;
    }, [oneOfOptions, credentialIds, hasDiscriminator, discriminator.fieldName, resolveRef]);

    // Sync selectedOptionIndex from the operation prop (top-level node attribute).
    // Operation is NOT part of config — it's set by node drafter or the OperationPicker.
    useEffect(() => {
        if (hasDiscriminator && operationProp && discriminator.valueToOptionIndex.has(operationProp)) {
            const optionIdx = discriminator.valueToOptionIndex.get(operationProp)!;
            if (optionIdx !== selectedOptionIndex) {
                setSelectedOptionIndex(optionIdx);
            }
        }
    }, [hasDiscriminator, operationProp, discriminator.valueToOptionIndex]);

    // Populate schema defaults for conditionally-visible fields (ui:show-if)
    // Only applies defaults for fields that have never been set (undefined in config).
    // Uses a ref to track which fields have been initialized to avoid re-applying defaults
    // after user intentionally clears a field.
    const initializedShowIfFields = useRef<Set<string>>(new Set());
    useEffect(() => {
        const properties = resolvedSchema?.properties;
        if (!properties) return;
        const updates: Record<string, any> = {};
        for (const [key, prop] of Object.entries(properties) as [string, any][]) {
            const showIf = prop['ui:show-if'];
            if (!showIf || prop.default === undefined) continue;
            if (initializedShowIfFields.current.has(key)) continue;
            const isVisible = evaluateShowIf(showIf, localConfig);
            if (isVisible && localConfig[key] === undefined) {
                updates[key] = prop.default;
                initializedShowIfFields.current.add(key);
            }
        }
        if (Object.keys(updates).length > 0) {
            const newConfig = { ...localConfig, ...updates };
            setLocalConfig(newConfig);
            onChange(newConfig, nodeId);
        }
    }, [resolvedSchema, localConfig, nodeId]);

    // Handle operation change from the OperationPicker.
    // Writes to node.data.operation (top-level), NOT to config.
    const handleOptionChange = useCallback((optionIndex: number) => {
        setSelectedOptionIndex(optionIndex);

        if (hasDiscriminator) {
            const operationValue = discriminator.optionToValue.get(optionIndex);
            if (operationValue && onOperationChange) {
                onOperationChange(operationValue);
            }
        }
    }, [hasDiscriminator, discriminator, onOperationChange]);

    // Load dynamic values for fields with ui:loadValue
    // This is operation-aware: only loads values for fields in the currently selected operation schema
    // This allows nodes like Telegram to have webhook URLs only for specific operations (e.g., "receive_message")
    useEffect(() => {
        if (!resolvedSchema || !workflowId || !nodeId) return;

        // Find all fields with ui:loadValue in the CURRENT active schema
        // This respects anyOf/oneOf discriminators - different operations can have different fields
        const loadValueFields: string[] = [];

        // Resolve the active option from the COMMITTED operation, not from
        // selectedOptionIndex: on first mount that state is still 0 (its sync
        // effect lands a render later), which pointed this effect at option 0's
        // schema and fired its ui:loadValue side effects (webhook + cron
        // provisioning) for nodes set to a different operation. And with no
        // operation picked yet, load nothing — provisioning must never run
        // against a default schema.
        let effectiveOptionIndex = selectedOptionIndex;
        if (hasDiscriminator) {
            if (!operationProp) return;
            const committedIdx = discriminator.valueToOptionIndex.get(operationProp);
            if (committedIdx === undefined) return;
            effectiveOptionIndex = committedIdx;
        }

        // Determine the active schema based on oneOf/anyOf and the effective option
        let activeSchema = resolvedSchema;
        if (hasOneOf && oneOfOptions.length > effectiveOptionIndex) {
            const selectedOption = oneOfOptions[effectiveOptionIndex];
            if (selectedOption?.$ref) {
                activeSchema = resolveRef(selectedOption.$ref) || resolvedSchema;
            } else if (selectedOption) {
                activeSchema = selectedOption;
            }
        }

        const properties = activeSchema?.properties || {};

        for (const [fieldName, fieldProp] of Object.entries(properties) as [string, any][]) {
            if (fieldProp['ui:loadValue'] === true) {
                loadValueFields.push(fieldName);
            }
        }

        if (loadValueFields.length === 0) return;

        // Required-field completeness of the active operation ('operation' is
        // top-level, not config). Folded into webhook_url's fetch key so the
        // provisioning loader re-fires when completeness flips. This is a UX
        // head start, NOT the correctness mechanism: registration converges
        // server-side via WebhookManager.reconcile_node from every save/change
        // surface — the re-fire just registers ahead of the autosave and pulls
        // fresh mirrors (next_run, trigger_registered/_error) into the panel
        // immediately instead of on the next open.
        const requiredOk = ((activeSchema?.required as string[] | undefined) || [])
            .filter(f => f !== 'operation')
            .every(f => {
                const v = (localConfig as Record<string, any>)[f];
                return v !== undefined && v !== null && v !== '';
            });

        // Capture nodeId at effect start to prevent race conditions when switching nodes
        const capturedNodeId = nodeId;

        // Load values for each field in the current operation
        loadValueFields.forEach(async (fieldName) => {
            // Skip if already loading (use ref to avoid stale closure issues)
            if (isLoadingValuesRef.current[fieldName]) return;
            // Re-load only when the content that the value depends on actually
            // changed — operation pick + credentialId selection. Object
            // identity of credentialIds changes per render (parent re-creates
            // the literal), so gating on a stringified content-key avoids the
            // 2-second reload thrash that would otherwise churn server-side
            // subscription writes. (Previous heuristic — "skip if non-trigger-*
            // node already has a value" — left app-fanout triggers like
            // Slack/HubSpot stuck on the initial "Unknown trigger operation:
            // None" response forever after the user picked an operation.)
            const credKey = Object.entries(credentialIds || {})
                .filter(([, v]) => v)
                .map(([k, v]) => `${k}=${v}`)
                .sort()
                .join('|');
            // webhook_url additionally re-fetches on required-completeness
            // flips (see requiredOk above); other loadValue fields keep the
            // operation+credential key so config typing never re-fires them.
            const fetchKey = fieldName === 'webhook_url'
                ? `${operationProp ?? ''}::${credKey}::req=${requiredOk}`
                : `${operationProp ?? ''}::${credKey}`;
            if (lastFetchKeyRef.current[fieldName] === fetchKey) return;
            lastFetchKeyRef.current[fieldName] = fetchKey;

            // Update both ref and state
            isLoadingValuesRef.current[fieldName] = true;
            setIsLoadingValues(prev => ({ ...prev, [fieldName]: true }));

            try {
                const response = await sendEventAsync({
                    event_name: 'workflow:node:load_value',
                    node_type: nodeType,
                    field_name: fieldName,
                    workflow_id: workflowId,
                    node_id: capturedNodeId,
                    // operation is a top-level node attribute, not part of config —
                    // merge it in so operation-aware loaders (per-event triggers,
                    // schedule-aware fields) can resolve it from context.
                    context: { ...localConfig, operation: operationProp },
                    // Pass credential IDs for nodes that need API calls during value loading (e.g., Telegram setWebhook)
                    credential_ids: credentialIds,
                }) as { success: boolean; value?: any; values?: Record<string, any>; message?: string };

                if (response?.success) {
                    if (response.values) {
                        // Multiple values returned - update all of them in config
                        // Use functional update to avoid race conditions
                        setLocalConfig(prev => {
                            const newConfig = { ...prev, ...response.values };
                            setTimeout(() => onChange(newConfig, capturedNodeId), 0);
                            return newConfig;
                        });
                    } else if (response.value !== undefined) {
                        // Single value returned
                        // Use functional update to avoid race conditions
                        setLocalConfig(prev => {
                            const newConfig = { ...prev, [fieldName]: response.value };
                            setTimeout(() => onChange(newConfig, capturedNodeId), 0);
                            return newConfig;
                        });
                    }
                } else {
                    console.warn(`Failed to load value for ${fieldName}:`, response?.message);
                }
            } catch (error) {
                console.error(`Error loading value for ${fieldName}:`, error);
            } finally {
                isLoadingValuesRef.current[fieldName] = false;
                setIsLoadingValues(prev => ({ ...prev, [fieldName]: false }));
            }
        });
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [resolvedSchema, workflowId, nodeId, nodeType, selectedOptionIndex, hasOneOf, hasDiscriminator, operationProp, discriminator.valueToOptionIndex, credentialIds, localConfig]); // Re-run when operation, credentials, or config (required-completeness) change

    // Track previous schedule for comparison (nodes with schedule + webhook)
    const prevScheduleRef = useRef<string | null>(null);

    // Re-trigger schedule update when schedule changes (for any node with a schedule widget)
    // This ensures the external schedule is updated when user modifies the schedule
    // Applies to trigger-cron, automation-gmail (trigger), and any future scheduled nodes
    useEffect(() => {
        const hasSchedule = localConfig.schedule !== undefined || localConfig.schedules !== undefined;
        if (!hasSchedule || !workflowId || !nodeId) return;

        const currentSchedule = JSON.stringify(localConfig.schedules || localConfig.schedule || {});
        const prevSchedule = prevScheduleRef.current;

        // Skip if schedule hasn't changed or this is the initial mount
        if (prevSchedule === null) {
            prevScheduleRef.current = currentSchedule;
            return;
        }

        if (currentSchedule === prevSchedule) return;

        prevScheduleRef.current = currentSchedule;

        // Skip if already loading webhook_url (initial load in progress) - prevents duplicate schedule creation
        if (isLoadingValuesRef.current['webhook_url']) {
            console.debug('[NodeConfig] Skipping schedule update - initial load in progress');
            return;
        }

        // Capture nodeId at effect start to prevent race conditions when switching nodes
        const capturedNodeId = nodeId;

        // Schedule changed - update the external schedule via load_field_value
        const updateSchedule = async () => {
            isLoadingValuesRef.current['webhook_url'] = true;
            setIsLoadingValues(prev => ({ ...prev, webhook_url: true }));

            try {
                const response = await sendEventAsync({
                    event_name: 'workflow:node:load_value',
                    node_type: nodeType,
                    field_name: 'webhook_url',
                    workflow_id: workflowId,
                    node_id: capturedNodeId,
                    // operation merged like the main loader: the backend's
                    // registration validity gate judges the config against the
                    // operation's schema (no operation = gate can't judge).
                    context: { ...localConfig, operation: operationProp },
                }) as { success: boolean; values?: Record<string, any>; message?: string };

                if (response?.success && response.values) {
                    // Update config with new next_run, schedule_id, etc.
                    // Use functional update to avoid race conditions with user typing
                    setLocalConfig(prev => {
                        const newConfig = { ...prev, ...response.values };
                        setTimeout(() => onChange(newConfig, capturedNodeId), 0);
                        return newConfig;
                    });
                } else {
                    console.warn('Failed to update cron schedule:', response?.message);
                }
            } catch (error) {
                console.error('Error updating cron schedule:', error);
            } finally {
                isLoadingValuesRef.current['webhook_url'] = false;
                setIsLoadingValues(prev => ({ ...prev, webhook_url: false }));
            }
        };

        // Debounce the update to avoid too many requests while user is adjusting
        const timeoutId = setTimeout(updateSchedule, 500);
        return () => clearTimeout(timeoutId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [localConfig.schedules, localConfig.schedule, workflowId, nodeId, nodeType, operationProp]);

    // Defer placeholder return until after all hooks fire (Rules of Hooks).
    let earlyReturn: JSX.Element | null = null;
    if (!schema) {
        earlyReturn = (
            <div className="p-4 text-center text-muted-foreground dark:text-zinc-500 text-sm">
                This node type does not have configurable options.
            </div>
        );
    } else if (!resolvedSchema) {
        earlyReturn = (
            <div className="p-4 text-center text-red-500 text-sm">
                Failed to resolve schema reference for node type: {nodeType}
            </div>
        );
    }

    // Get fields for the currently selected option only (when using discriminator)
    // Otherwise, extract all fields from all options
    const getFieldsForCurrentOption = (): Map<string, { prop: any; required: boolean }> => {
        const fields = new Map<string, { prop: any; required: boolean }>();
        const resolveFieldProp = (prop: any) => {
            if (!prop?.$ref) return prop;
            const resolved = resolveRef(prop.$ref);
            return resolved ? { ...resolved, ...prop } : prop;
        };

        if (hasOneOf) {
            if (hasDiscriminator && !discriminatorHidden) {
                // Clamp because selectedOptionIndex is sticky across node switches.
                const safeIndex = Math.min(Math.max(0, selectedOptionIndex), oneOfOptions.length - 1);
                const option = oneOfOptions[safeIndex];
                const resolved = option?.$ref ? resolveRef(option.$ref) : option;
                const props = resolved?.properties || {};
                const requiredFields = resolved?.required || [];

                Object.entries(props).forEach(([key, prop]: [string, any]) => {
                    // Skip hidden discriminator fields
                    if (key === discriminator.fieldName && prop['ui:hidden']) {
                        return;
                    }
                    fields.set(key, {
                        prop: resolveFieldProp(prop),
                        required: requiredFields.includes(key)
                    });
                });
            } else {
                // No visible discriminator - merge fields from all variants. `ui:show-if`
                // clauses on individual fields control visibility (pre-refactor Agent UX).
                // Required-ness is OR'd across variants to match the validator merge
                // below — otherwise the per-field badge can say Optional while the
                // alert bar says the same field is required.
                oneOfOptions.forEach((option: any) => {
                    const resolved = option.$ref ? resolveRef(option.$ref) : option;
                    const props = resolved?.properties || {};
                    const requiredFields = resolved?.required || [];

                    Object.entries(props).forEach(([key, prop]: [string, any]) => {
                        // Skip hidden discriminator fields (e.g. model_type on AgentConfig).
                        if (key === discriminator.fieldName && prop?.['ui:hidden']) {
                            return;
                        }
                        const isRequiredHere = requiredFields.includes(key);
                        const existing = fields.get(key);
                        if (!existing) {
                            fields.set(key, { prop: resolveFieldProp(prop), required: isRequiredHere });
                        } else if (isRequiredHere && !existing.required) {
                            fields.set(key, { ...existing, required: true });
                        }
                    });
                });
            }
        } else {
            // No oneOf, use direct properties
            const properties = resolvedSchema?.properties || {};
            const required = resolvedSchema?.required || [];
            Object.entries(properties).forEach(([key, prop]) => {
                fields.set(key, {
                    prop: resolveFieldProp(prop),
                    required: required.includes(key)
                });
            });
        }

        return fields;
    };

    const currentFields = getFieldsForCurrentOption();

    // Operation-aware frontend validation (instant)
    // Only validates fields that are relevant to the currently selected operation
    useEffect(() => {
        if (!schema || !resolvedSchema) {
            setFrontendValidation({ valid: false, errors: [{ message: 'No schema found for this node type', type: 'general' }] });
            return;
        }

        // Get the active schema for the selected operation
        // Start with resolvedSchema (handles $ref resolution) instead of raw schema
        let activeSchema = resolvedSchema;
        const oneOfOpts = resolvedSchema?.oneOf || resolvedSchema?.anyOf || [];

        if (discriminatorHidden && oneOfOpts.length > 0) {
            // Merge all variants' fields so validation matches the flattened UI.
            const mergedProps: Record<string, any> = {};
            const mergedRequired: string[] = [];
            oneOfOpts.forEach((option: any) => {
                const resolved = option.$ref ? resolveRef(option.$ref) : option;
                Object.entries(resolved?.properties || {}).forEach(([k, v]) => {
                    if (!(k in mergedProps)) mergedProps[k] = v;
                });
                (resolved?.required || []).forEach((f: string) => {
                    if (!mergedRequired.includes(f)) mergedRequired.push(f);
                });
            });
            activeSchema = { ...resolvedSchema, properties: mergedProps, required: mergedRequired };
        } else if (oneOfOpts.length > 0 && selectedOptionIndex < oneOfOpts.length) {
            const selectedOption = oneOfOpts[selectedOptionIndex];
            if (selectedOption?.$ref) {
                // Resolve $ref
                const refPath = selectedOption.$ref.replace('#/$defs/', '').replace('#/definitions/', '');
                const defs = rootSchema?.$defs || rootSchema?.definitions || schema.$defs || schema.definitions || {};
                activeSchema = defs[refPath] || resolvedSchema;
            } else if (selectedOption) {
                activeSchema = selectedOption;
            }
        }

        // Build validation schema for the active operation only
        // Exclude fields hidden by ui:show-if conditions
        const allProperties = activeSchema?.properties || {};
        const visibleProperties: Record<string, any> = {};
        const allRequired = activeSchema?.required || [];
        for (const [key, prop] of Object.entries(allProperties) as [string, any][]) {
            const showIf = prop['ui:show-if'];
            if (showIf) {
                if (!evaluateShowIf(showIf, localConfig)) {
                    continue; // skip hidden fields
                }
            }
            visibleProperties[key] = prop;
        }
        const visibleRequired = allRequired.filter((f: string) => f in visibleProperties);

        const validationSchema = {
            type: 'object',
            properties: visibleProperties,
            required: visibleRequired,
            $defs: rootSchema?.$defs || schema.$defs || {},
            definitions: rootSchema?.definitions || schema.definitions || {}
        };

        // Preprocess config: parse JSON string values for fields that expect arrays
        // (e.g., person_titles: "[\"CEO\",\"Owner\"]" → ["CEO","Owner"]). For
        // ui:widget="list" fields, also coerce plain/comma-separated strings to
        // arrays so the banner doesn't flag a populated single recipient as
        // invalid — the list widget shows that string as one item, so validation
        // must agree.
        const preprocessed = { ...localConfig };
        for (const [key, prop] of Object.entries(visibleProperties) as [string, any][]) {
            const val = preprocessed[key];
            if (typeof val !== 'string') continue;
            // A reference/expression ({{ ... }}) resolves server-side; don't split or
            // coerce it (a comma inside `$('x').split(',')` isn't a list separator).
            if (val.includes('{{')) continue;
            const options = prop.anyOf || prop.oneOf || (prop.type === 'array' ? [prop] : []);
            const expectsArray = options.some((opt: any) => opt.type === 'array');
            if (!expectsArray) continue;
            if (val.startsWith('[')) {
                try { preprocessed[key] = JSON.parse(val); } catch { /* leave as-is */ }
            } else if (prop['ui:widget'] === 'list' && val.trim()) {
                preprocessed[key] = val.split(',').map((s: string) => s.trim()).filter(Boolean);
            }
        }

        const validate = ajv.compile(validationSchema);
        const ajvValid = validate(preprocessed);

        const validationErrors: ValidationError[] = [];
        const fieldsWithErrors = new Set<string>(); // Track fields already reported

        // Collect AJV validation errors
        if (!ajvValid) {
            // Filter out sub-errors from anyOf/oneOf branches — only keep the parent error
            // e.g., for anyOf: [{type: "array"}, {type: "null"}], AJV produces:
            //   1. type error for array branch (schemaPath: .../anyOf/0/type)
            //   2. type error for null branch (schemaPath: .../anyOf/1/type)
            //   3. parent anyOf error (schemaPath: .../anyOf)
            // We only want #3 to avoid duplicate rows per field
            const filteredErrors = (validate.errors || []).filter(err =>
                !err.schemaPath || !/\/(anyOf|oneOf)\/\d+/.test(err.schemaPath)
            );
            // Helper: extract top-level field name from instancePath (e.g., "/foo/0/bar" → "foo")
            const rootField = (path: string | undefined) => path?.replace(/^\//, '').split('/')[0] || '';

            for (const err of filteredErrors) {
                // A field holding a reference/expression ({{ ... }}) is resolved
                // server-side; its type/format/enum is only knowable after resolution,
                // so don't flag it as invalid here.
                const errField = err.keyword === 'required'
                    ? err.params?.missingProperty
                    : rootField(err.instancePath);
                const rawVal = errField ? localConfig[errField] : undefined;
                if (typeof rawVal === 'string' && rawVal.includes('{{')) continue;
                if (err.keyword === 'anyOf' || err.keyword === 'oneOf') {
                    const field = rootField(err.instancePath);
                    if (field && !fieldsWithErrors.has(field)) {
                        fieldsWithErrors.add(field);
                        const fieldSchema = activeSchema?.properties?.[field];
                        const label = fieldSchema?.title || field;
                        const options = fieldSchema?.anyOf || fieldSchema?.oneOf || [];
                        const expectedTypes = options
                            .map((opt: any) => opt.type)
                            .filter((t: string) => t && t !== 'null');
                        const message = expectedTypes.length > 0
                            ? `must be ${expectedTypes.join(' or ')}`
                            : 'has invalid value';
                        validationErrors.push({
                            message,
                            fieldKey: field,
                            fieldLabel: label,
                            type: 'field',
                        });
                    }
                    continue;
                }
                if (err.keyword === 'required') {
                    const missing = err.params.missingProperty;
                    if (fieldsWithErrors.has(missing)) continue;
                    fieldsWithErrors.add(missing);
                    const fieldSchema = activeSchema?.properties?.[missing];
                    const label = fieldSchema?.title || missing;
                    validationErrors.push({
                        message: 'is required',
                        fieldKey: missing,
                        fieldLabel: label,
                        type: 'field',
                    });
                } else if (err.keyword === 'minLength') {
                    const field = rootField(err.instancePath) || 'field';
                    if (fieldsWithErrors.has(field)) continue;
                    fieldsWithErrors.add(field);
                    const fieldSchema = activeSchema?.properties?.[field];
                    const label = fieldSchema?.title || field;
                    validationErrors.push({
                        message: 'is required',
                        fieldKey: field,
                        fieldLabel: label,
                        type: 'field',
                    });
                } else if (err.keyword === 'pattern') {
                    const field = rootField(err.instancePath) || 'field';
                    if (fieldsWithErrors.has(field)) continue;
                    fieldsWithErrors.add(field);
                    const fieldSchema = activeSchema?.properties?.[field];
                    const label = fieldSchema?.title || field;
                    validationErrors.push({
                        message: 'has invalid format',
                        fieldKey: field,
                        fieldLabel: label,
                        type: 'field',
                    });
                } else if (err.keyword === 'type') {
                    const field = rootField(err.instancePath) || 'field';
                    if (fieldsWithErrors.has(field)) continue;
                    // Empty string on a number/integer field means "use backend default" — not an error
                    if ((err.params?.type === 'integer' || err.params?.type === 'number') && localConfig[field] === '') {
                        continue;
                    }
                    fieldsWithErrors.add(field);
                    const fieldSchema = activeSchema?.properties?.[field];
                    const label = fieldSchema?.title || field;
                    const expectedType = err.params?.type || 'correct type';
                    validationErrors.push({
                        message: `must be ${expectedType}`,
                        fieldKey: field,
                        fieldLabel: label,
                        type: 'field',
                    });
                } else if (err.keyword === 'enum') {
                    const field = rootField(err.instancePath);
                    if (field) {
                        if (fieldsWithErrors.has(field)) continue;
                        fieldsWithErrors.add(field);
                        const fieldSchema = activeSchema?.properties?.[field];
                        const label = fieldSchema?.title || field;
                        // Get allowed values from err.params or the field's items schema
                        const allowed: string[] = err.params?.allowedValues
                            || fieldSchema?.items?.enum
                            || fieldSchema?.enum
                            || [];
                        const MAX_SHOWN = 8;
                        let message: string;
                        if (allowed.length === 0) {
                            message = 'has invalid value';
                        } else if (allowed.length <= MAX_SHOWN) {
                            message = `must be one of: ${allowed.join(', ')}`;
                        } else {
                            message = `must be one of: ${allowed.slice(0, MAX_SHOWN).join(', ')} (+${allowed.length - MAX_SHOWN} more)`;
                        }
                        validationErrors.push({
                            message,
                            fieldKey: field,
                            fieldLabel: label,
                            type: 'field',
                        });
                    }
                } else {
                    const field = rootField(err.instancePath);
                    if (field) {
                        if (fieldsWithErrors.has(field)) continue;
                        fieldsWithErrors.add(field);
                        const fieldSchema = activeSchema?.properties?.[field];
                        const label = fieldSchema?.title || field;
                        validationErrors.push({
                            message: err.message || 'has invalid value',
                            fieldKey: field,
                            fieldLabel: label,
                            type: 'field',
                        });
                    } else {
                        validationErrors.push({
                            message: err.message || 'Invalid value',
                            type: 'general',
                        });
                    }
                }
            }
        }

        // Additional check: required string fields that are empty
        // AJV's "required" only checks if property exists, not if it's non-empty
        // Use visibleRequired/visibleProperties to skip hidden fields
        for (const fieldName of visibleRequired) {
            // Skip if AJV already reported this field
            if (fieldsWithErrors.has(fieldName)) continue;

            const fieldSchema = visibleProperties[fieldName];
            // Check string fields that are empty (AJV doesn't catch this)
            if (fieldSchema?.type === 'string' && !fieldSchema?.default) {
                const value = localConfig[fieldName];
                if (value === undefined || value === null || (typeof value === 'string' && value.trim() === '')) {
                    const label = fieldSchema.title || fieldName;
                    validationErrors.push({
                        message: 'is required',
                        fieldKey: fieldName,
                        fieldLabel: label,
                        type: 'field',
                    });
                }
            }
        }

        // Either-or constraints: flag any group with no satisfied alternative.
        const oneOfGroups = activeSchema?.['x-require-one-of'];
        if (Array.isArray(oneOfGroups) && oneOfGroups.length > 0) {
            const titleOf = (k: string) => activeSchema?.properties?.[k]?.title || k;
            const { unsatisfiedGroups } = evaluateRequireOneOf(oneOfGroups, localConfig);
            for (const group of unsatisfiedGroups) {
                const firstKey = group[0]?.[0];
                if (firstKey) fieldsWithErrors.add(firstKey);
                validationErrors.push({
                    message: `Provide ${describeRequireOneOfGroup(group, titleOf)}`,
                    fieldKey: firstKey,
                    fieldLabel: firstKey ? titleOf(firstKey) : undefined,
                    type: 'field',
                });
            }
        }

        setFrontendValidation({
            valid: validationErrors.length === 0,
            errors: validationErrors,
        });
    }, [localConfig, schema, resolvedSchema, rootSchema, nodeType, selectedOptionIndex]);

    // Fire an analytics event when validation first transitions from valid → invalid with a
    // new set of field keys. Signature uses (type, fieldKey) only — never the error message,
    // since messages may echo user config values.
    const lastErrorSignatureRef = useRef<string>('');
    const prevValidRef = useRef<boolean>(true);
    // Reset dedupe when switching to a different node so we don't suppress legitimate new events.
    useEffect(() => {
        lastErrorSignatureRef.current = '';
        prevValidRef.current = true;
    }, [nodeId]);
    useEffect(() => {
        const { valid, errors } = frontendValidation;
        if (valid || errors.length === 0) {
            prevValidRef.current = true;
            return;
        }
        const signature = errors
            .map(e => `${e.type}:${(e as { fieldKey?: string }).fieldKey || ''}`)
            .sort()
            .join('|');
        const wasValid = prevValidRef.current;
        prevValidRef.current = false;
        if (!wasValid && signature === lastErrorSignatureRef.current) return;
        lastErrorSignatureRef.current = signature;
        logActivity(EVENTS.NODE_CONFIG_ERROR_SHOWN, {
            node_id: nodeId,
            node_type: nodeType,
            workflow_id: workflowId,
            error_count: errors.length,
            error_types: Array.from(new Set(errors.map(e => e.type))),
        });
    }, [frontendValidation, logActivity, nodeId, nodeType, workflowId]);

    // Get option labels for the selector — delegate to the shared helper so
    // every surface rendering operations always shows identical names.
    const getOptionLabel = (optionIndex: number): string =>
        getOptionDisplayName({ options: oneOfOptions, discriminator, resolveRef }, optionIndex);

    // Get tier requirement label for operations (e.g., "⭐ Basic", "⭐⭐ Pro")
    const getOptionTierLabel = (optionIndex: number): string | null => {
        const option = oneOfOptions[optionIndex];
        const resolved = option.$ref ? resolveRef(option.$ref) : option;
        // Instagram: a handful of ops (hashtag search, business discovery,
        // product tagging) only work on the Facebook-Login connection, not the
        // Instagram-Login one. When an Instagram-Login credential is attached,
        // badge them so the requirement is visible before running — the backend
        // also returns a clear error as a backstop for non-UI call paths.
        // `x-requires-login` lives on the discriminator (operation) field, like
        // x-category — read it there, not from the config-class top level.
        const opField = hasDiscriminator && discriminator.fieldName
            ? resolved?.properties?.[discriminator.fieldName]
            : undefined;
        const requiresLogin = opField?.['x-requires-login'] ?? resolved?.['x-requires-login'];
        if (requiresLogin === 'facebook' && credentialIds?.['instagram_login']) {
            return 'Facebook Login';
        }
        return resolved?.['x-tier-label'] || null;
    };

    // Get the object category an operation acts on (e.g., "Message", "Channel"),
    // stamped on the discriminator field by the op-rename refactor. Falls back
    // to a legacy top-level `x-category` for any node that hasn't been migrated.
    const getOptionCategory = (optionIndex: number): string | null => {
        const option = oneOfOptions[optionIndex];
        const resolved = option.$ref ? resolveRef(option.$ref) : option;
        if (hasDiscriminator && discriminator.fieldName) {
            const opField = resolved?.properties?.[discriminator.fieldName];
            if (opField?.['x-category']) return opField['x-category'];
        }
        return resolved?.['x-category'] || null;
    };

    // True iff this operation starts a workflow on an external event (webhook
    // receive, pub/sub subscribe, scheduled poll). From `x-is-trigger` on the
    // discriminator field.
    const getOptionIsTrigger = (optionIndex: number): boolean => {
        const option = oneOfOptions[optionIndex];
        const resolved = option.$ref ? resolveRef(option.$ref) : option;
        if (hasDiscriminator && discriminator.fieldName) {
            return Boolean(resolved?.properties?.[discriminator.fieldName]?.['x-is-trigger']);
        }
        return false;
    };

    // Extra identity text the OperationPicker fuzzy-matches alongside the label:
    // the raw discriminator value (e.g. "send_message" → "send message"), the
    // schema title, and author-supplied `x-keywords` search synonyms, so intent
    // queries that share no words with the label still find the right action
    // (e.g. "get rows" → "Read Sheet Data"). `x-keywords` lives on the operation
    // field (like x-category) and may be a string or a list of phrases; a legacy
    // top-level fallback covers any unmigrated node.
    const getOptionKeywords = (optionIndex: number): string => {
        const option = oneOfOptions[optionIndex];
        const resolved = option.$ref ? resolveRef(option.$ref) : option;
        const parts: string[] = [];
        const value = discriminator.optionToValue.get(optionIndex);
        if (value) parts.push(value.replace(/[_-]+/g, ' '));
        if (resolved?.title) parts.push(resolved.title);
        const opField =
            hasDiscriminator && discriminator.fieldName
                ? resolved?.properties?.[discriminator.fieldName]
                : undefined;
        const keywords = opField?.['x-keywords'] ?? resolved?.['x-keywords'];
        if (keywords) parts.push(Array.isArray(keywords) ? keywords.join(' ') : keywords);
        return parts.join(' ');
    };

    // Operation description — searched at low weight so a query can hit synonyms
    // that only appear in prose (e.g. "remove" matching a "Delete" action).
    const getOptionDescription = (optionIndex: number): string => {
        const option = oneOfOptions[optionIndex];
        const resolved = option.$ref ? resolveRef(option.$ref) : option;
        return resolved?.description || '';
    };

    if (earlyReturn) return earlyReturn;

    // Contextual buttons under a focused field, all in ONE low-key row: "Add
    // reference" (insert a `{{ $('') }}` expression + open the builder), jump to the
    // Input panel ("Show previous nodes"), the Output panel ("Show output"), and — when
    // the field references an array — "Loop over each item" (injects an iteration node).
    // Each shown only when relevant.
    const renderFieldPanelPrompts = (
        fieldKey: string,
        fieldProp?: { type?: string; enum?: unknown; 'ui:widget'?: string; 'x-dynamic-options'?: unknown },
        fieldValue?: unknown,
    ) => {
        if (focusedFieldKey !== fieldKey) return null;
        const showInputBtn = Boolean(showInputPrompt && onShowInputPrompt);
        const showOutputBtn = Boolean(showOutputPrompt && onShowOutputPrompt);
        // A scalar field holding a list ([]) ref OR a plain {{node.items}} ref
        // that resolves to an array produces a list value, not a loop — offer to
        // make looping explicit by injecting an iteration node before this node.
        const showLoopBtn = Boolean(
            onInjectIteration && nodeId && fieldProp?.type !== 'array'
            && (hasListReference(fieldValue) || fieldHoldsArrayRef?.(fieldValue)),
        );
        // "Add reference" only for a reference-capable text field: a droppable input is
        // registered for this key (so not an array/widget) AND it isn't an enum,
        // dynamic-options, or non-textarea custom widget. The registry presence is the
        // exact signal that a DroppableTextField is mounted here.
        const insertRef = getInsertReferenceForField(fieldKey);
        const showAddRefBtn = Boolean(
            refAutocomplete && insertRef
            && !fieldProp?.enum
            && !fieldProp?.['x-dynamic-options']
            && (!fieldProp?.['ui:widget'] || fieldProp['ui:widget'] === 'textarea'),
        );
        if (!showInputBtn && !showOutputBtn && !showLoopBtn && !showAddRefBtn) return null;
        const btnClass =
            "inline-flex items-center rounded border border-foreground/[0.06] bg-card dark:bg-foreground/[0.03] px-2 py-0.5 text-[11px] text-muted-foreground dark:text-zinc-500 transition-colors hover:border-foreground/[0.1] hover:bg-muted dark:hover:bg-foreground/[0.06] hover:text-foreground";
        return (
            <div className="mt-2 flex flex-wrap items-center gap-2">
                {showAddRefBtn && insertRef && (
                    <button
                        type="button"
                        onMouseDown={(e) => e.preventDefault()} // keep the field focused so the builder opens
                        onClick={() => insertRef("{{ $('') }}")}
                        className={btnClass}
                        title="Insert a reference / expression"
                    >
                        <span className="mr-1 font-mono text-muted-foreground dark:text-zinc-500">{'{}'}</span>
                        Add reference
                    </button>
                )}
                {showLoopBtn && (
                    <button
                        type="button"
                        onClick={() => { if (onInjectIteration && nodeId) onInjectIteration(nodeId, fieldKey); }}
                        className={btnClass}
                        title="This field references a list. Run this node once per item by inserting an iteration node before it."
                    >
                        <Repeat2 className="mr-1 h-3 w-3 text-purple-600 dark:text-purple-400" />
                        Loop over each item
                    </button>
                )}
                {showInputBtn && (
                    <button type="button" onClick={onShowInputPrompt} className={btnClass}>
                        Show previous nodes
                    </button>
                )}
                {showOutputBtn && (
                    <button type="button" onClick={onShowOutputPrompt} className={btnClass}>
                        Show output
                    </button>
                )}
            </div>
        );
    };

    return (
        <div className="space-y-4">

            {activeView === 'settings' ? (
                <NodeSettings
                    settings={localConfig._settings || {}}
                    onChange={(newSettings) => {
                        const updated = { ...localConfig, _settings: newSettings };
                        setLocalConfig(updated);
                        onChange(updated, nodeId);
                    }}
                />
            ) : (<>

            {/* Incomplete Configuration Banner — shows specific issues with
                clickable field names. Hidden while the operation picker is open
                because the picker fully replaces the field area, and the
                banner's "missing field X" prompts wouldn't have anywhere to
                scroll to. */}
            {!(pickerOpen && hasOneOf && hasDiscriminator && !discriminatorHidden) && (() => {
                // A focused host names the problem itself — the banner would
                // restate the step's own headline.
                if (focusFields) return null;
                // For agent nodes, use the hook result; for others, use hasUnconnectedCredentials
                const missingCredentials = nodeType === 'agent'
                    ? agentCredentialsCheck.credentialsRequired
                    : hasUnconnectedCredentials(nodeType, credentialIds, { operation: operationProp, config });
                const hasConfigErrors = !frontendValidation.valid && frontendValidation.errors.length > 0;

                if (!missingCredentials && !hasConfigErrors) return null;

                return (
                    <IncompleteConfigBanner nodeId={nodeId}>
                        <div className="space-y-1">
                            <div className="flex items-center gap-2">
                                <div className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full bg-amber-400/25 ring-1 ring-amber-500/30 dark:bg-amber-400/15 dark:ring-amber-300/30">
                                    <AlertCircle className="h-3.5 w-3.5 text-amber-600 dark:text-amber-300" />
                                </div>
                                <div className="text-sm font-semibold leading-5 text-amber-900 dark:text-amber-100">
                                    Complete required fields (click below)
                                </div>
                            </div>
                            {missingCredentials && (
                                <p className="pl-8 text-xs leading-4 text-amber-900/90 dark:text-amber-100/90">
                                    {onSwitchToCredentials ? (
                                        <>
                                            <button
                                                onClick={onSwitchToCredentials}
                                                className="inline-flex items-center gap-1 font-semibold text-amber-700 dark:text-amber-50 hover:text-amber-800 dark:hover:text-foreground underline underline-offset-2 transition-colors"
                                            >
                                                Credentials
                                                <ArrowUpRight className="h-3 w-3" />
                                            </button>
                                            {' '}are required
                                        </>
                                    ) : (
                                        'Credentials are required'
                                    )}
                                </p>
                            )}
                            {frontendValidation.errors.map((error, idx) => (
                                <p key={idx} className="pl-8 text-xs leading-4 text-amber-900/90 dark:text-amber-100/90">
                                    {error.type === 'field' && error.fieldKey ? (
                                        <>
                                            <button
                                                onClick={() => highlightConfigField(error.fieldKey!, { focus: true })}
                                                className="inline-flex items-center gap-1 font-semibold text-amber-700 dark:text-amber-50 hover:text-amber-800 dark:hover:text-foreground underline underline-offset-2 transition-colors"
                                            >
                                                {error.fieldLabel}
                                                <ArrowUpRight className="h-3 w-3" />
                                            </button>
                                            {' '}{error.message}
                                        </>
                                    ) : (
                                        error.message
                                    )}
                                </p>
                            ))}
                        </div>
                    </IncompleteConfigBanner>
                );
            })()}

            {/* Operation/Mode Selector (for discriminated unions) */}
            {hasOneOf && hasDiscriminator && !discriminatorHidden && !hideOperationPicker && (
                <OperationPicker
                    key={hiddenOperationIndices.size}
                    options={oneOfOptions}
                    selectedIndex={selectedOptionIndex}
                    onSelect={(idx) => {
                        handleOptionChange(idx);
                        setPickerOpen(false);
                    }}
                    getOptionLabel={getOptionLabel}
                    getOptionTierLabel={getOptionTierLabel}
                    getOptionCategory={getOptionCategory}
                    getOptionIsTrigger={getOptionIsTrigger}
                    getOptionKeywords={getOptionKeywords}
                    getOptionDescription={getOptionDescription}
                    hiddenIndices={hiddenOperationIndices}
                    isOpen={pickerOpen}
                    autoFocusOnOpen={autoFocusOperationPicker}
                    onOpen={() => setPickerOpen(true)}
                    onClose={() => setPickerOpen(false)}
                    hasExplicitSelection={Boolean(operationProp)}
                    NodeIcon={nodeType ? getNodeMetadata(nodeType)?.Icon : undefined}
                    nodeIconColor={nodeType ? getNodeMetadata(nodeType)?.iconColor : undefined}
                    headerAction={onAutofillOperation ? (
                        <button
                            type="button"
                            onClick={() => {
                                logActivity(EVENTS.NODE_AUTOFILL_INVOKED, {
                                    mode: 'operation',
                                    node_id: nodeId,
                                    node_type: nodeType,
                                    workflow_id: workflowId,
                                });
                                onAutofillOperation();
                            }}
                            disabled={isAutofilling}
                            className="flex items-center gap-1 px-1.5 rounded text-[10px] font-medium bg-transparent text-muted-foreground hover:text-foreground hover:bg-muted dark:hover:bg-foreground/[0.06] border border-border dark:border-white/[0.08] hover:border-foreground/20 transition-colors disabled:cursor-not-allowed leading-[18px] whitespace-nowrap flex-shrink-0"
                            title="Pick the best operation with AI"
                        >
                            {isAutofillingOperation ? (
                                <Loader2 className="h-2.5 w-2.5 animate-spin" />
                            ) : (
                                <Sparkles className={`h-2.5 w-2.5 ${isAutofilling ? 'opacity-40' : ''}`} />
                            )}
                            <span>AI Fill</span>
                        </button>
                    ) : undefined}
                />
            )}

            {/* Legacy: Show non-selectable option info for non-discriminated unions */}
            {hasOneOf && !hasDiscriminator && (
                <div className="space-y-2">
                    <div className="text-[11px] text-muted-foreground dark:text-zinc-500 uppercase tracking-wider">
                        Configuration options:
                    </div>
                    <div className="flex flex-wrap gap-2">
                        {oneOfOptions.map((option: any, idx: number) => {
                            const resolved = option.$ref ? resolveRef(option.$ref) : option;
                            const description = resolved?.description || resolved?.title || 'Alternative configuration';
                            return (
                                <div
                                    key={idx}
                                    className="px-3 py-2 rounded-lg bg-foreground/[0.03] border border-border dark:border-white/[0.08]"
                                >
                                    <span className="text-xs text-muted-foreground">{description}</span>
                                </div>
                            );
                        })}
                    </div>
                </div>
            )}

            {/* When the operation picker is in its open state we replace the
                entire field area with the picker — fields and per-operation
                helpers (e.g. ClearStateButton) are hidden until the user
                picks an operation and the picker collapses. */}
            {!(pickerOpen && hasOneOf && hasDiscriminator && !discriminatorHidden) && (<>

            {/* Auto-generated form fields (filtered for selected option) */}
            {Array.from(currentFields.entries()).map(([key, fieldInfo]) => {
                const { prop, required: isRequired } = fieldInfo;
                const value = localConfig[key] || '';

                // Focused hosts render only the fields they came to fix.
                if (focusFields && !focusFields.includes(key)) {
                    return null;
                }

                // Skip fields marked as hidden
                if (prop['ui:hidden']) {
                    return null;
                }

                // Skip fields whose condition is not met
                const showIf = prop['ui:show-if'];
                if (showIf) {
                    if (!evaluateShowIf(showIf, localConfig)) {
                        return null;
                    }
                }

                // Handle nested objects with $ref - expand their fields inline
                // Also handle anyOf with $ref (e.g., Optional[HardwareConfig] generates anyOf with $ref and null)
                let resolvedProp = prop.$ref ? resolveRef(prop.$ref) : prop;
                if (!resolvedProp?.properties && prop.anyOf) {
                    // Find the first non-null option with a $ref
                    const refOption = prop.anyOf.find((opt: any) => opt.$ref);
                    if (refOption) {
                        resolvedProp = resolveRef(refOption.$ref) || resolvedProp;
                    }
                }
                const isNestedObject = resolvedProp?.type === 'object' && resolvedProp?.properties;

                // If the nested object has a ui:widget, render it via the widget registry
                // instead of expanding into sub-fields (e.g., schedule widget)
                if (isNestedObject && (prop['ui:widget'] || resolvedProp['ui:widget'])) {
                    const widgetValue = localConfig[key] ?? resolvedProp.default ?? {};
                    const widgetElement = renderSchemaWidget({
                        fieldKey: key,
                        fieldSchema: { ...resolvedProp, ...prop },
                        value: widgetValue,
                        onChange: (_, v) => handleFieldChange(key, v),
                        isLoading: isLoadingValues[key],
                        config: localConfig,
                        onFieldRefetch: handleFieldRefetch,
                        nodeId,
                        nodeType,
                        workflowId,
                    });
                    if (widgetElement) {
                        return (
                            <div
                                key={key}
                                data-field-key={key}
                                className="space-y-1"
                                onFocusCapture={() => setFocusedFieldKey(key)}
                            >
                                <div className="flex flex-wrap items-center gap-x-1 gap-y-0.5">
                                    <label className="text-xs text-muted-foreground uppercase tracking-wider min-w-0 break-words">
                                        {prop.title || resolvedProp.title || key}
                                    </label>
                                    {workflowId && nodeId && (
                                        <CopyLinkButton
                                            url={buildNodeDeepLink(workflowId, nodeId, key)}
                                            tooltip="Copy link to field"
                                        />
                                    )}
                                </div>
                                <div data-field-control>{widgetElement}</div>
                                {renderFieldPanelPrompts(key, prop)}
                            </div>
                        );
                    }
                }

                if (isNestedObject) {
                    const nestedValue = (localConfig[key] as Record<string, any>) || {};
                    const handleNestedChange = (passedKey: string, newValue: any) => {
                        // Handle label storage separately (DynamicOptionsField stores labels with __label suffix)
                        if (passedKey.endsWith('__label')) {
                            // Store label at top level for DynamicOptionsField to find
                            handleFieldChange(passedKey, newValue);
                        } else {
                            // Extract the actual nested key from the passed key (e.g., "hardware.gpu_type" -> "gpu_type")
                            const actualNestedKey = passedKey.includes('.') ? passedKey.split('.').pop()! : passedKey;
                            handleFieldChange(key, { ...nestedValue, [actualNestedKey]: newValue });
                        }
                    };

                    const isCollapsed = collapsedSections[key] ?? false;
                    const toggleCollapsed = () => setCollapsedSections(prev => ({ ...prev, [key]: !prev[key] }));

                    return (
                        <div key={key} data-field-key={key} className="space-y-2">
                            <div className="flex flex-wrap items-center gap-x-1 gap-y-0.5">
                                <label className="text-xs text-muted-foreground uppercase tracking-wider min-w-0 break-words">
                                    {prop.title || resolvedProp.title || key}
                                </label>
                                {workflowId && nodeId && (
                                    <CopyLinkButton
                                        url={buildNodeDeepLink(workflowId, nodeId, key)}
                                        tooltip="Copy link to field"
                                    />
                                )}
                                <button
                                    type="button"
                                    onClick={toggleCollapsed}
                                    className="p-0.5 rounded hover:bg-foreground/[0.05] text-muted-foreground dark:text-zinc-500 hover:text-foreground/80 transition-colors"
                                    title={isCollapsed ? 'Expand' : 'Collapse'}
                                >
                                    {isCollapsed ? (
                                        <ChevronRight className="w-3.5 h-3.5" />
                                    ) : (
                                        <ChevronDown className="w-3.5 h-3.5" />
                                    )}
                                </button>
                                {renderAutofillButton(key, prop.title || resolvedProp.title)}
                            </div>
                            {!isCollapsed && (
                                <div data-field-control className="space-y-3">
                                    {Object.entries(resolvedProp.properties).map(([nestedKey, nestedProp]: [string, any]) => {
                                        const nestedFieldValue = nestedValue[nestedKey] ?? nestedProp.default ?? '';
                                        return (
                                            <div
                                                key={nestedKey}
                                                onFocusCapture={() => setFocusedFieldKey(`${key}.${nestedKey}`)}
                                            >
                                                <label className="text-[10px] text-muted-foreground dark:text-zinc-500 uppercase tracking-wider">
                                                    {nestedProp.title || nestedKey}
                                                </label>
                                                {nestedProp.description && (
                                                    <div className="text-[11.5px] text-muted-foreground/70 dark:text-zinc-500 mb-1">
                                                        {nestedProp.description}
                                                    </div>
                                                )}
                                                {nestedProp['x-dynamic-options'] ? (
                                                    <DynamicOptionsField
                                                        fieldKey={`${key}.${nestedKey}`}
                                                        prop={nestedProp}
                                                        value={nestedFieldValue}
                                                        onChange={(k, v) => handleNestedChange(k, v)}
                                                        nodeType={nodeType}
                                                        credentialIds={credentialIds}
                                                        config={localConfig}
                                                        onOpenCredentials={onSwitchToCredentials}
                                                    />
                                                ) : (
                                                    renderField(
                                                        `${key}.${nestedKey}`,
                                                        nestedProp,
                                                        nestedFieldValue,
                                                        (k, v) => handleNestedChange(k, v),
                                                        false,
                                                        undefined,
                                                        localConfig,
                                                        false,
                                                        nodeId,
                                                        nodeType,
                                                        workflowId,
                                                    )
                                                )}
                                                {renderFieldPanelPrompts(`${key}.${nestedKey}`, nestedProp)}
                                            </div>
                                        );
                                    })}
                                </div>
                            )}
                        </div>
                    );
                }

                // Check if this is a collapsible widget (function_inputs, python_editor, textarea, tool_parameters, form_fields)
                const isCollapsibleWidget = prop['ui:widget'] === 'function_inputs' || prop['ui:widget'] === 'python_editor' || prop['ui:widget'] === 'textarea' || prop['ui:widget'] === 'tool_parameters' || prop['ui:widget'] === 'form_fields';

                if (isCollapsibleWidget) {
                    const isCollapsed = collapsedSections[key] ?? false;
                    const toggleCollapsed = () => setCollapsedSections(prev => ({ ...prev, [key]: !prev[key] }));

                    return (
                        <div
                            key={key}
                            data-field-key={key}
                            className="space-y-2"
                        >
                            <div className="flex flex-wrap items-center gap-x-1 gap-y-0.5">
                                <label className="text-xs text-muted-foreground uppercase tracking-wider flex items-center gap-2 min-w-0 break-words">
                                    {prop.title || key}
                                    <FieldRequirementBadge isRequired={isRequired || requireOneOfAttention.has(key)} isFilled={isFieldFilled(localConfig[key])} />
                                </label>
                                {workflowId && nodeId && (
                                    <CopyLinkButton
                                        url={buildNodeDeepLink(workflowId, nodeId, key)}
                                        tooltip="Copy link to field"
                                    />
                                )}
                                <button
                                    type="button"
                                    onClick={toggleCollapsed}
                                    className="p-0.5 rounded hover:bg-foreground/[0.05] text-muted-foreground dark:text-zinc-500 hover:text-foreground/80 transition-colors"
                                    title={isCollapsed ? 'Expand' : 'Collapse'}
                                >
                                    {isCollapsed ? (
                                        <ChevronRight className="w-3.5 h-3.5" />
                                    ) : (
                                        <ChevronDown className="w-3.5 h-3.5" />
                                    )}
                                </button>
                                {renderAutofillButton(key, prop.title)}
                            </div>
                            {!isCollapsed && (
                                <div data-field-control onFocusCapture={() => setFocusedFieldKey(key)}>
                                    {renderField(key, prop, value, handleFieldChange, isLoadingValues[key], handleFieldRefetch, localConfig, false, nodeId, nodeType, workflowId)}
                                </div>
                            )}
                            {!isCollapsed && renderFieldPanelPrompts(key, prop, value)}
                            {fieldAddons?.[key]}
                        </div>
                    );
                }

                // Check if this field has execution errors
                const fieldHasError = fieldErrors[key] && fieldErrors[key].length > 0;

                // A field bound to a workflow variable ({{vars.x}} as its WHOLE
                // value) shows the RESOLVED value and its editor writes through
                // the variable — the reference stays in the config, so the
                // binding survives every edit. The raw ref was unreadable and
                // made the field's own dropdown a trap (picking would have
                // replaced the reference with a literal).
                const boundVar =
                    typeof value === 'string' && onVariableValueChange
                        ? /^\{\{vars\.([\w-]+)\}\}$/.exec(value)?.[1]
                        : undefined;
                const fieldValue = boundVar
                    ? String(workflowVariables?.[boundVar] ?? '')
                    : value;
                const fieldOnChange = boundVar
                    ? (k: string, v: any) => {
                          // Only the primary key is the variable's value —
                          // `${key}__label` bookkeeping writes are dropped.
                          if (k === key) onVariableValueChange!(boundVar, String(v ?? ''));
                      }
                    : handleFieldChange;

                return (
                    <div
                        key={key}
                        data-field-key={key}
                        className={fieldHasError ? 'relative rounded-lg p-2 -mx-2 bg-red-500/5 border border-red-500/30' : ''}
                    >
                        <div className={`flex flex-wrap items-center gap-x-1 gap-y-0.5${prop.description ? '' : ' mb-1.5'}`}>
                            <label className={`text-xs uppercase tracking-wider flex items-center gap-2 min-w-0 break-words ${fieldHasError ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground'}`}>
                                {prop.title || key}
                                <FieldRequirementBadge isRequired={isRequired || requireOneOfAttention.has(key)} isFilled={isFieldFilled(localConfig[key])} />
                            </label>
                            {workflowId && nodeId && (
                                <CopyLinkButton
                                    url={buildNodeDeepLink(workflowId, nodeId, key)}
                                    tooltip="Copy link to field"
                                />
                            )}
                            {renderAutofillButton(key, prop.title)}
                        </div>

                        {prop.description && (
                            <div className="text-[11.5px] text-muted-foreground/70 dark:text-zinc-500 mb-2 mt-1">
                                {prop.description}
                            </div>
                        )}

                        {boundVar && (
                            <div className="mb-1.5 mt-1 flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground/70 dark:text-zinc-500">
                                <Braces className="h-3 w-3 shrink-0" />
                                <span className="font-mono">{boundVar}</span>
                                <span>· edits update the variable</span>
                                <button
                                    type="button"
                                    onClick={() => handleFieldChange(key, fieldValue)}
                                    title="Replace the reference with the current value — the field stops following the variable"
                                    className="underline decoration-foreground/25 underline-offset-2 transition-colors hover:decoration-foreground/60"
                                >
                                    unlink
                                </button>
                            </div>
                        )}

                        <div data-field-control onFocusCapture={() => setFocusedFieldKey(key)}>
                            <NodeConfigFieldControl
                                fieldKey={key}
                                prop={prop}
                                value={fieldValue}
                                onChange={fieldOnChange}
                                nodeType={nodeType}
                                nodeId={nodeId}
                                workflowId={workflowId}
                                credentialIds={credentialIds}
                                config={localConfig}
                                hasError={fieldHasError}
                                isLoading={isLoadingValues[key]}
                                onFieldRefetch={handleFieldRefetch}
                                onOpenCredentials={onSwitchToCredentials}
                            />
                        </div>
                        {fieldAddons?.[key]}
                        {renderFieldPanelPrompts(key, prop, value)}

                        {/* Field-level error message from execution errors */}
                        {fieldHasError && (
                            <div className="mt-1.5 text-xs text-red-600 dark:text-red-400">
                                {fieldErrors[key][0]}
                            </div>
                        )}
                    </div>
                );
            })}

            {/* Clear State button for stateful nodes */}
            {['automation-rss', 'state-manager', 'agent'].includes(nodeType) && nodeId && workflowId && (
                <ClearStateButton
                    nodeId={nodeId}
                    workflowId={workflowId}
                    nodeType={nodeType}
                    config={config}
                    onChange={onChange}
                />
            )}

            </>)}

            </>)}

        </div>
    );
}

// Render appropriate form field based on JSON Schema property type
// Text fields use DroppableTextField to accept dropped JSON field references
function renderField(
    key: string,
    prop: any,
    value: any,
    onChange: (key: string, value: any) => void,
    isLoading?: boolean,
    onFieldRefetch?: (fieldName: string) => void,  // For widgets that need to trigger a refetch (e.g., nextRun countdown expired)
    config?: Record<string, any>,  // Full config for accessing sibling field values
    hasError?: boolean,  // Whether this field has execution errors
    nodeId?: string,
    nodeType?: string,
    workflowId?: string,
) {
    const commonClasses = `w-full px-3 py-2 text-sm bg-card dark:bg-foreground/[0.02] border rounded-lg text-foreground/80 placeholder:text-[hsl(var(--placeholder))] focus:outline-none transition-colors ${
        hasError
            ? 'border-red-500/50 focus:border-red-500/70'
            : 'border-input dark:border-white/[0.05] focus:border-foreground/20'
    }`;

    // An explicit ui:placeholder hint wins; otherwise fall back to the field's
    // description so text inputs always show guidance when the schema provides it.
    const fieldPlaceholder = prop['ui:placeholder'] || prop.description;

    // First, try the shared widget registry for ui:widget types
    // This ensures consistency with generation panel and other consumers
    const widgetElement = renderSchemaWidget({
        fieldKey: key,
        fieldSchema: prop,
        value,
        onChange,
        isLoading,
        config,
        onFieldRefetch,
        nodeId,
        nodeType,
        workflowId,
    });
    if (widgetElement) {
        return widgetElement;
    }

    // Array of enum values -> multi-select combobox that emits string[]. Handles
    // both shapes: top-level enum with type:array, and items.enum. Without this,
    // an array-enum fell through to the scalar enum/text path and stored a string,
    // failing AJV's "must be array" (e.g. the Pipedrive trigger's event_types).
    const isArrayEnum =
        prop.type === 'array' && (Array.isArray(prop.enum) || Array.isArray(prop.items?.enum));
    if (isArrayEnum) {
        const enumValues = (prop.enum || prop.items?.enum) as string[];
        const labels = prop.enumNames || prop.enumLabels || prop.items?.enumNames || enumValues;
        const arrVal = Array.isArray(value) ? value : value ? [String(value)] : [];
        return (
            <MultiSelectEnumField
                fieldKey={key}
                value={arrVal}
                enumValues={enumValues}
                enumLabels={labels}
                onChange={onChange}
                placeholder={prop['ui:placeholder'] || prop.placeholder || prop.description || 'Select one or more...'}
            />
        );
    }

    // Enum (select dropdown) - use searchable combobox if x-enum-searchable is true
    if (prop.enum) {
        const labels = prop.enumNames || prop.enumLabels || prop.enum;
        const isSearchable = prop['x-enum-searchable'] === true;

        if (isSearchable) {
            return (
                <SearchableEnumField
                    fieldKey={key}
                    value={value || ''}
                    enumValues={prop.enum}
                    enumLabels={labels}
                    onChange={onChange}
                    placeholder={prop['ui:placeholder'] || prop.placeholder || prop.description || 'Select an option...'}
                />
            );
        }

        // Standard select dropdown for non-searchable enums
        return (
            <select
                value={value}
                onChange={(e) => onChange(key, e.target.value)}
                className={commonClasses}
            >
                {prop.enum.map((opt: string, idx: number) => (
                    <option key={opt} value={opt} className="bg-card">
                        {labels[idx] || opt}
                    </option>
                ))}
            </select>
        );
    }

    // Textarea (when explicitly requested via ui:widget) - uses DroppableTextField for editor drag-drop
    if (prop['ui:widget'] === 'textarea') {
        return (
            <DroppableTextField
                fieldKey={key}
                value={value || ''}
                onChange={(newValue) => onChange(key, newValue)}
                placeholder={fieldPlaceholder}
                multiline={true}
                rows={3}
                hasError={hasError}
            />
        );
    }

    // URL input - droppable (URLs can come from previous nodes)
    if (prop.format === 'uri') {
        return (
            <DroppableTextField
                fieldKey={key}
                value={value || ''}
                onChange={(newValue) => onChange(key, newValue)}
                placeholder={fieldPlaceholder}
                hasError={hasError}
            />
        );
    }

    // Number input - droppable (references resolve to actual values at runtime)
    if (prop.type === 'number' || prop.type === 'integer') {
        // If value contains a reference, treat as text; otherwise parse as number
        const stringValue = value?.toString() || '';
        return (
            <DroppableTextField
                fieldKey={key}
                value={stringValue}
                onChange={(newValue) => {
                    // If it contains a reference/expression, keep as string for backend
                    // resolution (brace-aware so JS blocks with inner `}` aren't parsed).
                    if (newValue.includes('{{')) {
                        onChange(key, newValue);
                    } else if (newValue === '') {
                        onChange(key, '');
                    } else {
                        // Parse as number
                        const num = prop.type === 'integer' ? parseInt(newValue, 10) : parseFloat(newValue);
                        onChange(key, isNaN(num) ? newValue : num);
                    }
                }}
                placeholder={fieldPlaceholder}
                hasError={hasError}
            />
        );
    }

    // Default: text input - droppable
    return (
        <DroppableTextField
            fieldKey={key}
            value={value || ''}
            onChange={(newValue) => onChange(key, newValue)}
            placeholder={fieldPlaceholder}
            hasError={hasError}
        />
    );
}

interface NodeConfigFieldControlProps {
    fieldKey: string;
    prop: Record<string, unknown>;
    value: unknown;
    onChange: (key: string, value: unknown) => void;
    nodeType: string;
    nodeId?: string;
    workflowId?: string;
    credentialIds?: Record<string, string>;
    /** Sibling field values — dynamic dropdowns and some widgets depend on them. */
    config?: Record<string, unknown>;
    hasError?: boolean;
    isLoading?: boolean;
    onFieldRefetch?: (fieldName: string) => void;
    onOpenCredentials?: () => void;
}

/**
 * One config field's input control — the ui:widget registry, dynamic-options
 * dropdowns, enums, and the droppable text/number fallback, picked the same way
 * everywhere.
 *
 * Exported because the config panel is no longer the only place a field gets
 * filled in: the Run button's unconfigured-steps popup edits missing fields in
 * place. Both must render the identical control, or a field would behave (and
 * store its value) differently depending on where the user typed it.
 */
export function NodeConfigFieldControl({
    fieldKey,
    prop,
    value,
    onChange,
    nodeType,
    nodeId,
    workflowId,
    credentialIds,
    config,
    hasError,
    isLoading,
    onFieldRefetch,
    onOpenCredentials,
}: NodeConfigFieldControlProps) {
    if (prop['x-dynamic-options']) {
        return (
            <DynamicOptionsField
                fieldKey={fieldKey}
                prop={prop}
                value={value}
                onChange={onChange}
                nodeType={nodeType}
                credentialIds={credentialIds ?? {}}
                config={config ?? {}}
                hasError={hasError}
                onOpenCredentials={onOpenCredentials}
            />
        );
    }
    return renderField(
        fieldKey,
        prop,
        value,
        onChange,
        isLoading,
        onFieldRefetch,
        config,
        hasError,
        nodeId,
        nodeType,
        workflowId,
    );
}

// Clear State button component for stateful nodes (RSS with only_new_items, State Manager)
function ClearStateButton({ nodeId, workflowId, nodeType, config, onChange }: {
    nodeId: string;
    workflowId: string;
    nodeType: string;
    config: Record<string, any>;
    onChange: (config: Record<string, any>, sourceNodeId?: string) => void;
}) {
    const [isClearing, setIsClearing] = useState(false);
    const [cleared, setCleared] = useState(false);

    const handleClearState = async () => {
        setIsClearing(true);
        try {
            const response = await sendEventAsync({
                event_name: 'workflow:clear_node_state',
                workflow_id: workflowId,
                node_id: nodeId,
            }) as { success: boolean; error?: string };

            if (response?.success) {
                // For state-manager nodes, also reset the config's state field to empty
                if (nodeType === 'state-manager') {
                    onChange({ ...config, state: {} }, nodeId);
                }
                setCleared(true);
                setTimeout(() => setCleared(false), 2000);
            }
        } catch (error) {
            console.error('Failed to clear node state:', error);
        } finally {
            setIsClearing(false);
        }
    };

    return (
        <div className="pt-4 mt-4 border-t border-border dark:border-white/[0.05]">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="min-w-0 flex-1">
                    <div className="text-xs text-muted-foreground break-words">
                        {nodeType === 'agent' ? 'Conversation History' : 'Persistent State'}
                    </div>
                    <div className="text-[10px] text-muted-foreground/70 dark:text-zinc-600 mt-0.5 break-words">
                        {nodeType === 'agent'
                            ? 'Clear all stored conversations for this node'
                            : 'Clear saved state to reset node memory'}
                    </div>
                </div>
                <button
                    onClick={handleClearState}
                    disabled={isClearing || cleared}
                    className={`px-3 py-1.5 text-xs rounded-lg border transition-colors flex items-center gap-1.5 ${
                        cleared
                            ? 'bg-green-500/10 border-green-500/30 text-green-600 dark:text-green-400'
                            : 'bg-red-500/10 border-red-500/30 text-red-600 dark:text-red-400 hover:bg-red-500/20 disabled:opacity-50'
                    }`}
                >
                    {isClearing ? (
                        <>
                            <Loader2 className="h-3 w-3 animate-spin" />
                            Clearing...
                        </>
                    ) : cleared ? (
                        <>
                            <CheckCircle2 className="h-3 w-3" />
                            Cleared
                        </>
                    ) : (
                        nodeType === 'agent' ? 'Clear History' : 'Clear State'
                    )}
                </button>
            </div>
        </div>
    );
}
