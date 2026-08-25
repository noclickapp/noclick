// SchedulesWidget - Multi-schedule container for the cron trigger node.
// Renders a list of ScheduleWidget instances with add/remove buttons.
// Supports whole-entry drag-and-drop — each entry can be either a manual
// schedule config or a reference to another node's schedule output.

import { useCallback, useEffect, useRef } from 'react';
import { useDroppable } from '@dnd-kit/core';
import { Plus, Trash2, Link2, X } from 'lucide-react';
import { ScheduleWidget } from './ScheduleWidget';
import type { ScheduleConfig } from './ScheduleWidget';
import { registerInsertReference, unregisterInsertReference } from './DroppableTextField';
import { decodeLegacyHtmlEntities } from './legacyConfigParsing';

// A schedule entry is either a config object (manual) or a reference string
type ScheduleEntry = ScheduleConfig | string;

interface SchedulesWidgetProps {
    value: ScheduleEntry[];
    onChange: (value: ScheduleEntry[]) => void;
    fieldKey: string;
}

const DEFAULT_SCHEDULE: ScheduleConfig = {
    frequency: 'day', hour: 9, minute: 0, dayOfWeek: 1, dayOfMonth: 1,
};

const isReference = (val: unknown): val is string =>
    typeof val === 'string' && /^\{\{[^}]+\}\}$/.test(val.trim());

const refLabel = (val: string): string => {
    const inner = val.replace(/^\{\{|\}\}$/g, '');
    const parts = inner.split('.');
    return parts[parts.length - 1];
};

function parseSchedules(value: unknown): ScheduleEntry[] {
    if (Array.isArray(value)) return value;
    // Single schedule object
    if (value && typeof value === 'object' && !Array.isArray(value) && 'frequency' in (value as Record<string, unknown>)) {
        return [value as ScheduleConfig];
    }
    if (typeof value === 'string' && value.trim()) {
        // Single reference string
        if (isReference(value)) return [value];
        try {
            const decoded = decodeLegacyHtmlEntities(value);
            const parsed = JSON.parse(decoded);
            if (Array.isArray(parsed)) return parsed;
            if (parsed && typeof parsed === 'object' && 'frequency' in parsed) return [parsed];
        } catch { /* ignore */ }
    }
    return [];
}

// ---------------------------------------------------------------------------
// ReferenceBadge – shown when a schedule entry is a {{…}} reference
// ---------------------------------------------------------------------------
function ReferenceBadge({ value, onClear }: { value: string; onClear: () => void }) {
    return (
        <span className="inline-flex items-center gap-1 px-2 py-1.5 rounded-lg text-xs font-mono
            bg-secondary dark:bg-zinc-700/60 text-foreground border border-muted-foreground/40 dark:border-zinc-600/50">
            <Link2 className="h-3 w-3 text-muted-foreground shrink-0" />
            <span className="truncate max-w-[180px]" title={value}>{refLabel(value)}</span>
            <button
                type="button"
                onClick={onClear}
                className="ml-0.5 text-muted-foreground dark:text-zinc-500 hover:text-foreground transition-colors"
            >
                <X className="h-3 w-3" />
            </button>
        </span>
    );
}

