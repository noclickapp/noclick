// Feed — approval requests, processed decisions, and activity logs in one hub.

import { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import {
    ShieldCheck, Check, X, RefreshCw, Clock,
    User, ArrowUpRight, Workflow, ChevronDown, ChevronRight,
    ScrollText, Info, CheckCircle2, AlertTriangle, XCircle, Search, CheckSquare,
    Bot, Wrench, Terminal, Plug, FolderOpen, Mail, KeyRound,
} from 'lucide-react';
import { cn } from '~/lib/utils';
import { useApprovalFeed, type ApprovalRequest, type ApprovalFormField } from '~/hooks/useApprovalFeed';
import { useActivityLog, type ActivityLogEntry } from '~/hooks/useActivityLog';
import { useToolCallEvents, type ToolCallEntry } from '~/hooks/useToolCallEvents';
import { getNodeMetadata } from '~/components/workflow/nodes/nodeRegistry';
import { resolveToolProviderMeta } from '~/lib/toolBrand';
import { ToolDetailBlock } from '~/components/shared/ToolDetailBlock';
import { BrandIcon, type BrandIconComponent } from '~/components/shared/BrandIcon';
import { AgentModelIcon } from '~/components/workflow/nodes/base/AgentModelIcon';
import { modelShortName } from '~/lib/modelFiltering';
import { isCliAgentModel } from '~/lib/agentChat';
import { openCreateCredential } from '~/components/shared/popups/CreateCredentialDialog';
import { navigateToTab } from '~/lib/navigation';
import { navigateToNode } from '~/utils/workflowNavigation';
import { fuzzyFilter } from '~/utils/fuzzySearch';
import { SparkleButton } from '~/components/ui/SparkleButton';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '~/components/ui/dialog';
import { Popover, PopoverContent, PopoverTrigger } from '~/components/ui/popover';
import { Button } from '~/components/ui/button';
import { isLocalEdition } from '~/lib/edition';

// ============================================================================
// Helpers
// ============================================================================

function timeAgo(dateStr: string): string {
    const seconds = Math.floor((Date.now() - new Date(dateStr).getTime()) / 1000);
    if (seconds < 60) return 'just now';
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours}h ago`;
    const days = Math.floor(hours / 24);
    return `${days}d ago`;
}

function ElapsedTime({ since }: { since: string }) {
    const [, setTick] = useState(0);
    useEffect(() => {
        const id = setInterval(() => setTick(t => t + 1), 60_000);
        return () => clearInterval(id);
    }, []);
    return <span>{timeAgo(since)}</span>;
}

// Navigate to a workflow node from the feed tab without a page reload.
// Dispatches a custom event that Dashboard handles — switches tab, sets URL params,
// and queues node selection all in one go.
function goToWorkflowNode(workflowId: string, nodeId: string) {
    window.dispatchEvent(new CustomEvent('noclick:navigate-to-node', {
        detail: { workflowId, nodeId },
    }));
    // For already-mounted FlowCanvas, fire after the tab switch renders
    setTimeout(() => navigateToNode(workflowId, nodeId), 200);
}

// ============================================================================
// Form Field Input
// ============================================================================

function FormFieldInput({ field, value, onChange }: {
    field: ApprovalFormField;
    value: any;
    onChange: (name: string, value: any) => void;
}) {
    const label = field.label || field.name;
    const inputBase = 'w-full bg-muted dark:bg-foreground/[0.05] border border-input dark:border-white/[0.08] rounded-lg px-3 py-2 text-[0.8125rem] text-foreground placeholder:text-[hsl(var(--placeholder))] focus:outline-none focus:border-ring/30 dark:focus:border-white/[0.2] backdrop-blur-sm transition-colors';

    if (field.type === 'boolean') {
        return (
            <label className="flex items-center gap-3 py-0.5 cursor-pointer group/check">
                <div className={cn(
                    'w-[1.125rem] h-[1.125rem] rounded border flex items-center justify-center transition-colors',
                    value === true || value === 'true'
                        ? 'bg-primary border-primary'
                        : 'bg-transparent border-border dark:border-zinc-700 group-hover/check:border-muted-foreground dark:check:border-zinc-500'
                )}>
                    {(value === true || value === 'true') && <Check className="w-3 h-3 text-primary-foreground" />}
                </div>
                <input type="checkbox" className="sr-only"
                    checked={value === true || value === 'true'}
                    onChange={(e) => onChange(field.name, e.target.checked)} />
                <div>
                    <span className="text-[0.8125rem] text-foreground/80">{label}</span>
                    {field.description && <p className="text-[0.6875rem] text-muted-foreground/70 dark:text-zinc-600 mt-0.5">{field.description}</p>}
                </div>
            </label>
        );
    }

    if (field.type === 'media') {
        const url = typeof value === 'string' ? value.trim() : '';
        const lower = url.toLowerCase();
        const isVideo = /\.(mp4|webm|mov|ogg)(\?|$)/i.test(lower) || lower.includes('video');
        const isAudio = /\.(mp3|wav|ogg|aac|m4a)(\?|$)/i.test(lower);
        // Everything else (including data URIs) treated as image

        return (
            <div className="space-y-1.5">
                <label className="text-[0.6875rem] text-muted-foreground dark:text-zinc-500">{label}</label>
                {url ? (
                    <div className="rounded-lg overflow-hidden border border-border dark:border-white/[0.06] bg-muted dark:bg-black/20">
                        {isVideo ? (
                            <video
                                src={url}
                                controls
                                className="w-full max-h-[22.5rem] object-contain"
                            />
                        ) : isAudio ? (
                            <div className="p-3">
                                <audio src={url} controls className="w-full" />
                            </div>
                        ) : (
                            <img
                                src={url}
                                alt={label}
                                className="w-full max-h-[22.5rem] object-contain"
                                onError={(e) => {
                                    // If image fails, show as a link instead
                                    const target = e.currentTarget;
                                    target.style.display = 'none';
                                    target.nextElementSibling?.classList.remove('hidden');
                                }}
                            />
                        )}
                        {/* Fallback link (hidden by default, shown if image fails) */}
                        <a href={url} target="_blank" rel="noopener noreferrer"
                            className="hidden px-3 py-2 text-xs text-muted-foreground hover:text-foreground truncate block">
                            {url}
                        </a>
                    </div>
                ) : (
                    <div className="rounded-lg border border-border dark:border-white/[0.06] bg-foreground/[0.03] dark:bg-black/10 px-3 py-6 text-center text-xs text-muted-foreground/70 dark:text-zinc-600">
                        No media URL provided
                    </div>
                )}
                {field.description && <p className="text-[0.6875rem] text-muted-foreground/70 dark:text-zinc-600 mt-1">{field.description}</p>}
            </div>
        );
    }

    if (field.type === 'select' && field.options) {
        return (
            <div className="space-y-1.5">
                <label className="text-[0.6875rem] text-muted-foreground dark:text-zinc-500">{label}</label>
                <select value={value ?? ''} onChange={(e) => onChange(field.name, e.target.value)} className={inputBase}>
                    <option value="" className="bg-card text-muted-foreground dark:text-zinc-500">Select...</option>
                    {field.options.map(opt => <option key={opt} value={opt} className="bg-card">{opt}</option>)}
                </select>
                {field.description && <p className="text-[0.6875rem] text-muted-foreground/70 dark:text-zinc-600">{field.description}</p>}
            </div>
        );
    }

    const isLong = typeof value === 'string' && value.length > 100;
    return (
        <div className="space-y-1.5">
            <label className="text-[0.6875rem] text-muted-foreground dark:text-zinc-500">{label}</label>
            {isLong ? (
                <textarea value={value ?? ''} onChange={(e) => onChange(field.name, e.target.value)}
                    rows={3} className={`${inputBase} resize-y`} />
            ) : (
                <input type={field.type === 'number' ? 'number' : 'text'}
                    value={value ?? ''}
                    onChange={(e) => onChange(field.name, field.type === 'number' && e.target.value !== '' ? Number(e.target.value) : e.target.value)}
                    className={inputBase} />
            )}
            {field.description && <p className="text-[0.6875rem] text-muted-foreground/70 dark:text-zinc-600">{field.description}</p>}
        </div>
    );
}

// ============================================================================
// Pending Card
// ============================================================================

function PendingCard({ approval, onRespond, isSelected, onToggleSelect }: {
    approval: ApprovalRequest;
    onRespond: (id: string, decision: 'approved' | 'rejected', values?: Record<string, any>) => void;
    isSelected: boolean;
    onToggleSelect: (id: string) => void;
}) {
    const [editedValues, setEditedValues] = useState<Record<string, any>>(approval.values || {});
    const [fading, setFading] = useState(false);
    const cardRef = useRef<HTMLDivElement>(null);
    const hasFields = approval.fields && approval.fields.length > 0;
    const goToWorkflow = goToWorkflowNode;

    const handleRespond = (decision: 'approved' | 'rejected') => {
        setFading(true);

        const wrapper = cardRef.current;
        if (wrapper) {
            // Explicitly set height to current value, then animate to 0 on next frame
            wrapper.style.height = `${wrapper.offsetHeight}px`;
            wrapper.style.transition = 'height 400ms cubic-bezier(0.4, 0, 0.2, 1) 150ms';
            requestAnimationFrame(() => {
                requestAnimationFrame(() => {
                    if (cardRef.current) cardRef.current.style.height = '0px';
                });
            });
        }

        // Remove well after animation completes
        setTimeout(() => onRespond(approval.id, decision, editedValues), 900);
    };

    return (
        <div
            ref={cardRef}
            className="overflow-hidden"
        >
        <div className="pb-3">
        <div
            className={cn(
                'rounded-xl border backdrop-blur-sm overflow-hidden transition-colors',
                isSelected
                    ? 'border-foreground/30 bg-accent dark:bg-foreground/[0.1]'
                    : 'border-border dark:border-white/[0.14] bg-card dark:bg-foreground/[0.07] hover:bg-muted dark:hover:bg-foreground/[0.09]',
                fading && 'opacity-0 scale-[0.97]'
            )}
            style={{
                transition: 'background-color 150ms ease-in-out, border-color 150ms ease-in-out, opacity 300ms ease-out, transform 300ms ease-out',
            }}
        >
            {/* Header */}
            <div className="px-5 pt-4 pb-3">
                <div className="flex items-start gap-3">
                    {/* Selection checkbox — always visible so the title never sits behind an empty gap. */}
                    <button
                        onClick={() => onToggleSelect(approval.id)}
                        className={cn(
                            'mt-0.5 flex-shrink-0 w-[1.125rem] h-[1.125rem] rounded border flex items-center justify-center transition-all duration-150',
                            isSelected
                                ? 'bg-primary border-primary'
                                : 'border-border dark:border-zinc-700 bg-transparent hover:border-muted-foreground'
                        )}
                        aria-label={isSelected ? 'Deselect' : 'Select'}
                    >
                        {isSelected && <Check className="w-3 h-3 text-primary-foreground" />}
                    </button>
                    <div className="flex-1 min-w-0">
                        <div className="flex items-start justify-between gap-3">
                            <h3 className="text-sm font-medium text-foreground leading-snug flex-1 min-w-0">
                                {approval.title || 'Approval Required'}
                            </h3>
                            <div className="flex items-center gap-1 text-[0.6875rem] text-muted-foreground/70 dark:text-zinc-600 flex-shrink-0 tabular-nums">
                                <Clock className="w-3 h-3" />
                                <ElapsedTime since={approval.created_at} />
                            </div>
                        </div>

                        {/* Workflow link */}
                        <button
                            onClick={() => goToWorkflow(approval.workflow_id, approval.node_id)}
                            className="mt-1.5 inline-flex items-center gap-1.5 text-[0.6875rem] text-muted-foreground dark:text-zinc-500 hover:text-foreground/80 transition-colors"
                        >
                            <Workflow className="w-3 h-3 flex-shrink-0" />
                            <span className="truncate max-w-[13.75rem]">{approval.workflow_name}</span>
                            <ArrowUpRight className="w-3 h-3 flex-shrink-0" />
                        </button>
                    </div>
                </div>
            </div>

            {/* Form fields */}
            {hasFields && (
                <div className="px-5 pb-4 space-y-3">
                    {approval.fields.map(field => (
                        <FormFieldInput
                            key={field.name} field={field}
                            value={editedValues[field.name]}
                            onChange={(name, val) => setEditedValues(prev => ({ ...prev, [name]: val }))}
                        />
                    ))}
                </div>
            )}

            {/* Actions */}
            <div className="px-5 py-3 flex items-center justify-end gap-3">
                <SparkleButton
                    onClick={() => handleRespond('rejected')}
                    sparkColors={['#ef4444', '#f87171', '#fca5a5', '#dc2626']}
                    particleCount={24}
                    feedbackIcon="cross"
                    className="h-8 px-4 rounded-md text-xs font-medium text-foreground/80 bg-foreground/10 border border-border dark:border-white/10 shadow-[0_2.5px_0_0_hsl(var(--foreground)/0.06)] hover:shadow-[0_1px_0_0_hsl(var(--foreground)/0.06)] hover:translate-y-[1.5px] active:shadow-none active:translate-y-[2.5px] transition-all duration-100"
                >
                    Reject
                </SparkleButton>
                <SparkleButton
                    onClick={() => handleRespond('approved')}
                    sparkColors={['#ffffff', '#fafafa', '#e4e4e7', '#f0fdf4', '#bbf7d0']}
                    particleCount={24}
                    feedbackIcon="check"
                    className="h-8 px-4 rounded-md text-xs font-medium text-primary-foreground bg-primary shadow-[0_2.5px_0_0_#a0a0a0] hover:shadow-[0_1px_0_0_#a0a0a0] hover:translate-y-[1.5px] active:shadow-none active:translate-y-[2.5px] transition-all duration-100"
                >
                    Approve
                </SparkleButton>
            </div>
        </div>
        </div>
        </div>
    );
}

// ============================================================================
// Processed Card (expandable)
// ============================================================================

function ProcessedCard({ approval, onRedo }: {
    approval: ApprovalRequest;
    onRedo: (id: string, decision: 'approved' | 'rejected', values?: Record<string, any>) => void;
}) {
    const [expanded, setExpanded] = useState(false);
    const [editedValues, setEditedValues] = useState<Record<string, any>>(approval.values || {});
    const [confirmAction, setConfirmAction] = useState<'approved' | 'rejected' | null>(null);
    const isApproved = approval.status === 'approved';
    const hasFields = approval.fields && approval.fields.length > 0;

    const handleRedo = (decision: 'approved' | 'rejected') => {
        setConfirmAction(null);
        onRedo(approval.id, decision, editedValues);
    };

    return (
        <>
            <div className="rounded-xl border border-border dark:border-white/[0.08] bg-card dark:bg-foreground/[0.04] backdrop-blur-sm overflow-hidden transition-all">
                {/* Header — clickable to expand */}
                <div
                    onClick={() => setExpanded(!expanded)}
                    className="flex items-center gap-3 px-4 py-3 cursor-pointer hover:bg-foreground/[0.03] transition-colors"
                >
                    {/* Status icon */}
                    <div className={cn(
                        'w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0',
                        isApproved ? 'bg-emerald-500/15' : 'bg-red-500/15'
                    )}>
                        {isApproved
                            ? <Check className="w-3 h-3 text-emerald-600 dark:text-emerald-400" />
                            : <X className="w-3 h-3 text-red-600 dark:text-red-400" />}
                    </div>

                    {/* Title + workflow */}
                    <div className="flex-1 min-w-0">
                        <div className="text-[0.8125rem] text-foreground">
                            {approval.title || 'Approval Request'}
                        </div>
                        <div className="text-[0.6875rem] text-muted-foreground/70 dark:text-zinc-600 mt-0.5 flex items-center gap-1.5">
                            <Workflow className="w-3 h-3" />
                            <span className="truncate">{approval.workflow_name}</span>
                        </div>
                    </div>

                    {/* Meta */}
                    <div className="flex items-center gap-3 flex-shrink-0 text-[0.6875rem] text-muted-foreground dark:text-zinc-500">
                        <span className={cn(
                            'px-2 py-0.5 rounded-full text-[0.625rem] font-medium',
                            isApproved ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400' : 'bg-red-500/10 text-red-600 dark:text-red-400'
                        )}>
                            {isApproved ? 'Approved' : 'Rejected'}
                        </span>
                        <span className="flex items-center gap-1">
                            <User className="w-3 h-3" />
                            {approval.decided_by_email || 'unknown'}
                        </span>
                        <span>{approval.decided_at ? timeAgo(approval.decided_at) : ''}</span>
                    </div>

                    {/* Chevron */}
                    <ChevronDown className={cn(
                        'w-4 h-4 text-muted-foreground/70 dark:text-zinc-600 transition-transform duration-200',
                        expanded && 'rotate-180'
                    )} />
                </div>

                {/* Expanded content */}
                {expanded && (
                    <div className="border-t border-border dark:border-white/[0.06]">
                        {/* Form fields — editable for redo */}
                        {hasFields && (
                            <div className="px-4 py-3 space-y-3">
                                {approval.fields.map(field => (
                                    <FormFieldInput
                                        key={field.name}
                                        field={field}
                                        value={editedValues[field.name]}
                                        onChange={(name, val) => setEditedValues(prev => ({ ...prev, [name]: val }))}
                                    />
                                ))}
                            </div>
                        )}

                        {/* Actions */}
                        <div className="px-4 py-3 flex items-center justify-between border-t border-border dark:border-white/[0.04]">
                            <button
                                onClick={(e) => {
                                    e.stopPropagation();
                                    goToWorkflowNode(approval.workflow_id, approval.node_id);
                                }}
                                className="text-[0.6875rem] text-muted-foreground dark:text-zinc-500 hover:text-foreground/80 transition-colors flex items-center gap-1"
                            >
                                <ArrowUpRight className="w-3 h-3" />
                                View in workflow
                            </button>
                            <div className="flex items-center gap-2">
                                <button
                                    onClick={(e) => { e.stopPropagation(); setConfirmAction('rejected'); }}
                                    className="h-7 px-3 rounded-md text-[0.6875rem] font-medium text-muted-foreground bg-foreground/10 border border-border dark:border-white/10 shadow-[0_2px_0_0_hsl(var(--foreground)/0.05)] hover:shadow-[0_1px_0_0_hsl(var(--foreground)/0.05)] hover:translate-y-[1px] active:shadow-none active:translate-y-[2px] transition-all duration-100"
                                >
                                    Redo as Reject
                                </button>
                                <button
                                    onClick={(e) => { e.stopPropagation(); setConfirmAction('approved'); }}
                                    className="h-7 px-3 rounded-md text-[0.6875rem] font-medium text-muted-foreground bg-foreground/10 border border-border dark:border-white/10 shadow-[0_2px_0_0_hsl(var(--foreground)/0.05)] hover:shadow-[0_1px_0_0_hsl(var(--foreground)/0.05)] hover:translate-y-[1px] active:shadow-none active:translate-y-[2px] transition-all duration-100"
                                >
                                    Redo as Approve
                                </button>
                            </div>
                        </div>
                    </div>
                )}
            </div>

            {/* Confirmation dialog */}
            <Dialog open={confirmAction !== null} onOpenChange={(open) => { if (!open) setConfirmAction(null); }}>
                <DialogContent className="bg-sunken border-border text-foreground max-w-sm p-6">
                    <DialogHeader className="pb-2">
                        <DialogTitle className="text-lg text-foreground flex items-center gap-2">
                            <ShieldCheck className="w-5 h-5 text-muted-foreground" />
                            Redo as {confirmAction === 'approved' ? 'Approve' : 'Reject'}?
                        </DialogTitle>
                        <div className="text-sm text-muted-foreground pt-2 leading-relaxed">
                            This will re-run the workflow from the approval node down
                            the <span className="text-foreground font-medium">{confirmAction}</span> branch.
                            {approval.decided_by_email && (
                                <span className="block mt-2 text-muted-foreground dark:text-zinc-500 text-xs">
                                    Previously {isApproved ? 'approved' : 'rejected'} by {approval.decided_by_email}
                                    {approval.decided_at && <> · {timeAgo(approval.decided_at)}</>}
                                </span>
                            )}
                        </div>
                    </DialogHeader>

                    <div className="flex justify-end gap-2 pt-4">
                        <Button
                            variant="outline"
                            onClick={() => setConfirmAction(null)}
                            className="bg-transparent text-foreground/80 hover:text-foreground hover:bg-accent/50 border-border dark:border-zinc-700/70 hover:border-muted-foreground/50 dark:hover:border-zinc-600/80 rounded-full"
                        >
                            Cancel
                        </Button>
                        <Button
                            onClick={() => handleRedo(confirmAction!)}
                            className="bg-primary text-primary-foreground hover:bg-primary/90 shadow-sm font-medium rounded-full min-w-[5.625rem]"
                        >
                            {confirmAction === 'approved' ? 'Approve' : 'Reject'}
                        </Button>
                    </div>
                </DialogContent>
            </Dialog>
        </>
    );
}

// ============================================================================
// Main Feed
// ============================================================================

// ============================================================================
// Activity Log Row
// ============================================================================

const LEVEL_CONFIG = {
    info:    { icon: Info,          color: 'text-muted-foreground',                   bar: 'bg-muted-foreground',                   bg: 'bg-zinc-500/10',    label: 'Info' },
    success: { icon: CheckCircle2,  color: 'text-emerald-600 dark:text-emerald-400', bar: 'bg-emerald-600 dark:bg-emerald-400',   bg: 'bg-emerald-500/10', label: 'Success' },
    warning: { icon: AlertTriangle, color: 'text-amber-600 dark:text-amber-400',     bar: 'bg-amber-600 dark:bg-amber-400',       bg: 'bg-amber-500/10',   label: 'Warning' },
    error:   { icon: XCircle,       color: 'text-red-600 dark:text-red-400',         bar: 'bg-red-600 dark:bg-red-400',           bg: 'bg-red-500/10',     label: 'Error' },
} as const;

type LogLevel = keyof typeof LEVEL_CONFIG;

function ActivityRow({ entry }: { entry: ActivityLogEntry }) {
    const config = LEVEL_CONFIG[entry.level] || LEVEL_CONFIG.info;
    const LevelIcon = config.icon;

    return (
        <div
            onClick={() => goToWorkflowNode(entry.workflow_id, entry.node_id)}
            className="flex items-center gap-2.5 mx-5 py-2.5 hover:bg-foreground/[0.02] cursor-pointer transition-colors group/row rounded-sm"
        >
            <div className={cn('w-0.5 h-4 rounded-full flex-shrink-0', config.bar, 'opacity-40')} />
            <div className={cn('w-5 h-5 rounded flex items-center justify-center flex-shrink-0', config.bg)}>
                <LevelIcon className={cn('w-3 h-3', config.color)} />
            </div>
            <div className="flex-1 min-w-0 text-[0.8125rem] text-foreground/80 group-hover/row:text-foreground transition-colors truncate">
                {entry.message}
            </div>
            <div className="flex items-center gap-1.5 flex-shrink-0 text-[0.6875rem] text-muted-foreground/70 dark:text-zinc-600 mr-1">
                <Workflow className="w-3 h-3" />
                <span className="truncate max-w-[7.5rem]">{entry.workflow_name}</span>
                <span className="text-muted-foreground/50 dark:text-zinc-700">·</span>
                <span className="tabular-nums">{timeAgo(entry.created_at)}</span>
            </div>
        </div>
    );
}

function WorkflowFilterDropdown({ value, workflows, onChange }: {
    value: string | 'all';
    workflows: { id: string; name: string }[];
    onChange: (id: string | 'all') => void;
}) {
    const [open, setOpen] = useState(false);
    const [search, setSearch] = useState('');
    const selected = value === 'all' ? null : workflows.find(w => w.id === value);

    const filtered = fuzzyFilter(workflows, search, w => [
        { text: w.name.toLowerCase(), weight: 1, fuzzy: true },
    ]);

    return (
        <Popover open={open} onOpenChange={setOpen}>
            <PopoverTrigger asChild>
                <button className="h-8 px-3 rounded-lg text-xs font-medium border border-border/70 dark:border-white/[0.06] text-muted-foreground hover:text-foreground hover:border-border dark:hover:border-white/[0.1] transition-colors flex items-center gap-1.5 max-w-[12.5rem]">
                    <Workflow className="w-3.5 h-3.5 flex-shrink-0" />
                    <span className="truncate">{selected ? selected.name : 'All workflows'}</span>
                    <ChevronDown className="w-3 h-3 flex-shrink-0 text-muted-foreground/70 dark:text-zinc-600" />
                </button>
            </PopoverTrigger>
            <PopoverContent
                align="start"
                className="w-[13.75rem] p-0 bg-background dark:bg-[#0a0a0b] border-border dark:border-white/[0.08] shadow-2xl rounded-lg overflow-hidden"
            >
                <div className="p-1.5">
                    <div className="flex items-center gap-2 px-2 py-1.5 rounded-md bg-foreground/[0.04]">
                        <Search className="w-3 h-3 text-muted-foreground/70 dark:text-zinc-600 flex-shrink-0" />
                        <input
                            type="text"
                            value={search}
                            onChange={(e) => setSearch(e.target.value)}
                            placeholder="Search..."
                            className="w-full bg-transparent text-xs text-foreground placeholder:text-[hsl(var(--placeholder))] focus:outline-none"
                            autoFocus
                        />
                    </div>
                </div>
                <div className="max-h-[15rem] overflow-y-auto scrollbar-subtle py-1">
                    <button
                        onClick={() => { onChange('all'); setOpen(false); setSearch(''); }}
                        className={cn(
                            'w-full text-left px-3 py-1.5 text-xs flex items-center gap-2 transition-colors rounded-sm mx-auto',
                            value === 'all' ? 'text-foreground' : 'text-muted-foreground dark:text-zinc-500 hover:text-foreground'
                        )}
                    >
                        All workflows
                        {value === 'all' && <Check className="w-3 h-3 ml-auto text-muted-foreground dark:text-zinc-500" />}
                    </button>
                    <div className="h-px bg-foreground/[0.04] mx-2 my-1" />
                    {filtered.map(w => (
                        <button
                            key={w.id}
                            onClick={() => { onChange(w.id); setOpen(false); setSearch(''); }}
                            className={cn(
                                'w-full text-left px-3 py-1.5 text-xs flex items-center gap-2 transition-colors rounded-sm',
                                value === w.id ? 'text-foreground' : 'text-muted-foreground dark:text-zinc-500 hover:text-foreground'
                            )}
                        >
                            <span className="truncate">{w.name}</span>
                            {value === w.id && <Check className="w-3 h-3 ml-auto flex-shrink-0 text-muted-foreground dark:text-zinc-500" />}
                        </button>
                    ))}
                    {filtered.length === 0 && (
                        <div className="px-3 py-3 text-[0.6875rem] text-muted-foreground/70 dark:text-zinc-600 text-center">No matches</div>
                    )}
                </div>
            </PopoverContent>
        </Popover>
    );
}

function ActivityLevelFilters({ levelFilter, onLevelChange }: {
    levelFilter: LogLevel | 'all';
    onLevelChange: (level: LogLevel | 'all') => void;
}) {
    const levels: (LogLevel | 'all')[] = ['all', 'info', 'success', 'warning', 'error'];

    return (
        <div className="px-5 pb-3 flex items-center gap-1.5 flex-wrap">
            {levels.map(level => {
                const active = levelFilter === level;
                const config = level === 'all' ? null : LEVEL_CONFIG[level];
                return (
                    <button
                        key={level}
                        onClick={() => onLevelChange(level)}
                        className={cn(
                            'h-7 px-2.5 rounded-md text-[0.6875rem] font-medium transition-all flex items-center gap-1.5',
                            active
                                ? 'bg-foreground/[0.1] text-foreground'
                                : 'text-muted-foreground dark:text-zinc-500 hover:text-foreground/80 hover:bg-foreground/[0.03]'
                        )}
                    >
                        {config && <config.icon className={cn('w-3 h-3', active ? config.color : '')} />}
                        {level === 'all' ? 'All' : config?.label}
                    </button>
                );
            })}
        </div>
    );
}

// ============================================================================
// Agent Tool Calls — run-grouped cards, styled after the Settings panels
// ============================================================================

function formatDuration(ms: number): string {
    if (ms < 1000) return `${Math.round(ms)}ms`;
    if (ms < 10000) return `${(ms / 1000).toFixed(1)}s`;
    return `${Math.round(ms / 1000)}s`;
}

// Prefer the resolved provider label + operation ("Linear · create_issue"),
// which reads better than the raw "linear__create_issue" slug.
function toolDisplayName(entry: ToolCallEntry): string {
    if (entry.provider_node_label && entry.operation) {
        return `${entry.provider_node_label} · ${entry.operation}`;
    }
    if (entry.operation) return entry.operation;
    return entry.tool_name.replace(/__/g, ' · ');
}

// Fallback glyph for tool types with no integration provider (bash, mcp, …).
const TOOL_TYPE_ICON: Record<string, BrandIconComponent> = {
    bash: Terminal,
    mcp: Plug,
    filesystem: FolderOpen,
    alarm: Clock,
    email_reply: Mail,
    workflow: Workflow,
    node_op_lookup: Search,
};

// Provider-brand resolution lives in ~/lib/toolBrand (shared with the agent
// chat's step timeline).
function resolveProviderMeta(entry: ToolCallEntry) {
    return resolveToolProviderMeta(entry.tool_name, entry.provider_node_type);
}

// The integration's brand icon (same mark shown on the canvas), falling back to
// a tool-type glyph for bash / mcp / filesystem etc.
function ToolIcon({ entry, className = 'w-4 h-4' }: { entry: ToolCallEntry; className?: string }) {
    const meta = resolveProviderMeta(entry);
    if (meta?.Icon) {
        return <BrandIcon Icon={meta.Icon as BrandIconComponent} iconColor={meta.iconColor} className={className} />;
    }
    const Fallback = TOOL_TYPE_ICON[entry.tool_type] || Wrench;
    return <Fallback className={cn(className, 'text-foreground/60 stroke-[1.5]')} />;
}

// One tool call inside a run group. Row chrome mirrors a Settings list row
// (icon badge + label + secondary), expands to args / result / error.
function ToolCallRow({ entry }: { entry: ToolCallEntry }) {
    const [expanded, setExpanded] = useState(false);
    const isError = entry.result_status === 'error';
    const hasArgs = !!entry.arguments && Object.keys(entry.arguments).length > 0;
    const canExpand = hasArgs || !!entry.error || !!entry.result_preview;
    const title = toolDisplayName(entry);

    return (
        <div>
            <div
                onClick={() => canExpand && setExpanded(v => !v)}
                className={cn('flex items-center gap-2.5 px-4 py-2 transition-colors', canExpand && 'cursor-pointer hover:bg-foreground/[0.02]')}
            >
                <div className="flex items-center justify-center w-6 h-6 rounded-md bg-foreground/[0.06] flex-shrink-0">
                    <ToolIcon entry={entry} className="w-3.5 h-3.5" />
                </div>

                <span className="text-[0.8125rem] font-medium text-foreground leading-tight truncate min-w-0">{title}</span>

                {/* status + caret sit right next to the name so they're easy to scan */}
                <span className={cn(
                    'inline-flex items-center gap-1 text-[0.6875rem] font-medium px-2 py-0.5 rounded-full flex-shrink-0',
                    isError ? 'text-red-600 dark:text-red-300 bg-red-500/15' : 'text-emerald-600 dark:text-emerald-300 bg-emerald-500/15'
                )}>
                    {isError ? <XCircle className="w-3 h-3" /> : <CheckCircle2 className="w-3 h-3" />}
                    {isError ? 'Failed' : 'OK'}
                </span>
                {canExpand && (
                    <ChevronDown className={cn('w-4 h-4 text-foreground/30 transition-transform duration-200 flex-shrink-0', expanded && 'rotate-180')} />
                )}

                {entry.duration_ms != null && (
                    <span className="ml-auto text-xs text-foreground/30 tabular-nums flex-shrink-0 hidden sm:inline">{formatDuration(entry.duration_ms)}</span>
                )}
            </div>

            {expanded && canExpand && (
                <div className="px-4 pb-3.5 space-y-2.5">
                    {hasArgs && (
                        <ToolDetailBlock label="Called with" tone="neutral">{JSON.stringify(entry.arguments, null, 2)}</ToolDetailBlock>
                    )}
                    {entry.error && <ToolDetailBlock label="Error" tone="error">{entry.error}</ToolDetailBlock>}
                    {!entry.error && entry.result_preview && (
                        <ToolDetailBlock label="Result" tone="neutral">{entry.result_preview}</ToolDetailBlock>
                    )}
                    {entry.credential_name && (
                        <button
                            onClick={(e) => {
                                e.stopPropagation();
                                openCreateCredential({
                                    credentialType: entry.credential_type ?? undefined,
                                    credentialId: entry.credential_id ?? undefined,
                                });
                            }}
                            className="inline-flex items-center gap-1.5 text-[0.6875rem] text-foreground/60 hover:text-foreground bg-foreground/[0.05] hover:bg-foreground/[0.08] border border-foreground/[0.06] hover:border-foreground/[0.12] rounded-full pl-1.5 pr-2.5 py-1 transition-colors"
                            title="Edit credential"
                        >
                            <KeyRound className="w-3 h-3 text-foreground/40" />
                            <span className="truncate max-w-[14rem]">{entry.credential_name}</span>
                        </button>
                    )}
                </div>
            )}
        </div>
    );
}

// Tool calls collapse into runs — one run = one agent invocation (keyed by
// execution / conversation), so the firehose reads as "this agent did N things."
interface RunGroup {
    key: string;
    entries: ToolCallEntry[];
    agentLabel: string;
    agentNodeId: string | null;
    agentType: string | null;
    agentModel: string | null;
    workflowId: string | null;
    workflowName: string | null;
    callCount: number;
    errorCount: number;
    totalDuration: number;
    lastAt: string;
    agentResponse?: string;
}

function groupByRun(entries: ToolCallEntry[], responses: Record<string, string>): RunGroup[] {
    const groups = new Map<string, RunGroup>();
    for (const e of entries) {
        const key = e.execution_id || e.conversation_id || e.agent_node_id || e.id;
        let g = groups.get(key);
        if (!g) {
            // entries arrive newest-first, so the first one seen is the latest
            g = {
                key, entries: [], agentLabel: e.agent_node_label || 'Agent',
                agentNodeId: e.agent_node_id, agentType: e.agent_node_type, agentModel: e.agent_model,
                workflowId: e.workflow_id, workflowName: e.workflow_name,
                callCount: 0, errorCount: 0, totalDuration: 0, lastAt: e.created_at,
                agentResponse: e.execution_id ? responses[e.execution_id] : undefined,
            };
            groups.set(key, g);
        }
        g.entries.push(e);
        g.callCount += 1;
        if (e.result_status === 'error') g.errorCount += 1;
        g.totalDuration += e.duration_ms || 0;
    }
    // flip each run to chronological order so it reads top-to-bottom as it ran
    for (const g of groups.values()) g.entries.reverse();
    return Array.from(groups.values());
}

// Model / harness chip shown after the agent name. Harnesses (Codex, Claude
// Code, OpenCode, OpenClaw, Hermes) get their brand logo via AgentModelIcon —
// the canvas's single source of truth — clamped to an inline size; plain LLM
// models show just the short name.
function ModelBadge({ model }: { model: string }) {
    return (
        <span className="inline-flex items-center gap-1 flex-shrink-0 text-[0.6875rem] text-foreground/50 bg-foreground/[0.05] border border-foreground/[0.06] rounded-full px-2 py-0.5">
            {isCliAgentModel(model) && (
                <AgentModelIcon model={model} variant="compact" stateClassName="!h-3.5 !w-auto max-w-[3.5rem] object-contain" />
            )}
            <span className="truncate max-w-[8rem]">{modelShortName(model)}</span>
        </span>
    );
}

function RunGroupCard({ group }: { group: RunGroup }) {
    const [collapsed, setCollapsed] = useState(false);
    const [showResponse, setShowResponse] = useState(false);
    const hasError = group.errorCount > 0;

    // Use the agent node's own icon + brand color so the feed matches the
    // canvas (the AI Agent node is a purple Bot).
    const agentMeta = group.agentType ? getNodeMetadata(group.agentType) : undefined;
    const AgentIcon = (agentMeta?.Icon as BrandIconComponent) || Bot;
    const agentColor = agentMeta?.iconColor || 'text-purple-400';

    return (
        <div className="rounded-xl border border-border dark:border-foreground/[0.06] bg-card dark:bg-foreground/[0.03] overflow-hidden">
            {/* Run header — caret sits just right of the agent name */}
            <div
                onClick={() => setCollapsed(c => !c)}
                className="flex items-center gap-3 px-4 py-3 cursor-pointer hover:bg-foreground/[0.02] transition-colors"
            >
                <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-foreground/[0.06] flex-shrink-0">
                    <BrandIcon Icon={AgentIcon} iconColor={agentColor} className="w-4 h-4" />
                </div>
                <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5 min-w-0">
                        {group.workflowId && group.agentNodeId ? (
                            <button
                                onClick={(e) => { e.stopPropagation(); goToWorkflowNode(group.workflowId!, group.agentNodeId!); }}
                                className="text-[0.9375rem] font-medium text-foreground leading-tight truncate hover:underline decoration-foreground/30 underline-offset-2 min-w-0"
                            >
                                {group.agentLabel}
                            </button>
                        ) : (
                            <span className="text-[0.9375rem] font-medium text-foreground leading-tight truncate min-w-0">{group.agentLabel}</span>
                        )}
                        <ChevronRight className={cn('w-3.5 h-3.5 text-foreground/40 flex-shrink-0 transition-transform duration-200', !collapsed && 'rotate-90')} />
                        {group.agentModel && <span className="ml-0.5"><ModelBadge model={group.agentModel} /></span>}
                    </div>
                    <div className="flex items-center gap-1.5 text-xs text-foreground/40 mt-0.5 min-w-0">
                        {group.workflowId && (
                            <button
                                onClick={(e) => { e.stopPropagation(); goToWorkflowNode(group.workflowId!, group.agentNodeId || ''); }}
                                className="inline-flex items-center gap-1 hover:text-foreground/70 transition-colors min-w-0"
                            >
                                <Workflow className="w-3 h-3 flex-shrink-0" />
                                <span className="truncate max-w-[12rem]">{group.workflowName || 'Untitled Workflow'}</span>
                            </button>
                        )}
                        <span className="text-foreground/30">·</span>
                        <span className="tabular-nums whitespace-nowrap">{timeAgo(group.lastAt)}</span>
                    </div>
                </div>

                <div className="flex items-center gap-2 flex-shrink-0">
                    <span className="text-[0.6875rem] text-foreground/50 bg-foreground/[0.06] px-2 py-0.5 rounded-full whitespace-nowrap">
                        {group.callCount} {group.callCount === 1 ? 'call' : 'calls'}
                    </span>
                    {hasError && (
                        <span className="text-[0.6875rem] font-medium text-red-600 dark:text-red-300 bg-red-500/15 px-2 py-0.5 rounded-full whitespace-nowrap">
                            {group.errorCount} failed
                        </span>
                    )}
                    {group.totalDuration > 0 && (
                        <span className="text-[0.6875rem] text-foreground/30 tabular-nums whitespace-nowrap hidden sm:inline">{formatDuration(group.totalDuration)}</span>
                    )}
                </div>
            </div>

            {!collapsed && (
                <>
                    <div className="border-t border-foreground/[0.06] divide-y divide-foreground/[0.04]">
                        {group.entries.map(entry => <ToolCallRow key={entry.id} entry={entry} />)}
                    </div>
                    {group.agentResponse && (
                        <div className="border-t border-foreground/[0.06]">
                            <button
                                onClick={() => setShowResponse(s => !s)}
                                className="w-full flex items-center gap-1.5 px-4 py-2.5 hover:bg-foreground/[0.02] transition-colors text-left"
                            >
                                <BrandIcon Icon={AgentIcon} iconColor={agentColor} className="w-3 h-3 flex-shrink-0" />
                                <span className="text-[0.625rem] uppercase tracking-wide text-foreground/30 flex-shrink-0">Agent response</span>
                                {!showResponse && (
                                    <span className="text-xs text-foreground/40 truncate min-w-0">{group.agentResponse}</span>
                                )}
                                <ChevronDown className={cn('w-3.5 h-3.5 text-foreground/30 ml-auto flex-shrink-0 transition-transform duration-200', showResponse && 'rotate-180')} />
                            </button>
                            {showResponse && (
                                <p className="px-4 pb-3.5 text-[0.8125rem] text-foreground/80 leading-relaxed whitespace-pre-wrap break-words">
                                    {group.agentResponse}
                                </p>
                            )}
                        </div>
                    )}
                </>
            )}
        </div>
    );
}

function AgentStatusFilters({ statusFilter, onStatusChange }: {
    statusFilter: 'all' | 'success' | 'error';
    onStatusChange: (status: 'all' | 'success' | 'error') => void;
}) {
    const options: { key: 'all' | 'success' | 'error'; label: string; icon: any; color: string }[] = [
        { key: 'all', label: 'All', icon: null, color: '' },
        { key: 'success', label: 'Success', icon: CheckCircle2, color: 'text-emerald-600 dark:text-emerald-400' },
        { key: 'error', label: 'Error', icon: XCircle, color: 'text-red-600 dark:text-red-400' },
    ];

    return (
        <div className="px-5 pb-3 flex items-center gap-1.5 flex-wrap">
            {options.map(opt => {
                const active = statusFilter === opt.key;
                return (
                    <button
                        key={opt.key}
                        onClick={() => onStatusChange(opt.key)}
                        className={cn(
                            'h-7 px-2.5 rounded-md text-[0.6875rem] font-medium transition-all flex items-center gap-1.5',
                            active ? 'bg-foreground/[0.1] text-foreground' : 'text-muted-foreground/70 dark:text-zinc-500 hover:text-muted-foreground dark:hover:text-zinc-300 hover:bg-foreground/[0.03]'
                        )}
                    >
                        {opt.icon && <opt.icon className={cn('w-3 h-3', active ? opt.color : '')} />}
                        {opt.label}
                    </button>
                );
            })}
        </div>
    );
}

// ============================================================================
// Bulk Action Bar
// ============================================================================

function BulkActionBar({ selectedCount, totalCount, onSelectAll, onClearAll, onBulkApprove, onBulkReject, isProcessing }: {
    selectedCount: number;
    totalCount: number;
    onSelectAll: () => void;
    onClearAll: () => void;
    onBulkApprove: () => void;
    onBulkReject: () => void;
    isProcessing: boolean;
}) {
    return (
        <div className="mx-4 sm:mx-6 mb-3 px-4 py-2.5 rounded-xl border border-border dark:border-white/[0.14] bg-card dark:bg-foreground/[0.07] backdrop-blur-sm flex items-center gap-3">
            <button
                onClick={selectedCount === totalCount ? onClearAll : onSelectAll}
                className="flex items-center gap-2 text-xs text-muted-foreground hover:text-foreground transition-colors"
            >
                <CheckSquare className="w-3.5 h-3.5" />
                {selectedCount === totalCount ? 'Deselect all' : 'Select all'}
            </button>
            <span className="text-muted-foreground/50 dark:text-zinc-700 text-xs">{selectedCount} selected</span>
            <div className="flex-1" />
            <button
                onClick={onClearAll}
                className="text-xs text-muted-foreground dark:text-zinc-500 hover:text-foreground/80 transition-colors px-2 py-1"
            >
                Cancel
            </button>
            <button
                onClick={onBulkReject}
                disabled={isProcessing}
                className="h-[1.875rem] px-3.5 rounded-md text-xs font-medium text-foreground/80 bg-foreground/10 border border-border dark:border-white/10 hover:bg-foreground/[0.15] disabled:opacity-40 transition-colors"
            >
                Reject {selectedCount > 1 ? `(${selectedCount})` : ''}
            </button>
            <button
                onClick={onBulkApprove}
                disabled={isProcessing}
                className="h-[1.875rem] px-3.5 rounded-md text-xs font-medium text-primary-foreground bg-primary hover:bg-primary/90 disabled:opacity-40 transition-colors"
            >
                Approve {selectedCount > 1 ? `(${selectedCount})` : ''}
            </button>
        </div>
    );
}

// ============================================================================
// Main Feed
// ============================================================================

export function Feed({ initialWorkflowFilter }: { initialWorkflowFilter?: string }) {
    const { pending, resolved, loading, error, respond, refresh } = useApprovalFeed();
    const activity = useActivityLog();
    const agents = useToolCallEvents();
    const [tab, setTab] = useState<'pending' | 'processed' | 'activity' | 'agents'>('pending');
    const [levelFilter, setLevelFilter] = useState<LogLevel | 'all'>('all');
    const [agentStatusFilter, setAgentStatusFilter] = useState<'all' | 'success' | 'error'>('all');
    const [workflowFilter, setWorkflowFilter] = useState<string | 'all'>(initialWorkflowFilter ?? 'all');

    // Track whether the user has ever responded to an approval this session,
    // so we don't flash the demo video while waiting for the resolved list to update.
    const hasRespondedRef = useRef(false);
    const wrappedRespond: typeof respond = (...args) => {
        hasRespondedRef.current = true;
        return respond(...args);
    };

    // Bulk selection state
    const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
    const [bulkProcessing, setBulkProcessing] = useState(false);

    const toggleSelect = useCallback((id: string) => {
        setSelectedIds(prev => {
            const next = new Set(prev);
            if (next.has(id)) next.delete(id); else next.add(id);
            return next;
        });
    }, []);

    // Clear selection whenever pending list changes (items removed after respond)
    useEffect(() => {
        setSelectedIds(prev => {
            if (prev.size === 0) return prev;
            const pendingIds = new Set(pending.map(a => a.id));
            const next = new Set([...prev].filter(id => pendingIds.has(id)));
            return next.size === prev.size ? prev : next;
        });
    }, [pending]);

    const handleBulkAction = useCallback(async (decision: 'approved' | 'rejected') => {
        const ids = [...selectedIds];
        if (ids.length === 0) return;
        setBulkProcessing(true);
        setSelectedIds(new Set());
        hasRespondedRef.current = true;
        // Fire all requests concurrently; each respond call returns a promise
        await Promise.all(ids.map(id => respond(id, decision)));
        setBulkProcessing(false);
    }, [selectedIds, respond]);

    // Sync workflowFilter with prop — handles the race condition when
    // handleTabChange clears the URL workflow param asynchronously after
    // Feed has already mounted with the stale value.
    useEffect(() => {
        setWorkflowFilter(initialWorkflowFilter ?? 'all');
    }, [initialWorkflowFilter]);

    useEffect(() => {
        if (pending.length > 0 && tab !== 'pending') setTab('pending');
    }, [pending.length]);

    // Derive unique workflows across ALL feed data for the global filter
    const allWorkflows = useMemo(() => {
        const seen = new Map<string, string>();
        for (const a of pending) {
            if (!seen.has(a.workflow_id)) seen.set(a.workflow_id, a.workflow_name);
        }
        for (const a of resolved) {
            if (!seen.has(a.workflow_id)) seen.set(a.workflow_id, a.workflow_name);
        }
        for (const e of activity.entries) {
            if (!seen.has(e.workflow_id)) seen.set(e.workflow_id, e.workflow_name);
        }
        for (const t of agents.entries) {
            if (t.workflow_id && !seen.has(t.workflow_id)) seen.set(t.workflow_id, t.workflow_name || 'Untitled Workflow');
        }
        return Array.from(seen, ([id, name]) => ({ id, name })).sort((a, b) => a.name.localeCompare(b.name));
    }, [pending, resolved, activity.entries, agents.entries]);

    // Apply workflow filter to each data source
    const filteredPending = useMemo(() =>
        workflowFilter === 'all' ? pending : pending.filter(a => a.workflow_id === workflowFilter),
    [pending, workflowFilter]);

    const filteredResolved = useMemo(() =>
        workflowFilter === 'all' ? resolved : resolved.filter(a => a.workflow_id === workflowFilter),
    [resolved, workflowFilter]);

    const filteredActivity = useMemo(() =>
        activity.entries.filter(e => {
            if (levelFilter !== 'all' && e.level !== levelFilter) return false;
            if (workflowFilter !== 'all' && e.workflow_id !== workflowFilter) return false;
            return true;
        }),
    [activity.entries, levelFilter, workflowFilter]);

    const filteredAgents = useMemo(() =>
        agents.entries.filter(t => {
            if (agentStatusFilter !== 'all' && t.result_status !== agentStatusFilter) return false;
            if (workflowFilter !== 'all' && t.workflow_id !== workflowFilter) return false;
            return true;
        }),
    [agents.entries, agentStatusFilter, workflowFilter]);

    const groupedAgents = useMemo(() => groupByRun(filteredAgents, agents.responses), [filteredAgents, agents.responses]);

    return (
        <div className="h-full flex flex-col relative overflow-hidden">
            {/* Dot grid background */}
            <div
                className="absolute inset-0 pointer-events-none z-0"
                style={{
                    backgroundImage: 'radial-gradient(circle, hsl(var(--foreground) / 0.15) 1px, transparent 1px)',
                    backgroundSize: '24px 24px',
                    maskImage: 'radial-gradient(ellipse 90% 60% at 50% 50%, black 50%, transparent 100%)',
                    WebkitMaskImage: 'radial-gradient(ellipse 90% 60% at 50% 50%, black 50%, transparent 100%)',
                }}
            />

            {/* Ambient color blobs — gives the glass something to frost over */}
            <div className="absolute inset-0 pointer-events-none z-0 overflow-hidden">
                <div className="absolute -top-20 -left-20 w-[400px] h-[400px] rounded-full bg-purple-500/[0.04] blur-[120px]" />
                <div className="absolute top-40 -right-20 w-[350px] h-[350px] rounded-full bg-blue-500/[0.04] blur-[120px]" />
                <div className="absolute bottom-20 left-1/3 w-[300px] h-[300px] rounded-full bg-teal-500/[0.03] blur-[120px]" />
            </div>

            {/* Header */}
            <div className="px-4 sm:px-6 pt-6 pb-4 flex-shrink-0 relative flex items-center gap-2">
                <h1 className="text-3xl font-semibold text-foreground tracking-tight ml-1">Feed</h1>
                <button onClick={() => { refresh(); activity.refresh(); agents.refresh(); }} disabled={loading || activity.loading || agents.loading}
                    className="p-1.5 rounded-md text-muted-foreground/70 dark:text-zinc-600 hover:text-muted-foreground transition-colors disabled:opacity-40 mt-1"
                    title="Refresh">
                    <RefreshCw className={cn('w-3.5 h-3.5', (loading || activity.loading || agents.loading) && 'animate-spin')} />
                </button>
            </div>

            {/* Tab bar + workflow filter */}
            <div className="px-4 sm:px-6 pb-4 relative z-10 flex flex-wrap items-center gap-3">
                <div className="flex rounded-lg border border-border bg-muted p-0.5 gap-0.5 dark:border-foreground/[0.08] dark:bg-foreground/[0.02] w-fit max-w-full overflow-x-auto scrollbar-hide">
                    <button
                        onClick={() => setTab('pending')}
                        className={cn(
                            'h-7 rounded-md px-3 text-xs font-medium transition-colors flex items-center gap-1.5 shrink-0',
                            tab === 'pending' ? 'bg-card text-foreground shadow-sm dark:bg-foreground/[0.1] dark:shadow-none' : 'text-foreground/50 hover:text-foreground/80 hover:bg-foreground/[0.04]'
                        )}
                    >
                        <ShieldCheck className="w-3.5 h-3.5" />
                        Pending
                        {pending.length > 0 && (
                            <span className={cn(
                                'text-[0.625rem] min-w-[1.125rem] h-[1.125rem] rounded-full flex items-center justify-center font-semibold',
                                tab === 'pending' ? 'bg-foreground/15 text-foreground' : 'bg-foreground/[0.06] text-muted-foreground dark:text-zinc-500'
                            )}>
                                {pending.length}
                            </span>
                        )}
                    </button>
                    <button
                        onClick={() => setTab('processed')}
                        className={cn(
                            'h-7 rounded-md px-3 text-xs font-medium transition-colors flex items-center gap-1.5 shrink-0',
                            tab === 'processed' ? 'bg-card text-foreground shadow-sm dark:bg-foreground/[0.1] dark:shadow-none' : 'text-foreground/50 hover:text-foreground/80 hover:bg-foreground/[0.04]'
                        )}
                    >
                        <Check className="w-3.5 h-3.5" />
                        Processed
                        {resolved.length > 0 && (
                            <span className={cn(
                                'text-[0.625rem] min-w-[1.125rem] h-[1.125rem] rounded-full flex items-center justify-center font-semibold',
                                tab === 'processed' ? 'bg-foreground/15 text-foreground' : 'bg-foreground/[0.06] text-muted-foreground dark:text-zinc-500'
                            )}>
                                {resolved.length}
                            </span>
                        )}
                    </button>
                    <button
                        onClick={() => setTab('activity')}
                        className={cn(
                            'h-7 rounded-md px-3 text-xs font-medium transition-colors flex items-center gap-1.5 shrink-0',
                            tab === 'activity' ? 'bg-card text-foreground shadow-sm dark:bg-foreground/[0.1] dark:shadow-none' : 'text-foreground/50 hover:text-foreground/80 hover:bg-foreground/[0.04]'
                        )}
                    >
                        <ScrollText className="w-3.5 h-3.5" />
                        Activity
                    </button>
                    <button
                        onClick={() => setTab('agents')}
                        className={cn(
                            'h-7 rounded-md px-3 text-xs font-medium transition-colors flex items-center gap-1.5 shrink-0',
                            tab === 'agents' ? 'bg-card text-foreground shadow-sm dark:bg-foreground/[0.1] dark:shadow-none' : 'text-foreground/50 hover:text-foreground/80 hover:bg-foreground/[0.04]'
                        )}
                    >
                        <Bot className="w-3.5 h-3.5" />
                        Agents
                    </button>
                </div>

                {/* Workflow filter */}
                {allWorkflows.length > 1 && (
                    <WorkflowFilterDropdown
                        value={workflowFilter}
                        workflows={allWorkflows}
                        onChange={setWorkflowFilter}
                    />
                )}
            </div>

            {/* Error */}
            {error && (
                <div className="mx-4 sm:mx-6 mb-4 px-3.5 py-2.5 rounded-lg bg-red-500/5 border border-red-500/10 text-xs text-red-600 dark:text-red-400/80">
                    {error}
                </div>
            )}

            {/* Content — the Agents tab sits on a solid themed sheet (bg-background,
                identical black in dark mode) so the translucent cards read with full
                contrast instead of washing out over the dotted-glass bg. */}
            <div className={cn('flex-1 overflow-y-auto relative scrollbar-subtle', tab === 'agents' && 'bg-background')}>
                {tab === 'pending' && (
                    <>
                        {filteredPending.length > 0 ? (
                            <>
                                {selectedIds.size > 0 && (
                                    <BulkActionBar
                                        selectedCount={selectedIds.size}
                                        totalCount={filteredPending.length}
                                        onSelectAll={() => setSelectedIds(new Set(filteredPending.map(a => a.id)))}
                                        onClearAll={() => setSelectedIds(new Set())}
                                        onBulkApprove={() => handleBulkAction('approved')}
                                        onBulkReject={() => handleBulkAction('rejected')}
                                        isProcessing={bulkProcessing}
                                    />
                                )}
                            <div className="px-4 sm:px-6 pb-6 flex flex-col">
                                {filteredPending.map(approval => (
                                    <PendingCard
                                        key={approval.id}
                                        approval={approval}
                                        onRespond={wrappedRespond}
                                        isSelected={selectedIds.has(approval.id)}
                                        onToggleSelect={toggleSelect}
                                    />
                                ))}
                            </div>
                            </>
                        ) : !loading && (
                            resolved.length === 0 && !hasRespondedRef.current ? (
                                /* User has never processed an approval — show demo video */
                                <div className="flex flex-col items-center px-4 sm:px-6 pt-2 pb-6">
                                    <p className="text-sm font-medium text-muted-foreground mb-1">No approval requests yet</p>
                                    <p className="text-xs text-muted-foreground/70 dark:text-zinc-600 mb-5 text-center max-w-sm">
                                        Add an approval node to your workflow to pause execution and collect decisions here.
                                    </p>
                                    {!isLocalEdition() && (
                                        <div className="w-full max-w-[67.5rem] rounded-xl overflow-hidden border border-border dark:border-white/[0.06] bg-card dark:bg-foreground/[0.02]">
                                            <video
                                                src="/checklist_webms/approval_feed.webm"
                                                muted
                                                loop
                                                autoPlay
                                                playsInline
                                                className="w-full h-auto"
                                            />
                                        </div>
                                    )}
                                </div>
                            ) : (
                                /* User has processed approvals before — show "all clear" */
                                <div className="flex flex-col items-center justify-center py-24 px-4 sm:px-6">
                                    {/* Animated check circle */}
                                    <div className="mb-5">
                                        <svg width="56" height="56" viewBox="0 0 56 56" fill="none">
                                            <circle className="text-foreground/[0.12]" cx="28" cy="28" r="26" stroke="currentColor" strokeWidth="2" fill="none"
                                                strokeDasharray="163" strokeDashoffset="163"
                                                style={{ animation: 'circle-draw 600ms ease-out forwards' }} />
                                            <path className="text-foreground/50" d="M18 28.5l7 7 13-13" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"
                                                fill="none" strokeDasharray="35" strokeDashoffset="35"
                                                style={{ animation: 'check-draw 400ms ease-out 400ms forwards' }} />
                                        </svg>
                                    </div>
                                    <div className="text-xl text-foreground/80 font-medium">All clear</div>
                                    <div className="text-[0.9375rem] text-muted-foreground dark:text-zinc-500 mt-2.5 text-center max-w-[20rem] leading-relaxed">
                                        No approval requests pending. You're all caught up.
                                    </div>
                                    <button
                                        onClick={() => navigateToTab('flow')}
                                        className="mt-7 h-[2.375rem] px-6 rounded-lg text-sm font-medium text-primary-foreground bg-primary shadow-[0_2.5px_0_0_#a0a0a0] hover:shadow-[0_1px_0_0_#a0a0a0] hover:translate-y-[1.5px] active:shadow-none active:translate-y-[2.5px] transition-all duration-100"
                                    >
                                        Back to Workflows
                                    </button>
                                </div>
                            )
                        )}
                    </>
                )}

                {tab === 'processed' && (
                    <>
                        {filteredResolved.length > 0 ? (
                            <div className="px-4 sm:px-6 pb-6 space-y-2">
                                {filteredResolved.map(approval => (
                                    <ProcessedCard key={approval.id} approval={approval} onRedo={wrappedRespond} />
                                ))}
                            </div>
                        ) : (
                            <div className="flex flex-col items-center justify-center py-24 px-4 sm:px-6">
                                <div className="w-12 h-12 rounded-xl bg-sunken border border-border dark:border-white/[0.05] flex items-center justify-center mb-4">
                                    <Check className="w-5 h-5 text-muted-foreground/50 dark:text-zinc-700" />
                                </div>
                                <div className="text-[0.9375rem] text-muted-foreground dark:text-zinc-500 font-medium">No history yet</div>
                                <div className="text-[0.8125rem] text-muted-foreground/70 dark:text-zinc-600 mt-1.5">Processed approvals will appear here</div>
                            </div>
                        )}
                    </>
                )}

                {tab === 'activity' && (
                    <>
                        {activity.error && (
                            <div className="mx-4 sm:mx-6 mb-4 px-3.5 py-2.5 rounded-lg bg-red-500/5 border border-red-500/10 text-xs text-red-600 dark:text-red-400/80">
                                {activity.error}
                            </div>
                        )}
                        {activity.entries.length > 0 ? (
                            <>
                                <ActivityLevelFilters
                                    levelFilter={levelFilter}
                                    onLevelChange={setLevelFilter}
                                />
                                {filteredActivity.length > 0 ? (
                                    <div className="pb-6">
                                        {filteredActivity.map(entry => (
                                            <ActivityRow key={entry.id} entry={entry} />
                                        ))}
                                    </div>
                                ) : (
                                    <div className="flex flex-col items-center justify-center py-16 px-4 sm:px-6">
                                        <div className="text-[0.8125rem] text-muted-foreground dark:text-zinc-500">No entries match the current filters</div>
                                    </div>
                                )}
                            </>
                        ) : !activity.loading && (
                            <div className="flex flex-col items-center px-4 sm:px-6 pt-2 pb-6">
                                <p className="text-sm font-medium text-muted-foreground mb-1">No activity yet</p>
                                <p className="text-xs text-muted-foreground/70 dark:text-zinc-600 mb-5 text-center max-w-sm">
                                    Add log nodes to your workflows to track activity here.
                                </p>
                                {!isLocalEdition() && (
                                    <div className="w-full max-w-[67.5rem] rounded-xl overflow-hidden border border-border dark:border-white/[0.06] bg-card dark:bg-foreground/[0.02]">
                                        <video
                                            src="/checklist_webms/activity_feed.webm"
                                            muted
                                            loop
                                            autoPlay
                                            playsInline
                                            className="w-full h-auto"
                                        />
                                    </div>
                                )}
                            </div>
                        )}
                    </>
                )}

                {tab === 'agents' && (
                    <>
                        {agents.error && (
                            <div className="mx-4 sm:mx-6 mb-4 px-3.5 py-2.5 rounded-lg bg-red-500/5 border border-red-500/10 text-xs text-red-600 dark:text-red-400/80">
                                {agents.error}
                            </div>
                        )}
                        {agents.entries.length > 0 ? (
                            <>
                                <AgentStatusFilters
                                    statusFilter={agentStatusFilter}
                                    onStatusChange={setAgentStatusFilter}
                                />
                                {groupedAgents.length > 0 ? (
                                    <div className="px-4 sm:px-6 pb-6 space-y-2.5">
                                        {groupedAgents.map(group => (
                                            <RunGroupCard key={group.key} group={group} />
                                        ))}
                                    </div>
                                ) : (
                                    <div className="flex flex-col items-center justify-center py-16 px-4 sm:px-6">
                                        <div className="text-[0.8125rem] text-foreground/50">No tool calls match the current filters</div>
                                    </div>
                                )}
                            </>
                        ) : !agents.loading && (
                            <div className="flex flex-col items-center justify-center py-24 px-4 sm:px-6">
                                <div className="w-12 h-12 rounded-xl bg-foreground/[0.03] border border-foreground/[0.06] flex items-center justify-center mb-4">
                                    <Bot className="w-5 h-5 text-foreground/30" />
                                </div>
                                <div className="text-[0.9375rem] text-foreground/70 font-medium">No agent activity yet</div>
                                <div className="text-[0.8125rem] text-foreground/40 mt-1.5 text-center max-w-[22rem] leading-relaxed">
                                    When an AI agent in your workflows calls a tool, each call is logged here with its arguments and result.
                                </div>
                            </div>
                        )}
                    </>
                )}
            </div>
        </div>
    );
}
