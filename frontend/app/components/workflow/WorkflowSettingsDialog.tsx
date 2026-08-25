// Dialog for configuring workflow-level settings. Backed by the
// `workflows.settings` JSONB column (merged on the backend). Two fields today:
//   - min_required_credits (Phase 2.1; legacy min_required_balance is read as a
//     fallback so existing workflows keep their value).
//   - error_handler_workflow_id — on failure, the backend fires the picked
//     workflow's on-error node with this run's error payload. Cross-workflow
//     error routing; the picker hides the current workflow and the backend
//     blocks self-target plus error-handler-of-error-handler recursion.
//
// Styled to match the canonical Settings design language used in
// /components/settings/* — white-opacity palette, rounded-lg inputs, and the
// Apple-style grouped-list card (rounded-xl + divide-y) so this dialog reads
// as part of the same surface as the full Settings views.

import { useState, useEffect, useRef, useCallback } from 'react';
import type { Node as FlowNode } from '@xyflow/react';
import { Coins, AlertTriangle, Braces, Loader2, ChevronDown, SlidersHorizontal, X } from 'lucide-react';
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DialogFooter,
} from '~/components/ui/dialog';
import { Button } from '~/components/ui/button';
import { sendEventWithCallback, sendEventAsync } from '~/lib/socket-sender';
import { WorkflowUpdateRequest } from '~/types/socket-events.generated';
import { fuzzyFilter } from '~/utils/fuzzySearch';
import { WorkflowVariablesView } from './variables/WorkflowVariablesView';
import type { WorkflowVariableDefinition } from '~/hooks/useWorkflowVariables';
import { toast } from 'sonner';

interface WorkflowSettingsDialogProps {
    isOpen: boolean;
    onOpenChange: (open: boolean) => void;
    workflowId: string;
    currentSettings: Record<string, unknown>;
    onSettingsChange: (settings: Record<string, unknown>) => void;
    /** For the Variables section's usage counts. */
    nodes?: FlowNode[];
    /** Section to open on — the canvas Variables FAB deep-links here. */
    initialSection?: 'general' | 'variables';
}

type WorkflowOption = { value: string; label: string };

// Shared input class — mirrors the canonical settings input (h-9, rounded-lg,
// white-opacity border + bg). Re-exported below so the picker stays in sync.
const settingsInputClass =
    'w-full h-9 px-3 text-sm bg-muted dark:bg-background/40 border border-border dark:border-foreground/[0.08] rounded-lg text-foreground placeholder:text-[hsl(var(--placeholder))] outline-none focus:border-foreground/20 transition-colors';

