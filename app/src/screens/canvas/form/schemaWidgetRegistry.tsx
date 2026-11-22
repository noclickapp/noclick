/**
 * schemaWidgetRegistry - Single source of truth for rendering schema-based form widgets.
 *
 * Both NodeConfig (workflow editor) and SchemaConfigForm (workflow generation) use this
 * registry to render fields. This ensures consistency and eliminates duplication.
 *
 * Widgets handle special ui:widget types. For standard type-based rendering (string, number,
 * boolean, enum), each consumer handles those directly since they may need different
 * components (e.g., DroppableTextField vs plain input).
 */

import { type ReactElement, useState, useRef } from 'react';
import { Loader2, Upload } from 'lucide-react';
import { standing } from '@/slots';
import { CopyableReadonlyField } from '@/ui/CopyableReadonlyField';
import { SubscriptionStatusField } from './SubscriptionStatusField';
import { ScheduleWidget } from './ScheduleWidget';
import { SchedulesWidget } from './SchedulesWidget';
import { NextRunWidget } from './NextRunWidget';
import { PythonFunctionEditor } from './PythonFunctionEditor';
import { JavaScriptFunctionEditor } from './JavaScriptFunctionEditor';
import { FunctionInputsEditor } from './FunctionInputsEditor';
import { ToolParametersEditor } from './ToolParametersEditor';
import { ApprovalFieldsEditor } from './ApprovalFieldsEditor';
import { SwitchCasesEditor } from './SwitchCasesEditor';
import { SearchableEnumField } from './SearchableEnumField';
import { DroppableTextField } from './DroppableTextField';
import { DateTimeField } from './DateTimeField';
import { StateEditorWidget } from './StateEditorWidget';
import { VariableAssignmentsEditor } from './VariableAssignmentsEditor';
import { KeyValueEditor } from './KeyValueEditor';
import { HttpBodyEditor } from './HttpBodyEditor';
import { AlarmViewerWidget } from './AlarmViewerWidget';
import { WorkflowPickerWidget } from './WorkflowPickerWidget';
import { ExternalFormInputsWidget } from './ExternalFormInputsWidget';
import { STEP_WIDGETS } from '../slots';
import { SecretInput } from './SecretInput';
import { StringListInput } from '@/ui/StringListInput';
import { Switch } from '@/ui/switch';

// ============================================================================
// Types
// ============================================================================

export interface WidgetRenderProps {
    /** Field key in the config object */
    fieldKey: string;
    /** JSON Schema property definition */
    fieldSchema: any;
    /** Current field value */
    value: any;
    /** Change handler - called with (fieldKey, newValue) */
    onChange: (key: string, value: any) => void;
    /** Whether the field value is currently loading */
    isLoading?: boolean;
    /** Full config object for accessing sibling fields */
    config?: Record<string, any>;
    /** Callback when a field needs to be refetched (e.g., after countdown expires) */
    onFieldRefetch?: (fieldName: string) => void | Promise<void>;
    /** Node context for widgets that need backend communication */
    nodeId?: string;
    nodeType?: string;
    workflowId?: string;
}

// ============================================================================
// Shared Input Styling
// ============================================================================

export const inputClasses = "w-full px-3 py-2 rounded-lg border border-border dark:border-white/[0.08] bg-card dark:bg-foreground/[0.03] text-foreground text-sm outline-none placeholder:text-[hsl(var(--placeholder))] focus:border-foreground/20 focus:bg-muted dark:focus:bg-foreground/[0.05]";

// ============================================================================
// Widget Renderers
// ============================================================================

/**
 * Schedule widget - cron schedule picker for trigger nodes (single entry).
 */
function renderScheduleWidget({ fieldKey, fieldSchema, value, onChange }: WidgetRenderProps): ReactElement {
    return (
        <ScheduleWidget
            value={value || fieldSchema.default || { frequency: 'hours', interval: 1, hour: 9, minute: 0 }}
            onChange={(newValue) => onChange(fieldKey, newValue)}
            excludeFrequencies={fieldSchema['x-exclude-frequencies']}
        />
    );
}

/**
 * Schedules widget - multi-schedule picker for cron trigger nodes.
 * Renders a list of ScheduleWidget instances with add/remove buttons.
 */
function renderSchedulesWidget({ fieldKey, value, onChange }: WidgetRenderProps): ReactElement {
    return (
        <SchedulesWidget
            value={value || []}
            onChange={(newValue) => onChange(fieldKey, newValue)}
            fieldKey={fieldKey}
        />
    );
}

