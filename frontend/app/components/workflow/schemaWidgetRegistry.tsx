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

import { type ReactElement, useState, useRef, useEffect } from 'react';
import { Loader2, Plus, X, Upload } from 'lucide-react';
import { sendEventAsync } from '~/lib/socket-sender';
import { ResourceDownloadUrlRequest } from '~/types/socket-events.generated';
import { useResourceUpload } from '~/hooks/useResourceUpload';
import { useRenewableResourceUrl } from '~/hooks/useRenewableResourceUrl';
import { UploadProgressBar } from '~/components/ui/upload-progress';
import { CopyableReadonlyField } from '~/components/ui/CopyableReadonlyField';
import { EmailTriggerField } from './EmailTriggerField';
import { ScheduleWidget } from './ScheduleWidget';
import { SchedulesWidget } from './SchedulesWidget';
import { NextRunWidget } from './NextRunWidget';
import { PythonFunctionEditor } from './PythonFunctionEditor';
import { JavaScriptFunctionEditor } from './JavaScriptFunctionEditor';
import { FunctionInputsEditor } from './FunctionInputsEditor';
import { ToolParametersEditor } from './ToolParametersEditor';
import { FormFieldsEditor } from './FormFieldsEditor';
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
import { FileBrowserWidget } from './FileBrowserWidget';
import { SecretInput } from './SecretInput';
import { StringListInput } from '~/components/shared/StringListInput';
import { Switch } from '~/components/ui/switch';

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
    onFieldRefetch?: (fieldName: string) => void;
    /** Node context for widgets that need backend communication */
    nodeId?: string;
    nodeType?: string;
    workflowId?: string;
}

// ============================================================================
// Shared Input Styling
// ============================================================================

const inputClasses = "w-full px-3 py-2 rounded-lg border border-border dark:border-white/[0.08] bg-card dark:bg-foreground/[0.03] text-foreground text-sm outline-none placeholder:text-[hsl(var(--placeholder))] focus:border-foreground/20 focus:bg-muted dark:focus:bg-foreground/[0.05]";

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
 * Form fields widget - array of input fields for form input trigger.
 */