export function WorkflowSettingsDialog({
    isOpen,
    onOpenChange,
    workflowId,
    currentSettings,
    onSettingsChange,
    nodes = [],
    initialSection = 'general',
}: WorkflowSettingsDialogProps) {
    const [minCredits, setMinCredits] = useState('');
    const [variableDefs, setVariableDefs] = useState<WorkflowVariableDefinition[]>([]);
    const [section, setSection] = useState<'general' | 'variables'>('general');
    const [errorHandlerId, setErrorHandlerId] = useState<string>('');
    const [errorHandlerLabel, setErrorHandlerLabel] = useState<string>('');
    const [saving, setSaving] = useState(false);

    // Sync local state when dialog opens or settings change. Fall back to the
    // legacy min_required_balance key for workflows that haven't been re-saved
    // since Phase 2.1 — the backend reads it as credits.
    useEffect(() => {
        if (isOpen) {
            const val = currentSettings.min_required_credits ?? currentSettings.min_required_balance;
            setMinCredits(val != null && Number(val) > 0 ? String(val) : '');
            const handler = currentSettings.error_handler_workflow_id;
            setErrorHandlerId(typeof handler === 'string' ? handler : '');
            setVariableDefs(
                Array.isArray(currentSettings.variable_definitions)
                    ? (currentSettings.variable_definitions as WorkflowVariableDefinition[])
                    : []
            );
            setSection(initialSection);
        }
    }, [isOpen, currentSettings, initialSection]);

    // Per-section dirty state: the rail marks what changed, Save arms only
    // when something did. Compared against the loaded settings, not a
    // snapshot — a save echo naturally reads as clean again.
    const loadedMinCredits = (() => {
        const val = currentSettings.min_required_credits ?? currentSettings.min_required_balance;
        return val != null && Number(val) > 0 ? String(val) : '';
    })();
    const loadedHandler =
        typeof currentSettings.error_handler_workflow_id === 'string'
            ? currentSettings.error_handler_workflow_id
            : '';
    const loadedDefs = Array.isArray(currentSettings.variable_definitions)
        ? (currentSettings.variable_definitions as WorkflowVariableDefinition[])
        : [];
    const generalDirty = minCredits !== loadedMinCredits || errorHandlerId !== loadedHandler;
    const variablesDirty =
        JSON.stringify(variableDefs.filter((d) => d.name.trim())) !==
        JSON.stringify(loadedDefs);
    const dirty = generalDirty || variablesDirty;

    const perUserCount = variableDefs.filter((d) => d.name.trim() && d.per_user).length;
    const namedCount = variableDefs.filter((d) => d.name.trim()).length;

    const handleSave = () => {
        const parsed = minCredits === '' ? null : parseInt(minCredits, 10);
        if (parsed !== null && (isNaN(parsed) || parsed < 0)) {
            toast.error('Please enter a valid number of credits');
            return;
        }

        if (errorHandlerId && errorHandlerId === workflowId) {
            toast.error('A workflow cannot route its errors to itself');
            return;
        }

        setSaving(true);
        sendEventWithCallback(
            WorkflowUpdateRequest.create({
                workflow_id: workflowId,
                // Write the new key; explicitly null the legacy one so workflows
                // re-saved here stop carrying both. error_handler_workflow_id is
                // null when cleared so the backend merge wipes the prior value.
                settings: {
                    min_required_credits: parsed,
                    min_required_balance: null,
                    error_handler_workflow_id: errorHandlerId || null,
                    variable_definitions: variableDefs.filter((d) => d.name.trim()),
                },
            }),
            (response: { error?: string; workflow?: { settings?: Record<string, unknown> } }) => {
                setSaving(false);
                if (response.error) {
                    toast.error(response.error);
                } else {
                    const newSettings = response.workflow?.settings ?? {};
                    onSettingsChange(newSettings);
                    onOpenChange(false);
                    toast.success('Settings saved');
                }
            }
        );
    };

    return (
        <Dialog open={isOpen} onOpenChange={onOpenChange}>
            {/* Sidebar layout in the ModelPickerModal idiom: fixed-height frame,
                bordered section rail on the left, scrollable content pane.
                noAnimation keeps Radix Presence from waiting on an exit
                animation that never fires when the tab is hidden. */}
            <DialogContent
                noAnimation
                className="bg-background dark:bg-zinc-950 dark:bg-sunken border-border dark:border-white/[0.08] text-foreground max-w-2xl p-0 gap-0 overflow-hidden"
            >
                <div className="flex h-[min(560px,80vh)] flex-col">
                    <DialogHeader className="flex-shrink-0 border-b border-border/30 dark:border-zinc-700/30 px-5 py-4 pr-14">
                        <DialogTitle className="text-lg font-semibold text-foreground">
                            Workflow Settings
                        </DialogTitle>
                    </DialogHeader>

                    <div className="flex min-h-0 flex-1">
                        {/* Section rail: label + a live meta line, and a dot
                            on sections holding unsaved edits. */}
                        <div className="flex w-52 flex-shrink-0 flex-col gap-0.5 border-r border-border/30 dark:border-zinc-700/30 p-2">
                            {(
                                [
                                    {
                                        id: 'general',
                                        label: 'General',
                                        Icon: SlidersHorizontal,
                                        meta:
                                            minCredits || errorHandlerId
                                                ? [
                                                      minCredits ? `≥ ${minCredits} credits` : null,
                                                      errorHandlerId ? 'error routing on' : null,
                                                  ]
                                                      .filter(Boolean)
                                                      .join(' · ')
                                                : 'Runs & failure routing',
                                        isDirty: generalDirty,
                                    },
                                    {
                                        id: 'variables',
                                        label: 'Variables',
                                        Icon: Braces,
                                        meta: namedCount
                                            ? `${namedCount} defined${perUserCount ? ` · ${perUserCount} per-user` : ''}`
                                            : 'None yet',
                                        isDirty: variablesDirty,
                                    },
                                ] as const
                            ).map(({ id, label, Icon, meta, isDirty }) => (
                                <button
                                    key={id}
                                    onClick={() => setSection(id)}
                                    className={`flex w-full items-start gap-2.5 rounded-md px-2.5 py-2 text-left transition-colors ${
                                        section === id
                                            ? 'bg-secondary dark:bg-zinc-700/50'
                                            : 'hover:bg-accent dark:hover:bg-zinc-700/30'
                                    }`}
                                >
                                    <Icon
                                        className={`mt-0.5 h-3.5 w-3.5 shrink-0 ${
                                            section === id ? 'text-foreground/80' : 'text-muted-foreground/70'
                                        }`}
                                    />
                                    <span className="min-w-0 flex-1">
                                        <span
                                            className={`block text-[13px] ${
                                                section === id
                                                    ? 'font-medium text-foreground'
                                                    : 'text-muted-foreground'
                                            }`}
                                        >
                                            {label}
                                        </span>
                                        <span className="block truncate text-[11px] text-muted-foreground/60 dark:text-white/30">
                                            {meta}
                                        </span>
                                    </span>
                                    {isDirty && (
                                        <span
                                            title="Unsaved changes"
                                            className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-amber-400"
                                        />
                                    )}
                                </button>
                            ))}
                        </div>

                        {/* Content pane */}
                        <div className="min-w-0 flex-1 overflow-y-auto p-5">
                            {section === 'general' ? (
                                <div className="rounded-xl border border-border dark:border-white/[0.06] bg-card dark:bg-foreground/[0.03] divide-y divide-border dark:divide-foreground/[0.06]">
                                    <SettingRow
                                        icon={Coins}
                                        label="Minimum credits to run"
                                        description="Users must have at least this many credits this month. Leave blank for no minimum."
                                    >
                                        <input
                                            type="number"
                                            min="0"
                                            step="1"
                                            value={minCredits}
                                            onChange={(e) => setMinCredits(e.target.value)}
                                            placeholder="0"
                                            className={`${settingsInputClass} [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none`}
                                        />
                                    </SettingRow>

                                    <SettingRow
                                        icon={AlertTriangle}
                                        label="On error, run another workflow"
                                        description={
                                            errorHandlerLabel && errorHandlerId
                                                ? `Routing errors to ${errorHandlerLabel}. Pick a workflow with an On Error node.`
                                                : 'When this workflow fails, fire another workflow’s On Error trigger with the error payload.'
                                        }
                                    >
                                        <ErrorHandlerPicker
                                            selectedId={errorHandlerId}
                                            onSelectedLabelChange={setErrorHandlerLabel}
                                            onChange={setErrorHandlerId}
                                            excludeWorkflowId={workflowId}
                                        />
                                    </SettingRow>
                                </div>
                            ) : (
                                <>
                                    {/* Variables — author-declared parameters.
                                        Draft-local like every field here: Save
                                        commits, Cancel discards. */}
                                    <p className="mb-3 mt-0 text-xs leading-relaxed text-muted-foreground dark:text-white/40">
                                        Reference anywhere as{' '}
                                        <code className="rounded bg-foreground/[0.06] px-1 py-0.5 font-mono text-[11px]">
                                            {'{{vars.name}}'}
                                        </code>
                                        . Left without a value, a variable becomes a Setup step.
                                    </p>
                                    <WorkflowVariablesView
                                        embedded
                                        definitions={variableDefs}
                                        onChange={setVariableDefs}
                                        nodes={nodes}
                                    />
                                </>
                            )}
                        </div>
                    </div>

                    <DialogFooter className="flex-shrink-0 items-center gap-2 border-t border-border/30 dark:border-zinc-700/30 px-5 py-3 sm:justify-between sm:gap-0">
                        <span className="mr-auto hidden text-[11.5px] text-muted-foreground/60 dark:text-white/30 sm:block">
                            {dirty ? 'Save applies every section' : 'No unsaved changes'}
                        </span>
                        <div className="flex items-center gap-2">
                        <Button
                            variant="outline"
                            onClick={() => onOpenChange(false)}
                            className="h-10 bg-foreground/[0.03] text-muted-foreground dark:text-white/60 hover:text-foreground hover:bg-foreground/[0.06] border-foreground/[0.08] hover:border-foreground/[0.12] rounded-md"
                        >
                            Cancel
                        </Button>
                        <Button
                            onClick={handleSave}
                            disabled={saving || !dirty}
                            className="h-10 bg-primary hover:bg-primary text-primary-foreground font-medium rounded-md border-0 shadow-[0_2.5px_0_0_#a0a0a0] hover:shadow-[0_1px_0_0_#a0a0a0] hover:translate-y-[1.5px] active:shadow-none active:translate-y-[2.5px] transition-all duration-100 disabled:opacity-40 min-w-[100px]"
                        >
                            {saving ? 'Saving...' : 'Save'}
                        </Button>
                        </div>
                    </DialogFooter>
                </div>
            </DialogContent>
        </Dialog>
    );
}

