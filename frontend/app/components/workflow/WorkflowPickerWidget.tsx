// WorkflowPickerWidget — multi-select dropdown for choosing workflows by name.
// Used by the NoClick node's "Specific workflows" scope config to pick allowed workflow IDs.
// Loads options dynamically from the backend via the load_options socket event.

import { type ReactElement, useState, useRef, useEffect, useCallback } from 'react';
import { Loader2, X, ChevronDown } from 'lucide-react';
import { sendEventAsync } from '~/lib/socket-sender';
import { fuzzyFilter } from '~/utils/fuzzySearch';

const inputClasses = "w-full px-3 py-2 rounded-lg border border-border dark:border-white/[0.08] bg-foreground/[0.03] text-foreground text-sm outline-none placeholder:text-[hsl(var(--placeholder))] focus:border-foreground/20 focus:bg-foreground/[0.05]";

interface WorkflowPickerWidgetProps {
    fieldKey: string;
    value: any;
    onChange: (key: string, value: any) => void;
    nodeType?: string;
}

export function WorkflowPickerWidget({ fieldKey, value, onChange, nodeType }: WorkflowPickerWidgetProps): ReactElement {
    // Parse comma-separated IDs into array
    const selectedIds: string[] = typeof value === 'string' && value.trim()
        ? value.split(',').map((s: string) => s.trim()).filter(Boolean)
        : [];

    // Label cache: workflow ID → name
    const [labels, setLabels] = useState<Record<string, string>>({});
    const [options, setOptions] = useState<{ value: string; label: string }[]>([]);
    const [loading, setLoading] = useState(false);
    const [isOpen, setIsOpen] = useState(false);
    const [search, setSearch] = useState('');
    const containerRef = useRef<HTMLDivElement>(null);

    const loadOptions = useCallback(async () => {
        setLoading(true);
        try {
            const { WorkflowNodeLoadOptionsRequest } = await import('~/types/socket-events.generated');
            const resp = await sendEventAsync(WorkflowNodeLoadOptionsRequest.create({
                node_type: nodeType || 'noclick',
                field_name: 'allowed_workflow_ids',
                credential_id: '',
                context: {},
            }));
            const opts = resp.options || [];
            setOptions(opts);
            const newLabels: Record<string, string> = {};
            for (const o of opts) newLabels[o.value] = o.label;
            setLabels(prev => ({ ...prev, ...newLabels }));
        } catch {
            // ignore
        } finally {
            setLoading(false);
        }
    }, [nodeType]);

    // Load options when dropdown opens
    useEffect(() => {
        if (isOpen && options.length === 0) loadOptions();
    }, [isOpen, loadOptions, options.length]);

    // Close on outside click
    useEffect(() => {
        const handler = (e: MouseEvent) => {
            if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
                setIsOpen(false);
            }
        };
        document.addEventListener('mousedown', handler);
        return () => document.removeEventListener('mousedown', handler);
    }, []);

    const addId = (id: string) => {
        if (!selectedIds.includes(id)) {
            const next = [...selectedIds, id];
            onChange(fieldKey, next.join(','));
        }
        setSearch('');
    };

    const removeId = (id: string) => {
        const next = selectedIds.filter(x => x !== id);
        onChange(fieldKey, next.join(','));
    };

    const filtered = fuzzyFilter(
        options.filter(o => !selectedIds.includes(o.value)),
        search,
        o => [{ text: o.label.toLowerCase(), weight: 1, fuzzy: true }]
    );

    return (
        <div ref={containerRef} className="space-y-1.5">
            {/* Selected workflows as chips */}
            {selectedIds.length > 0 && (
                <div className="flex flex-wrap gap-1">
                    {selectedIds.map(id => (
                        <span
                            key={id}
                            className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-foreground/[0.06] border border-foreground/[0.1] text-xs text-foreground/80"
                        >
                            <span className="truncate max-w-[140px]">{labels[id] || id.slice(0, 8) + '…'}</span>
                            <button
                                type="button"
                                onClick={() => removeId(id)}
                                className="text-muted-foreground dark:text-zinc-500 hover:text-red-400 transition-colors"
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
                            placeholder="Search workflows..."
                            className="flex-1 bg-transparent outline-none text-sm text-foreground placeholder:text-[hsl(var(--placeholder))]"
                        />
                    ) : (
                        <span className="flex-1 text-muted-foreground/70 dark:text-white/30 text-sm">Add workflow...</span>
                    )}
                    {loading ? (
                        <Loader2 className="w-3.5 h-3.5 text-muted-foreground dark:text-zinc-500 animate-spin flex-none" />
                    ) : (
                        <ChevronDown className={`w-3.5 h-3.5 text-muted-foreground dark:text-zinc-500 flex-none transition-transform ${isOpen ? 'rotate-180' : ''}`} />
                    )}
                </div>

                {isOpen && (
                    <div className="absolute z-50 w-full mt-1 max-h-40 overflow-y-auto rounded-lg border border-border dark:border-white/[0.08] bg-card shadow-xl">
                        {filtered.length === 0 && !loading && (
                            <div className="px-3 py-2 text-xs text-muted-foreground dark:text-zinc-500 italic">
                                {search ? 'No matching workflows' : 'No more workflows to add'}
                            </div>
                        )}
                        {filtered.map(o => (
                            <button
                                key={o.value}
                                type="button"
                                className="w-full text-left px-3 py-1.5 text-sm text-foreground/80 hover:bg-foreground/[0.06] hover:text-foreground transition-colors"
                                onClick={() => addId(o.value)}
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