function renderFormFieldsWidget({ fieldKey, value, onChange }: WidgetRenderProps): ReactElement {
    return (
        <FormFieldsEditor
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
    const items: string[] = Array.isArray(value) ? value : (
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

/**
 * File browser widget - displays files in a filesystem node's managed workspace volume.
 */
function renderFileBrowserWidget(props: WidgetRenderProps): ReactElement {
    return (
        <FileBrowserWidget
            nodeId={props.nodeId || ''}
            nodeType={props.nodeType || ''}
            workflowId={props.workflowId || ''}
            volumeMode={props.config?.volume_mode}
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
// Media Upload Widget — URL/reference field + "upload a file" button
// ============================================================================

// A media input: paste a URL, drag a {{reference}}, or upload a local file.
// Uploads persist a resource ID and renew their private URL for display/run. Used
// by upload nodes (YouTube video, Twitter media, Telegram photo/video, ...).
function MediaUploadWidget({ fieldKey, fieldSchema, value, onChange, nodeId, workflowId }: WidgetRenderProps): ReactElement {
    const [error, setError] = useState<string | null>(null);
    const inputRef = useRef<HTMLInputElement>(null);
    const { uploadFile, uploading, progress } = useResourceUpload();

    const val = (value || '').trim();
    const {
        url: resolvedUrl,
        isResourceId,
        resolving,
        error: resolveError,
    } = useRenewableResourceUrl(val);
    const displayUrl = resolvedUrl || '';
    const isUrl = /^https?:\/\//i.test(displayUrl);
    const ext = isUrl ? (displayUrl.split(/[?#]/)[0].split('.').pop() || '').toLowerCase() : '';
    const isImage = isUrl && ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'svg', 'avif'].includes(ext);
    const isVideo = isUrl && ['mp4', 'mov', 'webm', 'm4v', 'ogg'].includes(ext);

    const handleFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        e.target.value = '';
        if (!file) return;
        if (!workflowId || !nodeId) {
            setError('Save the workflow before uploading a file.');
            return;
        }
        setError(null);
        try {
            const res = await uploadFile(file, workflowId, nodeId);
            onChange(fieldKey, res.resourceId);
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Upload failed');
        }
    };

    return (
        <div className="space-y-2">
            <input
                ref={inputRef}
                type="file"
                accept={fieldSchema['ui:accept'] || undefined}
                className="hidden"
                onChange={handleFile}
            />
            <div className="flex items-center gap-1.5">
                <div className="flex-1 min-w-0">
                    <DroppableTextField
                        fieldKey={fieldKey}
                        value={isResourceId ? '' : (value || '')}
                        onChange={(v) => onChange(fieldKey, v)}
                        placeholder={isResourceId
                            ? (resolving ? 'Preparing uploaded file…' : 'Uploaded file')
                            : (fieldSchema.placeholder || 'Paste a URL, drag a reference, or upload a file')}
                    />
                </div>
                <button
                    type="button"
                    onClick={() => inputRef.current?.click()}
                    disabled={uploading}
                    title="Upload a file"
                    className="flex-none flex items-center gap-1.5 h-9 px-2.5 rounded-lg border border-foreground/[0.08] bg-foreground/[0.03] hover:bg-foreground/[0.08] text-foreground/60 hover:text-foreground/90 transition-colors disabled:opacity-40 text-xs"
                >
                    {uploading ? <Loader2 size={14} className="animate-spin" /> : <Upload size={14} />}
                    <span className="tabular-nums">
                        {uploading ? `${Math.round((progress ?? 0) * 100)}%` : 'Upload'}
                    </span>
                </button>
            </div>
            {uploading && <UploadProgressBar fraction={progress ?? 0} className="h-0.5" />}
            {(error || resolveError) && <p className="text-xs text-red-400">{error || resolveError}</p>}
            {isImage && (
                <img src={displayUrl} alt="preview" className="max-h-32 rounded-lg border border-foreground/[0.08] object-contain" />
            )}
            {isVideo && (
                <video src={displayUrl} controls className="max-h-40 w-full rounded-lg border border-foreground/[0.08]" />
            )}
            {isUrl && !isImage && !isVideo && (
                <a href={displayUrl} target="_blank" rel="noreferrer" className="inline-block max-w-full truncate text-[11px] text-blue-400 hover:underline">
                    {isResourceId ? 'Open uploaded file' : decodeURIComponent(displayUrl.split('/').pop() || displayUrl)}
                </a>
            )}
        </div>
    );
}

function renderMediaUploadWidget(props: WidgetRenderProps): ReactElement {
    return <MediaUploadWidget {...props} />;
}

// ============================================================================
// Veo Image Upload Widget
// ============================================================================

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function VeoImageUploadWidget({ fieldKey, value, onChange, nodeId, workflowId }: WidgetRenderProps): ReactElement {
    const [previewUrl, setPreviewUrl] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);
    const inputRef = useRef<HTMLInputElement>(null);
    const { uploadFile, uploading, progress } = useResourceUpload();

    const isResourceId = (v: string) => UUID_RE.test(v.trim());

    // Resolve resourceId to a presigned URL for thumbnail preview
    useEffect(() => {
        if (!value || !isResourceId(value)) { setPreviewUrl(null); return; }
        let cancelled = false;
        sendEventAsync(ResourceDownloadUrlRequest.create({ resource_id: value.trim() }))
            .then(res => { if (!cancelled) setPreviewUrl(res.download_url); })
            .catch(() => {});
        return () => { cancelled = true; };
    }, [value]);

    const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (!file || !nodeId || !workflowId) return;
        if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) {
            setError('Only JPEG, PNG, or WebP images are supported.');
            return;
        }
        setError(null);
        try {
            const result = await uploadFile(file, workflowId, nodeId);
            onChange(fieldKey, result.resourceId);
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Upload failed');
        } finally {
            e.target.value = '';
        }
    };

    return (
        <div className="space-y-2">
            <input
                ref={inputRef}
                type="file"
                accept="image/jpeg,image/png,image/webp"
                className="hidden"
                onChange={handleFileSelect}
            />
            {/* Text field for URL / upstream reference, with upload button on the right */}
            <div className="flex items-center gap-1.5">
                <div className="flex-1 min-w-0">
                    <DroppableTextField
                        fieldKey={fieldKey}
                        value={isResourceId(value) ? '' : (value || '')}
                        onChange={v => onChange(fieldKey, v)}
                        placeholder="Paste URL or drag a reference"
                    />
                </div>
                <button
                    onClick={() => inputRef.current?.click()}
                    disabled={uploading}
                    title="Upload image from file"
                    className="flex-none flex items-center justify-center w-8 h-8 rounded-lg border border-border dark:border-white/[0.08] bg-foreground/[0.03] hover:bg-foreground/[0.08] text-muted-foreground dark:text-white/50 hover:text-foreground/80 transition-colors disabled:opacity-40"
                >
                    {uploading ? <Loader2 size={14} className="animate-spin" /> : <Upload size={14} />}
                </button>
            </div>
            {uploading && <UploadProgressBar fraction={progress ?? 0} className="h-0.5" />}
            {/* Thumbnail preview when an image was uploaded (value is a resourceId) */}
            {isResourceId(value) && previewUrl && (
                <div className="relative rounded-lg overflow-hidden border border-border dark:border-white/[0.08] group">
                    <img src={previewUrl} alt="First frame" className="w-full h-28 object-cover" />
                    <button
                        onClick={() => onChange(fieldKey, '')}
                        className="absolute top-2 right-2 p-1 rounded-full bg-black/60 text-muted-foreground dark:text-white/70 hover:text-foreground opacity-0 group-hover:opacity-100 transition-opacity"
                    >
                        <X size={14} />
                    </button>
                </div>
            )}
            {error && <p className="text-xs text-red-600 dark:text-red-400">{error}</p>}
        </div>
    );
}

function renderVeoImageUploadWidget(props: WidgetRenderProps): ReactElement {
    return <VeoImageUploadWidget {...props} />;
}

// ============================================================================
// Gemini Multi-Image Upload Widget
// ============================================================================

function GeminiMultiImageUploadWidget({ fieldKey, value, onChange, nodeId, workflowId }: WidgetRenderProps): ReactElement {
    const { uploadFile } = useResourceUpload();

    // Parse stored value into array of entries.
    // Supports: empty → [''], single URL/UUID → [value], JSON array → parsed list.
    const parseEntries = (v: string): string[] => {
        const t = (v || '').trim();
        if (!t) return [''];
        if (t.startsWith('[')) {
            try {
                const p = JSON.parse(t);
                if (Array.isArray(p) && p.length > 0) return p;
            } catch {}
        }
        return [t];
    };

    const [entries, setEntries] = useState<string[]>(() => parseEntries(value));
    const [uploading, setUploading] = useState<number | null>(null);
    const [uploadFraction, setUploadFraction] = useState(0);
    const [errors, setErrors] = useState<Record<number, string>>({});
    const [previews, setPreviews] = useState<Record<number, string>>({});
    const inputRefs = useRef<(HTMLInputElement | null)[]>([]);

    // Sync local entries state when value prop changes externally (YJS sync / node switch)
    // Only update if the parsed result actually differs from current local state to avoid
    // fighting with in-progress user edits.
    useEffect(() => {
        const newEntries = parseEntries(value);
        setEntries(prev =>
            JSON.stringify(prev) === JSON.stringify(newEntries) ? prev : newEntries
        );
    }, [value]); // eslint-disable-line react-hooks/exhaustive-deps

    // Resolve resource UUIDs to presigned preview URLs
    useEffect(() => {
        entries.forEach((entry, i) => {
            if (entry && UUID_RE.test(entry.trim())) {
                sendEventAsync(ResourceDownloadUrlRequest.create({ resource_id: entry.trim() }))
                    .then(res => setPreviews(p => ({ ...p, [i]: res.download_url })))
                    .catch(() => {});
            } else {
                setPreviews(p => { const n = { ...p }; delete n[i]; return n; });
            }
        });
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [JSON.stringify(entries)]);

    const commit = (next: string[]) => {
        const filtered = next.filter(e => e.trim());
        if (filtered.length === 0) onChange(fieldKey, '');
        else if (filtered.length === 1) onChange(fieldKey, filtered[0]);
        else onChange(fieldKey, JSON.stringify(filtered));
    };

    const setEntry = (i: number, v: string) => {
        const next = [...entries];
        next[i] = v;
        setEntries(next);
        commit(next);
    };

    const removeEntry = (i: number) => {
        const next = entries.filter((_, j) => j !== i);
        const ne = next.length === 0 ? [''] : next;
        // Re-index previews
        setPreviews(p => {
            const n: Record<number, string> = {};
            Object.entries(p).forEach(([k, pv]) => {
                const ki = Number(k);
                if (ki !== i) n[ki < i ? ki : ki - 1] = pv;
            });
            return n;
        });
        setErrors(e => {
            const n: Record<number, string> = {};
            Object.entries(e).forEach(([k, ev]) => {
                const ki = Number(k);
                if (ki !== i) n[ki < i ? ki : ki - 1] = ev;
            });
            return n;
        });
        setEntries(ne);
        commit(ne);
    };

    const handleUpload = async (i: number, file: File) => {
        if (!nodeId || !workflowId) return;
        if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) {
            setErrors(e => ({ ...e, [i]: 'Only JPEG, PNG, or WebP supported.' }));
            return;
        }
        setUploading(i);
        setUploadFraction(0);
        setErrors(e => { const n = { ...e }; delete n[i]; return n; });
        try {
            const result = await uploadFile(file, workflowId, nodeId, setUploadFraction);
            setEntry(i, result.resourceId);
        } catch (err) {
            setErrors(e => ({ ...e, [i]: err instanceof Error ? err.message : 'Upload failed' }));
        } finally {
            setUploading(null);
        }
    };

    return (
        <div className="space-y-2">
            {entries.map((entry, i) => (
                <div key={i} className="space-y-1.5">
                    <input
                        ref={el => { inputRefs.current[i] = el; }}
                        type="file"
                        accept="image/jpeg,image/png,image/webp"
                        className="hidden"
                        onChange={e => { const f = e.target.files?.[0]; if (f) handleUpload(i, f); e.target.value = ''; }}
                    />
                    <div className="flex items-center gap-1.5">
                        <div className="flex-1 min-w-0">
                            <DroppableTextField
                                fieldKey={`${fieldKey}_${i}`}
                                value={UUID_RE.test(entry.trim()) ? '' : entry}
                                onChange={v => setEntry(i, v)}
                                placeholder="Paste URL or drag a reference"
                            />
                        </div>
                        <button
                            onClick={() => inputRefs.current[i]?.click()}
                            disabled={uploading === i}
                            title="Upload image"
                            className="flex-none flex items-center justify-center w-8 h-8 rounded-lg border border-border dark:border-white/[0.08] bg-foreground/[0.03] hover:bg-foreground/[0.08] text-muted-foreground dark:text-white/50 hover:text-foreground/80 transition-colors disabled:opacity-40"
                        >
                            {uploading === i ? <Loader2 size={14} className="animate-spin" /> : <Upload size={14} />}
                        </button>
                        {entries.length > 1 && (
                            <button
                                onClick={() => removeEntry(i)}
                                title="Remove image"
                                className="flex-none flex items-center justify-center w-8 h-8 rounded-lg border border-border dark:border-white/[0.08] bg-foreground/[0.03] hover:bg-foreground/[0.08] text-muted-foreground dark:text-white/50 hover:text-red-400 transition-colors"
                            >
                                <X size={14} />
                            </button>
                        )}
                    </div>
                    {uploading === i && <UploadProgressBar fraction={uploadFraction} className="h-0.5" />}
                    {UUID_RE.test(entry.trim()) && previews[i] && (
                        <div className="relative rounded-lg overflow-hidden border border-border dark:border-white/[0.08] group">
                            <img src={previews[i]} alt={`Reference ${i + 1}`} className="w-full h-24 object-cover" />
                            <button
                                onClick={() => setEntry(i, '')}
                                className="absolute top-2 right-2 p-1 rounded-full bg-black/60 text-muted-foreground dark:text-white/70 hover:text-foreground opacity-0 group-hover:opacity-100 transition-opacity"
                            >
                                <X size={14} />
                            </button>
                        </div>
                    )}
                    {errors[i] && <p className="text-xs text-red-600 dark:text-red-400">{errors[i]}</p>}
                </div>
            ))}
            {entries.length < 5 && (
                <button
                    onClick={() => setEntries(prev => [...prev, ''])}
                    className="flex items-center gap-1.5 text-xs text-muted-foreground/70 dark:text-white/40 hover:text-muted-foreground dark:hover:text-white/70 transition-colors"
                >
                    <Plus size={12} /> Add image
                </button>
            )}
        </div>
    );
}

function renderGeminiMultiImageUploadWidget(props: WidgetRenderProps): ReactElement {
    return <GeminiMultiImageUploadWidget {...props} />;
}

// ============================================================================
// Widget Registry
// ============================================================================

type WidgetRenderer = (props: WidgetRenderProps) => ReactElement;

/**
 * Registry mapping ui:widget values to their renderer functions.
 * All widgets defined here are automatically available in both NodeConfig and generation panel.
 */
const WIDGET_REGISTRY: Record<string, WidgetRenderer> = {
    'schedule': renderScheduleWidget,
    'schedules': renderSchedulesWidget,
    'nextRun': renderNextRunWidget,
    'python_editor': renderPythonEditorWidget,
    'code_editor': renderCodeEditorWidget,
    'function_inputs': renderFunctionInputsWidget,
    'tool_parameters': renderToolParametersWidget,
    'form_fields': renderFormFieldsWidget,
    'approval_fields': renderApprovalFieldsWidget,
    'switch_cases': renderSwitchCasesWidget,
    'switch_default_output': renderSwitchDefaultOutputWidget,
    'webhook': renderWebhookWidget,
    'email_trigger': (props) => <EmailTriggerField {...props} />,
    'readonly': renderReadonlyWidget,
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
    'file_browser': renderFileBrowserWidget,
    'text_upload_textarea': renderTextUploadTextareaWidget,
    'media_upload': renderMediaUploadWidget,
    'veo_image_upload': renderVeoImageUploadWidget,
    'gemini_multi_image_upload': renderGeminiMultiImageUploadWidget,
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

    if (widgetType && WIDGET_REGISTRY[widgetType]) {
        return WIDGET_REGISTRY[widgetType](props);
    }

    return null;
}

/**
 * Check if a field has a widget that we handle in the registry.
 */
export function hasRegisteredWidget(fieldSchema: any): boolean {
    const widgetType = fieldSchema?.['ui:widget'];
    return widgetType ? widgetType in WIDGET_REGISTRY : false;
}

/**
 * Get the list of all registered widget types.
 */
export function getRegisteredWidgetTypes(): string[] {
    return Object.keys(WIDGET_REGISTRY);
}