/**
 * Next run widget - shows human-readable date with live countdown.
 * When countdown expires, triggers a refetch to get new next_run from backend.
 */
function renderNextRunWidget({ value, onFieldRefetch, config }: WidgetRenderProps): ReactElement {
    return <NextRunWidget value={value} onExpired={() => onFieldRefetch?.('webhook_url')} timezone={config?.timezone} />;
}

/**
 * Python editor widget - code editor for Python serverless function code.
 */
function renderPythonEditorWidget({ fieldKey, fieldSchema, value, onChange, config }: WidgetRenderProps): ReactElement {
    // Extract input names from sibling function_inputs field for dynamic signature
    const functionInputs = config?.function_inputs;
    const inputNames = Array.isArray(functionInputs)
        ? functionInputs.map((i: { name: string; value: string }) => i.name).filter(Boolean)
        : [];

    return (
        <PythonFunctionEditor
            value={value || ''}
            onChange={(newValue) => onChange(fieldKey, newValue)}
            placeholder={fieldSchema.placeholder || fieldSchema.description}
            inputNames={inputNames}
        />
    );
}

/**
 * Code editor widget - JavaScript editor with syntax highlighting.
 */
function renderCodeEditorWidget({ fieldKey, fieldSchema, value, onChange, config }: WidgetRenderProps): ReactElement {
    const language = fieldSchema['x-code-language'] || 'javascript';
    return (
        <JavaScriptFunctionEditor
            value={value || ''}
            onChange={(newValue) => onChange(fieldKey, newValue)}
            placeholder={fieldSchema.placeholder || fieldSchema.description}
            functionInputs={config?.function_inputs}
            language={language}
        />
    );
}

/**
 * Function inputs widget - array of name/value pairs for serverless function.
 */
function renderFunctionInputsWidget({ fieldKey, value, onChange }: WidgetRenderProps): ReactElement {
    return (
        <FunctionInputsEditor
            fieldKey={fieldKey}
            value={value || []}
            onChange={(newValue) => onChange(fieldKey, newValue)}
        />
    );
}

/**
 * Tool parameters widget - array of parameters for LLM function calling.
 */
function renderToolParametersWidget({ fieldKey, value, onChange }: WidgetRenderProps): ReactElement {
    return (
        <ToolParametersEditor
            fieldKey={fieldKey}
            value={value || []}
            onChange={(newValue) => onChange(fieldKey, newValue)}
        />
    );
}

/**
 * Approval fields widget — like form_fields but each field has a Value input for references.
 */
function renderApprovalFieldsWidget({ fieldKey, value, onChange }: WidgetRenderProps): ReactElement {
    return (
        <ApprovalFieldsEditor
            fieldKey={fieldKey}
            value={value || []}
            onChange={(newValue) => onChange(fieldKey, newValue)}
        />
    );
}

/**
 * Switch cases widget - array of value/output pairs for switch node branching.
 */
function renderSwitchCasesWidget({ fieldKey, value, onChange }: WidgetRenderProps): ReactElement {
    return (
        <SwitchCasesEditor
            fieldKey={fieldKey}
            value={value || []}
            onChange={(newValue) => onChange(fieldKey, newValue)}
        />
    );
}

/**
 * Switch default output widget - searchable dropdown populated from sibling switch_cases values.
 * Supports typing and drag-and-drop of upstream node references.
 */
function renderSwitchDefaultOutputWidget({ fieldKey, value, onChange, config }: WidgetRenderProps): ReactElement {
    const cases: { value: string }[] = Array.isArray(config?.switch_cases) ? config.switch_cases : [];
    const options = cases.map(c => c.value).filter(Boolean);

    return (
        <div>
            <SearchableEnumField
                fieldKey={fieldKey}
                value={value || ''}
                enumValues={options}
                onChange={onChange}
                placeholder="Select or type default case..."
            />
            {options.length === 0 && (
                <p className="text-[10px] text-muted-foreground/70 dark:text-zinc-600 mt-1">
                    Add cases above first
                </p>
            )}
        </div>
    );
}

/**
 * Webhook URL widget - readonly, click-anywhere-to-copy field with loading state.
 */
function renderWebhookWidget({ fieldSchema, value, isLoading }: WidgetRenderProps): ReactElement {
    return (
        <CopyableReadonlyField
            value={value || ''}
            isLoading={isLoading}
            copyable={fieldSchema['ui:copyable'] === true}
            loadingPlaceholder="Generating webhook URL..."
            emptyPlaceholder="Will be auto-generated after completion..."
            inputClassName={inputClasses}
        />
    );
}

