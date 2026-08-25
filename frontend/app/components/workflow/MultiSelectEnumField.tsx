// MultiSelectEnumField — multi-select dropdown with chips for array-typed enum
// fields (JSON schema `type: array` with a static enum/items.enum + enumNames).
// Emits a string[] (fixing the "must be array" bug on array-enum fields, e.g. the
// Pipedrive trigger's event_types). Mirrors the app's standard multi-select-chips
// UX (WorkflowPickerWidget): selected values as removable chips above, a
// click-to-open search dropdown below — but over a STATIC option list instead of
// a dynamic loader.

import { type ReactElement, useState, useRef, useEffect, useMemo } from 'react';
import { X, ChevronDown } from 'lucide-react';
import { fuzzyFilter } from '~/utils/fuzzySearch';

const inputClasses = "w-full px-3 py-2 rounded-lg border border-foreground/[0.08] bg-card dark:bg-foreground/[0.03] text-foreground text-sm outline-none placeholder:text-foreground/30 focus:border-foreground/20 focus:bg-foreground/[0.05]";

interface MultiSelectEnumFieldProps {
    fieldKey: string;
    value: string[];
    enumValues: string[];
    enumLabels?: string[];
    onChange: (key: string, value: string[]) => void;
    placeholder?: string;
}

export function MultiSelectEnumField({
    fieldKey,
    value,
    enumValues,
    enumLabels,
    onChange,
    placeholder,
}: MultiSelectEnumFieldProps): ReactElement {
    const selected = Array.isArray(value) ? value : value ? [value] : [];
    const [isOpen, setIsOpen] = useState(false);
    const [search, setSearch] = useState('');
    const containerRef = useRef<HTMLDivElement>(null);

    const labelFor = (v: string) => {
        const i = enumValues.indexOf(v);
        return i >= 0 && enumLabels?.[i] ? enumLabels[i] : v;
    };

    // Close on outside click
    useEffect(() => {
        const handler = (e: MouseEvent) => {
            if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
                setIsOpen(false);
                setSearch('');
            }
        };
        document.addEventListener('mousedown', handler);
        return () => document.removeEventListener('mousedown', handler);
    }, []);

    const addValue = (v: string) => {
        if (!selected.includes(v)) onChange(fieldKey, [...selected, v]);
        setSearch('');
    };
    const removeValue = (v: string) => onChange(fieldKey, selected.filter(x => x !== v));

    const filtered = useMemo(() => {
        const available = enumValues
            .map((v, i) => ({ value: v, label: enumLabels?.[i] || v }))
            .filter(o => !selected.includes(o.value));
        return fuzzyFilter(available, search, o => [
            { text: o.label.toLowerCase(), weight: 1, fuzzy: true },
            { text: o.value.toLowerCase(), weight: 0.6, fuzzy: true },
        ]);
    }, [search, enumValues, enumLabels, selected]);

    return (
        <div ref={containerRef} className="space-y-1.5">
            {/* Selected values as chips */}
            {selected.length > 0 && (
                <div className="flex flex-wrap gap-1">
                    {selected.map(v => (
                        <span
                            key={v}
                            className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-foreground/[0.06] border border-foreground/[0.1] text-xs text-muted-foreground dark:text-zinc-300"
                        >
                            <span className="truncate max-w-[160px]">{labelFor(v)}</span>
                            <button
                                type="button"
                                onClick={() => removeValue(v)}
                                className="text-muted-foreground/70 dark:text-zinc-500 hover:text-red-600 dark:hover:text-red-400 transition-colors"
                                aria-label={`Remove ${labelFor(v)}`}
                            >
                                <X className="w-3 h-3" />
                            </button>
                        </span>
                    ))}
                </div>
            )}

            {/* Dropdown trigger / search */}
            <div className="relative">
                <div
                    className={`${inputClasses} py-1.5 flex items-center gap-1.5 cursor-pointer`}
                    onClick={() => setIsOpen(!isOpen)}
                >
                    {isOpen ? (
                        <input
                            autoFocus
                            type="text"
                            value={search}
                            onChange={e => setSearch(e.target.value)}
                            onClick={e => e.stopPropagation()}
                            placeholder="Search..."
                            className="flex-1 bg-transparent outline-none text-sm text-foreground placeholder:text-foreground/30"
                        />
                    ) : (
                        <span className="flex-1 text-foreground/30 text-sm">{placeholder || 'Add…'}</span>
                    )}
                    <ChevronDown className={`w-3.5 h-3.5 text-muted-foreground/70 dark:text-zinc-500 flex-none transition-transform ${isOpen ? 'rotate-180' : ''}`} />
                </div>

                {isOpen && (
                    <div className="absolute z-50 w-full mt-1 max-h-40 overflow-y-auto rounded-lg border border-foreground/[0.08] bg-card shadow-xl">
                        {filtered.length === 0 && (
                            <div className="px-3 py-2 text-xs text-muted-foreground/70 dark:text-zinc-500 italic">
                                {search ? 'No matches' : 'Nothing more to add'}
                            </div>
                        )}
                        {filtered.map(o => (
                            <button
                                key={o.value}
                                type="button"
                                className="w-full text-left px-3 py-1.5 text-sm text-muted-foreground dark:text-zinc-300 hover:bg-foreground/[0.06] hover:text-foreground transition-colors"
                                onClick={() => addValue(o.value)}
                            >
                                {o.label}
                            </button>
                        ))}
                    </div>
                )}
            </div>
        </div>
    );
}