// Single setting row in the grouped-list card. Mirrors the NotificationsSettings
// pattern (icon tile + label + description) but adds an input slot underneath
// for field-bearing settings (NotificationsSettings is toggles-only and puts
// its control inline; ours need a full-width field below).
interface SettingRowProps {
    icon: React.ComponentType<{ className?: string }>;
    label: string;
    description: string;
    children: React.ReactNode;
}

function SettingRow({ icon: Icon, label, description, children }: SettingRowProps) {
    return (
        <div className="px-4 py-3">
            <div className="flex items-start gap-3">
                <div className="flex items-center justify-center w-7 h-7 rounded-md bg-foreground/[0.06] flex-shrink-0 mt-0.5">
                    <Icon className="w-3.5 h-3.5 text-muted-foreground dark:text-white/60 stroke-[1.5]" />
                </div>
                <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-foreground leading-tight">{label}</p>
                    <p className="text-xs text-muted-foreground dark:text-white/40 mt-0.5">{description}</p>
                </div>
            </div>
            <div className="mt-2.5 pl-10">{children}</div>
        </div>
    );
}

// Single-select workflow dropdown. Reuses the NoClick node's
// `allowed_workflow_ids` load_options path (it already returns the caller's
// workflows by name) — saves wiring a new socket endpoint just for this field.
// The current workflow is hidden from the list so the UI can't construct
// self-target; the backend rejects it too as a defense in depth.
interface ErrorHandlerPickerProps {
    selectedId: string;
    onChange: (id: string) => void;
    onSelectedLabelChange: (label: string) => void;
    excludeWorkflowId: string;
}