/**
 * Readonly widget - readonly, click-anywhere-to-copy field with loading state.
 */
function renderReadonlyWidget({ fieldSchema, value, isLoading }: WidgetRenderProps): ReactElement {
    return (
        <CopyableReadonlyField
            value={value || fieldSchema.default || ''}
            isLoading={isLoading}
            copyable={fieldSchema['ui:copyable'] === true}
            inputClassName={inputClasses}
        />
    );
}

/**
 * Subscription status widget - an app-event trigger's registration verdict,
 * with the backend-minted fix-it action (`config.trigger_action`) as a button.
 */
function renderSubscriptionStatusWidget({ value, isLoading, config, onFieldRefetch }: WidgetRenderProps): ReactElement {
    return (
        <SubscriptionStatusField
            value={value || ''}
            isLoading={isLoading}
            action={config?.trigger_action ?? null}
            onAction={onFieldRefetch}
        />
    );
}

/**
 * Password widget - masked input field.
 */
function renderPasswordWidget({ fieldKey, fieldSchema, value, onChange }: WidgetRenderProps): ReactElement {
    return (
        <SecretInput
            value={value || ''}
            onChange={(e) => onChange(fieldKey, e.target.value)}
            placeholder={fieldSchema.placeholder || fieldSchema.description || 'Enter value...'}
            inputClassName={inputClasses}
        />
    );
}

// ============================================================================
// State Editor - JSON editor with syntax highlighting and drag-drop support
// ============================================================================

/**
 * State editor widget - JSON editor with syntax highlighting for State Manager node.
 * Supports drag-and-drop of references from the Input panel.
 */
function renderStateEditorWidget({ fieldKey, fieldSchema, value, onChange }: WidgetRenderProps): ReactElement {
    const placeholder = fieldSchema.placeholder || '{\n  "counter": 0,\n  "items": []\n}';
    return (
        <StateEditorWidget
            fieldKey={fieldKey}
            placeholder={placeholder}
            value={value || {}}
            onChange={onChange}
        />
    );
}

/**
 * Variable assignments widget - list of name/value pairs for set-variable nodes.
 */
function renderVariableAssignmentsWidget({ fieldKey, value, onChange }: WidgetRenderProps): ReactElement {
    return (
        <VariableAssignmentsEditor
            fieldKey={fieldKey}
            value={value || []}
            onChange={(newValue) => onChange(fieldKey, newValue)}
        />
    );
}

/**
 * Segmented widget - renders a string enum as a row of pill buttons (a
 * segmented control). Clearer and more discoverable than a dropdown for short
 * option sets like the HTTP body type. Reads `enum` + `enumNames` from schema.
 */
function renderSegmentedWidget({ fieldKey, fieldSchema, value, onChange }: WidgetRenderProps): ReactElement {
    const options: string[] = fieldSchema.enum || [];
    const labels: string[] = fieldSchema.enumNames || options;
    const current = value ?? fieldSchema.default ?? options[0];
    return (
        <div className="inline-flex w-full gap-0.5 rounded-lg border border-foreground/[0.06] bg-foreground/[0.03] p-0.5">
            {options.map((opt, i) => {
                const active = current === opt;
                return (
                    <button
                        key={opt}
                        type="button"
                        onClick={() => onChange(fieldKey, opt)}
                        className={`flex-1 rounded-md px-2 py-1.5 text-xs transition-colors ${
                            active
                                ? 'bg-foreground/[0.12] text-foreground shadow-sm'
                                : 'text-zinc-400 hover:text-zinc-200'
                        }`}
                    >
                        {labels[i] ?? opt}
                    </button>
                );
            })}
        </div>
    );
}

/**
 * Toggle widget - a switch for a "true"/"false" string-enum field. Reads
 * `enumNames` (ordered [true-label, false-label]) for the inline state label.
 */
function renderToggleWidget({ fieldKey, fieldSchema, value, onChange }: WidgetRenderProps): ReactElement {
    const on = (value ?? fieldSchema.default) === 'true';
    const labels: string[] = fieldSchema.enumNames || ['On', 'Off'];
    return (
        <div className="flex items-center gap-2.5">
            <Switch checked={on} onCheckedChange={(c) => onChange(fieldKey, c ? 'true' : 'false')} />
            <span className="text-xs text-zinc-400">{on ? labels[0] : labels[1]}</span>
        </div>
    );
}

/**
 * Key/value widget - list of {key, value, enabled} rows for HTTP headers and
 * query parameters. Each value supports {{references}} via drag-and-drop.
 */
