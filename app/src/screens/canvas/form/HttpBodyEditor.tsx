// HttpBodyEditor - composite "Body" editor for the HTTP Request node. Renders
// the body-type selector AND the matching editor (JSON / Form / Raw) together
// in one bordered section, so body-related fields read as one group instead of
// being scattered among the node's other fields. Assigned to the body_type
// field via ui:widget "http_body"; it writes the sibling body / body_form /
// content_type_override fields through the same onChange path.

import { DroppableTextField } from './DroppableTextField';
import { KeyValueEditor } from './KeyValueEditor';
import type { WidgetRenderProps } from './schemaWidgetRegistry';

export function HttpBodyEditor({ fieldKey, fieldSchema, value, onChange, config }: WidgetRenderProps) {
    const options: string[] = fieldSchema?.enum || ['none', 'json', 'form_urlencoded', 'raw'];
    const labels: string[] = fieldSchema?.enumNames || options;
    const bodyType = (value ?? fieldSchema?.default ?? 'none') as string;
    const cfg = (config || {}) as Record<string, any>;

    return (
        <div className="rounded-lg border border-foreground/[0.06] bg-foreground/[0.02] p-2 space-y-2.5">
            <div className="inline-flex w-full gap-0.5 rounded-lg border border-foreground/[0.06] bg-foreground/[0.03] p-0.5">
                {options.map((opt, i) => (
                    <button
                        key={opt}
                        type="button"
                        onClick={() => onChange(fieldKey, opt)}
                        className={`flex-1 rounded-md px-2 py-1.5 text-xs transition-colors ${
                            bodyType === opt
                                ? 'bg-foreground/[0.12] text-foreground shadow-sm'
                                : 'text-muted-foreground hover:text-foreground'
                        }`}
                    >
                        {labels[i] ?? opt}
                    </button>
                ))}
            </div>

            {bodyType === 'none' && (
                <p className="px-0.5 text-[11px] text-muted-foreground/70 dark:text-zinc-500">No request body will be sent.</p>
            )}

            {bodyType === 'json' && (
                <DroppableTextField
                    fieldKey="body"
                    value={cfg.body || ''}
                    onChange={(v) => onChange('body', v)}
                    multiline
                    rows={6}
                    placeholder={'{\n  "key": "value"\n}'}
                    className="text-xs font-mono"
                />
            )}

            {bodyType === 'raw' && (
                <div className="space-y-2">
                    <DroppableTextField
                        fieldKey="content_type_override"
                        value={cfg.content_type_override || ''}
                        onChange={(v) => onChange('content_type_override', v)}
                        placeholder="Content-Type (default text/plain)"
                        className="text-xs"
                    />
                    <DroppableTextField
                        fieldKey="body"
                        value={cfg.body || ''}
                        onChange={(v) => onChange('body', v)}
                        multiline
                        rows={6}
                        placeholder="Raw request body"
                        className="text-xs font-mono"
                    />
                </div>
            )}

            {bodyType === 'form_urlencoded' && (
                <KeyValueEditor
                    fieldKey="body_form"
                    value={cfg.body_form}
                    onChange={(rows) => onChange('body_form', rows)}
                    keyPlaceholder="field"
                    valuePlaceholder="value"
                    addLabel="Add field"
                />
            )}
        </div>
    );
}