// ---------------------------------------------------------------------------
// DroppableScheduleEntry – wraps an entire schedule entry with D&D support.
// When a json-field-reference is dropped, replaces the whole entry with a reference.
// ---------------------------------------------------------------------------
function DroppableScheduleEntry({
    index,
    fieldKey,
    entry,
    onUpdate,
    onRemove,
}: {
    index: number;
    fieldKey: string;
    entry: ScheduleEntry;
    onUpdate: (index: number, value: ScheduleEntry) => void;
    onRemove: (index: number) => void;
}) {
    const entryFieldKey = `${fieldKey}-${index}`;
    const { setNodeRef, isOver, active } = useDroppable({
        id: `droppable-field-${entryFieldKey}`,
        data: { type: 'config-field', fieldKey: entryFieldKey },
    });
    const isJsonFieldDrag = active?.data?.current?.type === 'json-field-reference';
    const entryIsRef = isReference(entry);
    const showDropHint = isOver && isJsonFieldDrag;
    const showDragActive = isJsonFieldDrag && !isOver && !entryIsRef;

    // Register in insertReferenceRegistry so FlowCanvas.handleDragEnd can insert
    const insertRef = useRef<{ fn: (ref: string) => void }>({
        fn: (ref: string) => onUpdate(index, ref),
    });
    insertRef.current.fn = (ref: string) => onUpdate(index, ref);

    useEffect(() => {
        registerInsertReference(entryFieldKey, insertRef.current);
        return () => { unregisterInsertReference(entryFieldKey); };
    }, [entryFieldKey]);

    const clearRef = useCallback(() => {
        onUpdate(index, { ...DEFAULT_SCHEDULE });
    }, [index, onUpdate]);

    return (
        <div
            ref={setNodeRef}
            className={`relative flex items-start gap-2 rounded-lg p-1 -m-1 transition-all ${
                showDropHint ? 'ring-2 ring-muted-foreground/40 dark:ring-zinc-500/40' :
                showDragActive ? 'outline outline-1 outline-dashed outline-muted-foreground/40 dark:outline-zinc-500/40' : ''
            }`}
        >
            <div className="flex-1 min-w-0">
                {entryIsRef ? (
                    <ReferenceBadge value={entry} onClear={clearRef} />
                ) : (
                    <ScheduleWidget
                        value={entry}
                        onChange={(v) => onUpdate(index, v)}
                    />
                )}
            </div>
            <button
                type="button"
                onClick={() => onRemove(index)}
                className="flex-shrink-0 p-1.5 mt-0.5 text-muted-foreground dark:text-zinc-500 hover:text-red-400 hover:bg-red-500/10 rounded transition-colors"
                title="Remove schedule"
            >
                <Trash2 className="w-3.5 h-3.5" />
            </button>
            {showDropHint && !entryIsRef && (
                <div className="absolute inset-0 flex items-center justify-center bg-card/90 rounded-lg
                    pointer-events-none border-2 border-dashed border-muted-foreground/50 dark:border-zinc-500/50 z-10">
                    <span className="text-xs text-foreground/80 font-medium">Drop to replace schedule</span>
                </div>
            )}
        </div>
    );
}

// ---------------------------------------------------------------------------
// SchedulesWidget
// ---------------------------------------------------------------------------
export function SchedulesWidget({ value, onChange, fieldKey }: SchedulesWidgetProps) {
    const schedules = parseSchedules(value);

    const addSchedule = () => {
        onChange([...schedules, { ...DEFAULT_SCHEDULE }]);
    };

    const removeSchedule = (index: number) => {
        onChange(schedules.filter((_, i) => i !== index));
    };

    const updateSchedule = (index: number, newEntry: ScheduleEntry) => {
        const updated = [...schedules];
        updated[index] = newEntry;
        onChange(updated);
    };

    return (
        <div className="space-y-3">
            {schedules.length === 0 && (
                <p className="text-xs text-muted-foreground dark:text-zinc-500 italic">No schedules configured — cron trigger is disabled.</p>
            )}

            {schedules.map((entry, index) => (
                <DroppableScheduleEntry
                    key={index}
                    index={index}
                    fieldKey={fieldKey}
                    entry={entry}
                    onUpdate={updateSchedule}
                    onRemove={removeSchedule}
                />
            ))}

            <button
                type="button"
                onClick={addSchedule}
                className="flex items-center gap-1.5 px-2 py-1 text-xs text-muted-foreground hover:text-foreground/80 hover:bg-foreground/[0.04] rounded transition-colors"
            >
                <Plus className="w-3.5 h-3.5" />
                <span>Add schedule</span>
            </button>
        </div>
    );
}