function renderKeyValueWidget({ fieldKey, fieldSchema, value, onChange }: WidgetRenderProps): ReactElement {
    const title = (fieldSchema?.title || '').toLowerCase();
    const isQuery = title.includes('query') || title.includes('param');
    return (
        <KeyValueEditor
            fieldKey={fieldKey}
            value={value}
            onChange={(rows) => onChange(fieldKey, rows)}
            keyPlaceholder={isQuery ? 'param' : 'Header-Name'}
            addLabel={isQuery ? 'Add parameter' : 'Add header'}
        />
    );
}

/**
 * List widget - multi-value string input for fields like email recipients and
 * feed URLs. Delegates to the shared StringListInput (auto-append + autosave,
 * no Enter required); see app/components/shared/StringListInput.tsx.
 */
function renderListWidget({ fieldKey, fieldSchema, value, onChange }: WidgetRenderProps): ReactElement {
    // Normalize: accept both array and comma-separated string
    const items: unknown[] = Array.isArray(value) ? value : (
        typeof value === 'string' && value.trim() ? value.split(',').map((s: string) => s.trim()) : []
    );
    return (
        <StringListInput
            value={items}
            onChange={(next) => onChange(fieldKey, next)}
            placeholder={fieldSchema.placeholder || fieldSchema.description}
            inputClassName={`${inputClasses} py-1.5`}
            trailingClassName="!border-dashed"
        />
    );
}

/**
 * Workflow picker widget - multi-select dropdown for choosing workflows by name.
 */
function renderWorkflowPickerWidget({ fieldKey, value, onChange, nodeType }: WidgetRenderProps): ReactElement {
    return (
        <WorkflowPickerWidget fieldKey={fieldKey} value={value} onChange={onChange} nodeType={nodeType} />
    );
}

/**
 * External form inputs widget — renders the selected flow's form fields to fill
 * (Submit External Form node). Reads sibling `workflow` + `form` config values.
 */
function renderExternalFormInputsWidget(props: WidgetRenderProps): ReactElement {
    return <ExternalFormInputsWidget {...props} />;
}

/**
 * Alarm viewer widget - displays active alarms for an alarm node.
 */
function renderAlarmViewerWidget(props: WidgetRenderProps): ReactElement {
    return (
        <AlarmViewerWidget
            nodeId={props.nodeId || ''}
            nodeType={props.nodeType || ''}
            workflowId={props.workflowId || ''}
        />
    );
}

// ============================================================================
// Text Upload Textarea Widget
// ============================================================================

function TextUploadTextareaWidget({ fieldKey, fieldSchema, value, onChange, nodeType }: WidgetRenderProps): ReactElement {
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const inputRef = useRef<HTMLInputElement>(null);
    const isFirestoreNode = nodeType === 'automation-firestore';

    const handleFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        e.target.value = '';
        if (!file) return;

        setLoading(true);
        setError(null);
        try {
            const rawText = await file.text();
            const shouldFormatJson = fieldSchema['x-format-uploaded-json'] !== false;
            let nextValue = rawText;

            if (shouldFormatJson) {
                const trimmed = rawText.trim();
                if (trimmed) {
                    try {
                        nextValue = JSON.stringify(JSON.parse(trimmed), null, 2);
                    } catch {
                        // Keep the raw file contents when the upload is not valid JSON.
                    }
                }
            }

            onChange(fieldKey, nextValue);
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Failed to read file');
        } finally {
            setLoading(false);
        }
    };

    const uploadButton = (
        <button
            type="button"
            onClick={() => inputRef.current?.click()}
            disabled={loading}
            title="Load from file"
            className="flex items-center gap-1.5 h-9 px-2.5 rounded-lg border border-foreground/[0.08] bg-foreground/[0.03] hover:bg-foreground/[0.08] text-foreground/60 hover:text-foreground/90 transition-colors disabled:opacity-40 text-xs"
        >
            {loading ? <Loader2 size={14} className="animate-spin" /> : <Upload size={14} />}
            <span>Upload</span>
        </button>
    );

    return (
        <div className="space-y-2">
            <input
                ref={inputRef}
                type="file"
                accept={fieldSchema['ui:accept'] || '.json,.txt,application/json,text/plain'}
                className="hidden"
                onChange={handleFile}
            />
            {isFirestoreNode ? (
                <div className="relative">
                    <textarea
                        value={value || ''}
                        onChange={e => onChange(fieldKey, e.target.value)}
                        placeholder={fieldSchema.placeholder || fieldSchema.description}
                        className={`${inputClasses} min-h-[160px] font-mono pr-28 pb-16`}
                    />
                    <div className="absolute bottom-2 right-2">
                        {uploadButton}
                    </div>
                </div>
            ) : (
                <>
                    <div className="flex justify-end">
                        {uploadButton}
                    </div>
                    <textarea
                        value={value || ''}
                        onChange={e => onChange(fieldKey, e.target.value)}
                        placeholder={fieldSchema.placeholder || fieldSchema.description}
                        className={`${inputClasses} min-h-[160px] font-mono`}
                    />
                </>
            )}
            {error && <p className="text-xs text-red-400">{error}</p>}
        </div>
    );
}

