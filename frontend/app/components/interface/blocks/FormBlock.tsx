// Unified form block: renders the form node's fields with PERSISTENT values
// (config.values — Valtio/YJS state, absorbed from the former ConfigFormBlock in
// the 2026-07 merge) plus the submit affordance that starts a workflow run.
// Edits persist instantly and survive reloads; Submit sends the merged view so
// downstream references resolve identically whether or not execute() runs.

import { useCallback, useMemo, useState } from 'react';
import type { BlockComponentProps, FormField } from '../types';
import { FieldRenderer, normalizeFields } from './FieldRenderer';

/** Parse a stored default (may be a JSON-encoded array/object) into a live value. */
function parseDefault(raw: unknown): unknown {
    if (typeof raw !== 'string') return raw;
    const s = raw.trim();
    if (s.startsWith('[') || s.startsWith('{')) {
        try {
            return JSON.parse(s);
        } catch {
            /* fall through to the raw string */
        }
    }
    return raw;
}

/** Initial values so references + submissions resolve before user edits:
 *  schedule fields need a structural default, others use their declared default. */
function getFieldDefaults(fields: FormField[]): Record<string, unknown> {
    const defaults: Record<string, unknown> = {};
    for (const f of fields) {
        if (f.type === 'schedule') {
            defaults[f.id] = [
                {
                    frequency: 'day',
                    hour: 9,
                    minute: 0,
                    dayOfWeek: 1,
                    dayOfMonth: 1,
                },
            ];
        } else if (f.defaultValue !== undefined && f.defaultValue !== null) {
            defaults[f.id] = parseDefault(f.defaultValue);
        }
    }
    return defaults;
}

const DEFAULT_FIELDS: FormField[] = [
    { id: 'name', type: 'text', label: 'Name', placeholder: 'Enter your name' },
    {
        id: 'email',
        type: 'text',
        label: 'Email',
        placeholder: 'Enter your email',
    },
];

export function FormBlock({
    config,
    onConfigChange,
    onSubmit,
    isReadOnly,
    onInteraction,
}: BlockComponentProps) {
    const fields = useMemo(() => {
        let raw = config.fields as unknown;
        // Parse JSON string (MCP/backend may store fields as a serialized string)
        if (typeof raw === 'string' && raw.trim()) {
            try {
                raw = JSON.parse(raw);
            } catch {
                /* ignore */
            }
        }
        if (!Array.isArray(raw) || raw.length === 0) return DEFAULT_FIELDS;
        return normalizeFields(raw);
    }, [config.fields]);

    // Read-only contexts (share pages, embeds) can't persist — fall back to
    // local state so the form stays typable there.
    const [localValues, setLocalValues] = useState<Record<string, unknown>>({});

    // Persistent values live in config.values (workflow node config — Valtio/auto-save)
    const values = useMemo(() => {
        let raw = config.values as unknown;
        if (typeof raw === 'string' && raw.trim()) {
            try {
                raw = JSON.parse(raw);
            } catch {
                /* ignore */
            }
        }
        const stored = (raw as Record<string, unknown>) ?? {};
        const defaults = getFieldDefaults(fields);
        const needsDefaults = Object.keys(defaults).some((k) => !(k in stored));
        if (needsDefaults && !isReadOnly) {
            const merged = { ...defaults, ...stored };
            // Persist the defaults immediately so references resolve
            onConfigChange({ ...config, values: merged });
            return merged;
        }
        return needsDefaults ? { ...getFieldDefaults(fields), ...stored } : stored;
    }, [config.values, fields]); // eslint-disable-line react-hooks/exhaustive-deps

    const effectiveValues = useMemo(
        () => (isReadOnly ? { ...values, ...localValues } : values),
        [isReadOnly, values, localValues]
    );

    const updateValue = useCallback(
        (fieldId: string, value: unknown) => {
            if (isReadOnly) {
                setLocalValues((prev) => ({ ...prev, [fieldId]: value }));
                return;
            }
            onConfigChange({ ...config, values: { ...values, [fieldId]: value } });
        },
        [isReadOnly, values, config, onConfigChange]
    );

    const handleSubmit = useCallback(() => {
        if (isReadOnly) {
            onInteraction?.();
            return;
        }
        onSubmit?.(effectiveValues);
    }, [isReadOnly, onInteraction, onSubmit, effectiveValues]);

    return (
        <div className="w-full h-full flex flex-col overflow-auto">
            <div className="flex-1 p-4 space-y-6">
                {fields.map((field) => (
                    <FieldRenderer
                        key={field.id}
                        field={field}
                        value={effectiveValues[field.id]}
                        onChange={updateValue}
                    />
                ))}
            </div>
            {/* Read-only keeps the button as the interaction nudge; otherwise it
                only renders where submit is actually wired (hides the dead button
                the mobile canvas used to show). */}
            {(onSubmit || isReadOnly) && (
                <div className="px-4 pt-6 pb-4">
                    <button
                        type="button"
                        className="w-full py-2.5 px-3 rounded-md bg-primary hover:bg-primary/90 text-xs font-medium text-primary-foreground transition-colors"
                        onClick={handleSubmit}
                    >
                        {(config.submitLabel as string) || 'Submit'}
                    </button>
                </div>
            )}
        </div>
    );
}