function ErrorHandlerPicker({
    selectedId,
    onChange,
    onSelectedLabelChange,
    excludeWorkflowId,
}: ErrorHandlerPickerProps) {
    const [options, setOptions] = useState<WorkflowOption[]>([]);
    const [labelCache, setLabelCache] = useState<Record<string, string>>({});
    const [loading, setLoading] = useState(false);
    const [isOpen, setIsOpen] = useState(false);
    const [search, setSearch] = useState('');
    const containerRef = useRef<HTMLDivElement>(null);

    const loadOptions = useCallback(async () => {
        setLoading(true);
        try {
            const { WorkflowNodeLoadOptionsRequest } = await import('~/types/socket-events.generated');
            const resp = await sendEventAsync(WorkflowNodeLoadOptionsRequest.create({
                node_type: 'noclick',
                field_name: 'allowed_workflow_ids',
                credential_id: '',
                context: {},
            }));
            const opts = (resp.options || []).filter((o: WorkflowOption) => o.value !== excludeWorkflowId);
            setOptions(opts);
            setLabelCache(prev => {
                const next = { ...prev };
                for (const o of opts) next[o.value] = o.label;
                return next;
            });
        } catch {
            // Silent — the picker stays empty and the user can still save.
        } finally {
            setLoading(false);
        }
    }, [excludeWorkflowId]);

    // Eagerly load once so the chip can show the selected workflow's NAME
    // (not just its UUID) before the user clicks the dropdown.
    useEffect(() => {
        if (selectedId && !labelCache[selectedId] && options.length === 0) {
            loadOptions();
        }
    }, [selectedId, labelCache, options.length, loadOptions]);

    useEffect(() => {
        if (isOpen && options.length === 0) loadOptions();
    }, [isOpen, options.length, loadOptions]);

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

    // Bubble the resolved label up so the surrounding helper text can name it.
    const selectedLabel = selectedId
        ? labelCache[selectedId] || (selectedId.slice(0, 8) + '…')
        : '';
    useEffect(() => {
        onSelectedLabelChange(selectedLabel);
    }, [selectedLabel, onSelectedLabelChange]);

    const filtered = fuzzyFilter(
        options.filter(o => o.value !== selectedId),
        search,
        o => [{ text: o.label.toLowerCase(), weight: 1, fuzzy: true }]
    );

    return (
        <div ref={containerRef} className="relative">
            <div
                className={`${settingsInputClass} flex items-center cursor-pointer gap-2`}
                onClick={() => {
                    // Clicking a selected chip clears it and opens the search,
                    // matching "click to change" expectations for a single-select.
                    if (selectedId) {
                        onChange('');
                        setSearch('');
                        setIsOpen(true);
                    } else {
                        setIsOpen(v => !v);
                    }
                }}
            >
                {selectedId ? (
                    <>
                        <span className="flex-1 text-foreground truncate">{selectedLabel}</span>
                        <button
                            type="button"
                            onClick={(e) => {
                                e.stopPropagation();
                                onChange('');
                                setSearch('');
                            }}
                            className="text-muted-foreground dark:text-white/40 hover:text-red-600 dark:hover:text-red-400 transition-colors"
                            aria-label="Clear error handler"
                        >
                            <X className="w-3.5 h-3.5" />
                        </button>
                    </>
                ) : isOpen ? (
                    <input
                        autoFocus
                        type="text"
                        value={search}
                        onChange={e => setSearch(e.target.value)}
                        onClick={e => e.stopPropagation()}
                        placeholder="Search workflows..."
                        className="flex-1 bg-transparent outline-none text-foreground placeholder:text-[hsl(var(--placeholder))]"
                    />
                ) : (
                    <span className="flex-1 text-muted-foreground/70 dark:text-white/30">No error handler</span>
                )}
                {loading ? (
                    <Loader2 className="w-3.5 h-3.5 text-muted-foreground dark:text-white/40 animate-spin flex-none" />
                ) : (
                    !selectedId && (
                        <ChevronDown className={`w-3.5 h-3.5 text-muted-foreground dark:text-white/40 flex-none transition-transform ${isOpen ? 'rotate-180' : ''}`} />
                    )
                )}
            </div>

            {isOpen && !selectedId && (
                <div className="absolute z-50 w-full mt-1 max-h-48 overflow-y-auto rounded-lg border border-border dark:border-white/[0.08] bg-popover dark:bg-zinc-950 shadow-xl">
                    {filtered.length === 0 && !loading && (
                        <div className="px-3 py-2 text-xs text-muted-foreground dark:text-white/40 italic">
                            {search ? 'No matching workflows' : 'No workflows available'}
                        </div>
                    )}
                    {filtered.map(o => (
                        <button
                            key={o.value}
                            type="button"
                            className="w-full text-left px-3 py-2 text-sm text-foreground/80 hover:bg-foreground/[0.06] hover:text-foreground transition-colors"
                            onClick={() => {
                                onChange(o.value);
                                setIsOpen(false);
                                setSearch('');
                            }}
                        >
                            {o.label}
                        </button>
                    ))}
                </div>
            )}
        </div>
    );
}