function renderTextUploadTextareaWidget(props: WidgetRenderProps): ReactElement {
    return <TextUploadTextareaWidget {...props} />;
}

// ============================================================================
// Widget Registry
// ============================================================================

type WidgetRenderer = (props: WidgetRenderProps) => ReactElement;

/**
 * Registry mapping ui:widget values to their renderer functions.
 * All widgets defined here are automatically available in both NodeConfig and generation panel; a host's own
 * (`canvas.step.widgets`) stand ahead of them.
 */
const WIDGET_REGISTRY: Record<string, WidgetRenderer> = {
    'schedule': renderScheduleWidget,
    'schedules': renderSchedulesWidget,
    'nextRun': renderNextRunWidget,
    'python_editor': renderPythonEditorWidget,
    'code_editor': renderCodeEditorWidget,
    'function_inputs': renderFunctionInputsWidget,
    'tool_parameters': renderToolParametersWidget,
    'approval_fields': renderApprovalFieldsWidget,
    'switch_cases': renderSwitchCasesWidget,
    'switch_default_output': renderSwitchDefaultOutputWidget,
    'webhook': renderWebhookWidget,
    'readonly': renderReadonlyWidget,
    'subscription_status': renderSubscriptionStatusWidget,
    'password': renderPasswordWidget,
    'datetime': ({ fieldKey, fieldSchema, value, onChange }) => (
        <DateTimeField
            value={value || ''}
            onChange={(v) => onChange(fieldKey, v)}
            placeholder={fieldSchema['ui:placeholder'] || fieldSchema.placeholder || fieldSchema.description}
            fieldKey={fieldKey}
            mode="datetime"
        />
    ),
    'date': ({ fieldKey, fieldSchema, value, onChange }) => (
        <DateTimeField
            value={value || ''}
            onChange={(v) => onChange(fieldKey, v)}
            placeholder={fieldSchema['ui:placeholder'] || fieldSchema.placeholder || fieldSchema.description}
            fieldKey={fieldKey}
            mode="date"
        />
    ),
    'state_editor': renderStateEditorWidget,
    'variable_assignments': renderVariableAssignmentsWidget,
    'key_value': renderKeyValueWidget,
    'segmented': renderSegmentedWidget,
    'toggle': renderToggleWidget,
    'http_body': (props) => <HttpBodyEditor {...props} />,
    'list': renderListWidget,
    'alarm_viewer': renderAlarmViewerWidget,
    'text_upload_textarea': renderTextUploadTextareaWidget,
    'workflow_picker': renderWorkflowPickerWidget,
    'external_form_inputs': renderExternalFormInputsWidget,
};

// ============================================================================
// Main Export
// ============================================================================

/**
 * Render a schema widget if the field has a ui:widget that we handle.
 * Returns null if no matching widget found (caller should fall back to type-based rendering).
 *
 * @example
 * const widgetElement = renderSchemaWidget(props);
 * if (widgetElement) return widgetElement;
 * // Fall back to type-based rendering...
 */
export function renderSchemaWidget(props: WidgetRenderProps): ReactElement | null {
    const widgetType = props.fieldSchema?.['ui:widget'];

    const renderer = widgetType ? standing(STEP_WIDGETS)[widgetType] ?? WIDGET_REGISTRY[widgetType] : undefined;
    if (renderer) {
        return renderer(props);
    }

    return null;
}

/**
 * Check if a field has a widget that we handle in the registry.
 */
export function hasRegisteredWidget(fieldSchema: any): boolean {
    const widgetType = fieldSchema?.['ui:widget'];
    return widgetType ? widgetType in standing(STEP_WIDGETS) || widgetType in WIDGET_REGISTRY : false;
}

/**
 * Get the list of all registered widget types.
 */
export function getRegisteredWidgetTypes(): string[] {
    return [...new Set([...Object.keys(WIDGET_REGISTRY), ...Object.keys(standing(STEP_WIDGETS))])];
}
