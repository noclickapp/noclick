/**
 * WorkflowCheckpointControl - Compact version control for workflows.
 * Unified popover with keyboard navigation, inline save, and quick restore.
 */

import React, { useState, useCallback, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { Node, Edge } from '@xyflow/react';
import { History, Plus, Trash2, RotateCcw, Check } from 'lucide-react';
import { Button } from '~/components/ui/button';
import { Popover, PopoverContent, PopoverTrigger } from '~/components/ui/popover';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '~/components/ui/tooltip';
import { KeyHint } from '~/components/shared/KeyHint';
import { cn } from '~/lib/utils';
import { sendEventWithCallback } from '~/lib/socket-sender';
import { createWorkflowNode } from '~/lib/applyNodeUpdate';
import type {
    CheckpointInfo,
    WorkflowCheckpointListResponse,
    WorkflowCheckpointCreateResponse,
    WorkflowCheckpointRestoreResponse,
    WorkflowCheckpointDeleteResponse,
} from '~/types/socket-events.generated';
import {
    WorkflowCheckpointCreateRequest,
    WorkflowCheckpointListRequest,
    WorkflowCheckpointRestoreRequest,
    WorkflowCheckpointDeleteRequest,
} from '~/types/socket-events.generated';
import { applyEdgeStyle } from '~/utils/workflowLayout';
import { fuzzyFilter } from '~/utils/fuzzySearch';
import { UpgradePopup } from '~/components/utils/UpgradePopup';
import { isPlanLimitError } from '~/lib/planLimitErrors';

interface WorkflowCheckpointControlProps {
    workflowId?: string;
    nodes: Node[];
    edges: Edge[];
    onRestore: (nodes: Node[], edges: Edge[]) => void;
    compact?: boolean;
}

// Format relative time compactly
function formatRelativeTime(dateString: string): string {
    const date = new Date(dateString);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMinutes = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMinutes / 60);
    const diffDays = Math.floor(diffHours / 24);

    if (diffDays > 0) return `${diffDays}d`;
    if (diffHours > 0) return `${diffHours}h`;
    if (diffMinutes > 0) return `${diffMinutes}m`;
    return 'now';
}

export function WorkflowCheckpointControl({
    workflowId,
    nodes,
    edges,
    onRestore,
    compact = false,
}: WorkflowCheckpointControlProps) {
    const [checkpoints, setCheckpoints] = useState<CheckpointInfo[]>([]);
    const [isLoading, setIsLoading] = useState(false);
    const [isOpen, setIsOpen] = useState(false);
    const [checkpointName, setCheckpointName] = useState('');
    const [isSaving, setIsSaving] = useState(false);
    const [isRestoring, setIsRestoring] = useState(false);
    const [confirmRestoreId, setConfirmRestoreId] = useState<string | null>(null);
    const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
    const [isDeleting, setIsDeleting] = useState(false);
    const [showSaveSuccess, setShowSaveSuccess] = useState(false);
    const [planLimitError, setPlanLimitError] = useState<string | null>(null);
    const [selectedIndex, setSelectedIndex] = useState(-1);
    const inputRef = useRef<HTMLInputElement>(null);
    const listRef = useRef<HTMLDivElement>(null);

    // Load checkpoints
    const loadCheckpoints = useCallback(() => {
        if (!workflowId) return;
        setIsLoading(true);
        sendEventWithCallback(
            WorkflowCheckpointListRequest.create({ workflow_id: workflowId }),
            (response: WorkflowCheckpointListResponse & { error?: string }) => {
                setIsLoading(false);
                if (!response.error) {
                    setCheckpoints(response.checkpoints || []);
                }
            }
        );
    }, [workflowId]);

    // Filter checkpoints based on search input
    const filteredCheckpoints = fuzzyFilter(checkpoints, checkpointName, cp => [
        { text: cp.name.toLowerCase(), weight: 1, fuzzy: true },
    ]);

    // Load on open
    useEffect(() => {
        if (isOpen) {
            loadCheckpoints();
            setSelectedIndex(-1);
            setTimeout(() => inputRef.current?.focus(), 50);
        }
    }, [isOpen, loadCheckpoints]);

    // Open on the "V" canvas shortcut (dispatched by FlowCanvas).
    useEffect(() => {
        const open = () => setIsOpen(true);
        window.addEventListener('noclick:open-version-history', open);
        return () => window.removeEventListener('noclick:open-version-history', open);
    }, []);

    // Create checkpoint
    const handleCreateCheckpoint = useCallback(() => {
        if (!workflowId || !checkpointName.trim()) return;
        setIsSaving(true);
        sendEventWithCallback(
            WorkflowCheckpointCreateRequest.create({
                workflow_id: workflowId,
                name: checkpointName.trim(),
                description: '',
            }),
            (response: WorkflowCheckpointCreateResponse & { error?: string }) => {
                setIsSaving(false);
                if (response.error && isPlanLimitError(response.error)) {
                    setPlanLimitError(response.error);
                } else if (!response.error && response.success && response.checkpoint) {
                    setCheckpoints(prev => [response.checkpoint!, ...prev]);
                    setShowSaveSuccess(true);
                    setTimeout(() => setShowSaveSuccess(false), 1500);
                }
                setCheckpointName('');
                inputRef.current?.focus();
            }
        );
    }, [workflowId, checkpointName]);

    // Restore checkpoint
    const handleRestoreCheckpoint = useCallback((checkpointId: string) => {
        if (!workflowId) return;
        setIsRestoring(true);
        sendEventWithCallback(
            WorkflowCheckpointRestoreRequest.create({
                workflow_id: workflowId,
                checkpoint_id: checkpointId,
            }),
            (response: WorkflowCheckpointRestoreResponse & { error?: string }) => {
                setIsRestoring(false);
                setConfirmRestoreId(null);
                if (!response.error && response.success && response.workflow) {
                    const workflowData = response.workflow as { nodes?: any[]; edges?: any[] };
                    const restoredNodes = (workflowData.nodes || []).map((node: any) => {
                        if (!node.config) {
                            console.error('[WorkflowCheckpointControl] Node missing config in checkpoint:', node);
                            throw new Error(`Checkpoint node ${node.id} is missing config`);
                        }
                        // node.config is the flat saved blob — createWorkflowNode
                        // builds the proper data.config shape from it.
                        const restored = createWorkflowNode(node.id, node.type, node.position, node.config);
                        if (node.width != null) restored.width = node.width;
                        if (node.height != null) restored.height = node.height;
                        return restored;
                    });
                    const restoredEdges = (workflowData.edges || []).map((edge: any) => applyEdgeStyle({
                        id: edge.id,
                        source: edge.source,
                        target: edge.target,
                        sourceHandle: edge.sourceHandle,
                        targetHandle: edge.targetHandle,
                    }));
                    onRestore(restoredNodes, restoredEdges);
                }
                setIsOpen(false);
            }
        );
    }, [workflowId, onRestore]);

    // Delete checkpoint
    const handleDeleteCheckpoint = useCallback((checkpointId: string) => {
        setIsDeleting(true);
        sendEventWithCallback(
            WorkflowCheckpointDeleteRequest.create({ checkpoint_id: checkpointId }),
            (response: WorkflowCheckpointDeleteResponse & { error?: string }) => {
                setIsDeleting(false);
                setConfirmDeleteId(null);
                if (!response.error && response.success) {
                    setCheckpoints(prev => prev.filter(cp => cp.id !== checkpointId));
                }
            }
        );
    }, []);

    // Get checkpoint name for confirmation dialogs
    const getCheckpointName = useCallback((id: string | null) => {
        if (!id) return '';
        return checkpoints.find(cp => cp.id === id)?.name || 'this version';
    }, [checkpoints]);

    // Keyboard navigation
    const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
        const maxIndex = filteredCheckpoints.length - 1;

        switch (e.key) {
            case 'ArrowDown':
                e.preventDefault();
                setSelectedIndex(prev => Math.min(prev + 1, maxIndex));
                break;
            case 'ArrowUp':
                e.preventDefault();
                setSelectedIndex(prev => Math.max(prev - 1, -1));
                if (selectedIndex === 0) inputRef.current?.focus();
                break;
            case 'Enter':
                e.preventDefault();
                if (selectedIndex >= 0 && filteredCheckpoints[selectedIndex]) {
                    setIsOpen(false);
                    setConfirmRestoreId(filteredCheckpoints[selectedIndex].id);
                } else if (checkpointName.trim() && filteredCheckpoints.length === 0) {
                    // Only save if there are no matching results (no ambiguity)
                    handleCreateCheckpoint();
                } else if (checkpointName.trim() && filteredCheckpoints.length > 0 && selectedIndex === -1) {
                    // If there are matches but nothing selected, save as new
                    handleCreateCheckpoint();
                }
                break;
            case 'Escape':
                e.preventDefault();
                setIsOpen(false);
                break;
        }
    }, [filteredCheckpoints, selectedIndex, checkpointName, handleCreateCheckpoint]);

    // Scroll selected into view
    useEffect(() => {
        if (selectedIndex >= 0 && listRef.current) {
            const el = listRef.current.querySelector(`[data-index="${selectedIndex}"]`);
            el?.scrollIntoView({ block: 'nearest' });
        }
    }, [selectedIndex]);

    if (!workflowId) return null;

    return (
        <>
            <Popover open={isOpen} onOpenChange={setIsOpen}>
                <TooltipProvider delayDuration={200}>
                    <Tooltip>
                        <TooltipTrigger asChild>
                            {/* inline-flex wrapper splits the nested asChild Slots
                                onto separate elements (Tooltip → span, Popover →
                                Button) so neither composed ref churns. Two Popper
                                anchor refs on one element via a nested Slot chain
                                loops to React #185 (radix #3799). The span wraps the
                                button tightly so tooltip anchoring is unchanged. */}
                            <span className="inline-flex">
                                <PopoverTrigger asChild>
                                    <Button
                                        variant="ghost"
                                        size="sm"
                                        className={cn(
                                            "text-muted-foreground hover:text-foreground hover:bg-foreground/5 h-8 rounded-lg transition-colors",
                                            compact ? 'w-8 px-0' : 'px-2.5 gap-1.5'
                                        )}
                                        aria-label="Versions — saved workflow snapshots"
                                    >
                                        <History className="h-4 w-4" />
                                        {!compact && <span className="text-xs font-medium">Versions</span>}
                                    </Button>
                                </PopoverTrigger>
                            </span>
                        </TooltipTrigger>
                        <TooltipContent
                            side="bottom"
                            sideOffset={16}
                            className="rounded-lg border border-border dark:border-white/10 bg-background dark:bg-[#0a0a0b] px-3 py-1.5 text-xs font-medium tracking-tight text-foreground shadow-2xl dark:shadow-black/60 backdrop-blur-md"
                        >
                            <span className="flex items-center gap-2">
                                Versions — saved workflow snapshots
                                <KeyHint keys={['V']} />
                            </span>
                        </TooltipContent>
                    </Tooltip>
                </TooltipProvider>
                <PopoverContent
                    className="w-72 p-0 bg-popover/80 backdrop-blur-2xl border-border dark:border-zinc-700/40 rounded-xl shadow-2xl overflow-hidden"
                    align="start"
                    sideOffset={12}
                    onKeyDown={handleKeyDown}
                >
                    {/* Header */}
                    <div className="px-3 pt-2.5 pb-1.5 flex items-center justify-between">
                        <div className="flex items-center gap-2">
                            <span className="text-[11px] font-medium text-muted-foreground">Version History</span>
                            {checkpoints.length > 0 && (
                                <span className="text-[10px] text-muted-foreground/70 dark:text-zinc-600 tabular-nums">
                                    {checkpointName.trim() && filteredCheckpoints.length !== checkpoints.length
                                        ? `${filteredCheckpoints.length}/${checkpoints.length}`
                                        : `${checkpoints.length} saved`}
                                </span>
                            )}
                        </div>
                    </div>

                    {/* Save input */}
                    <div className="px-2 pb-2 border-b border-border/50 dark:border-zinc-700/30">
                        <div className="relative flex items-center">
                            <input
                                ref={inputRef}
                                type="text"
                                value={checkpointName}
                                onChange={(e) => {
                                    setCheckpointName(e.target.value);
                                    setSelectedIndex(-1); // Reset selection when typing
                                }}
                                onFocus={() => setSelectedIndex(-1)}
                                placeholder={checkpoints.length > 0 ? "Search or save workflow" : "Save current state..."}
                                className="w-full h-8 pl-3 pr-8 text-xs bg-muted dark:bg-zinc-800/60 border border-input dark:border-zinc-700/40 rounded-lg text-foreground placeholder:text-[hsl(var(--placeholder))] focus:outline-none focus:border-muted-foreground/50 dark:focus:border-zinc-600 transition-colors"
                                disabled={isSaving}
                            />
                            <button
                                onClick={handleCreateCheckpoint}
                                disabled={!checkpointName.trim() || isSaving}
                                className="absolute right-1.5 h-5 w-5 flex items-center justify-center rounded-md bg-primary text-primary-foreground disabled:opacity-20 disabled:cursor-not-allowed hover:bg-primary/90 transition-colors"
                            >
                                {showSaveSuccess ? (
                                    <Check className="h-3 w-3 text-emerald-600 dark:text-emerald-400 dark:text-emerald-600" />
                                ) : (
                                    <Plus className="h-3 w-3" />
                                )}
                            </button>
                        </div>
                    </div>

                    {/* Checkpoint list */}
                    <div ref={listRef} className="max-h-52 overflow-y-auto">
                        {isLoading ? (
                            <div className="py-6 flex justify-center">
                                <div className="h-4 w-4 border-2 border-muted-foreground/40 dark:border-zinc-600 border-t-muted-foreground rounded-full animate-spin" />
                            </div>
                        ) : checkpoints.length === 0 ? (
                            <div className="py-6 px-3 text-center">
                                <History className="h-5 w-5 text-muted-foreground/70 dark:text-zinc-600 mx-auto mb-1.5" />
                                <p className="text-xs text-muted-foreground dark:text-zinc-500">No versions saved</p>
                            </div>
                        ) : filteredCheckpoints.length === 0 ? (
                            <div className="py-4 px-3 text-center">
                                <p className="text-xs text-muted-foreground dark:text-zinc-500">No matches</p>
                                <p className="text-[10px] text-muted-foreground/70 dark:text-zinc-600 mt-1">Press Enter to save as "{checkpointName}"</p>
                            </div>
                        ) : (
                            <div className="py-1 px-1">
                                {filteredCheckpoints.map((checkpoint, index) => (
                                    <button
                                        key={checkpoint.id}
                                        data-index={index}
                                        onClick={() => {
                                            setIsOpen(false);
                                            setConfirmRestoreId(checkpoint.id);
                                        }}
                                        onMouseEnter={() => setSelectedIndex(index)}
                                        className={cn(
                                            "w-full flex items-center gap-2 px-2 py-1.5 rounded-lg transition-colors group text-left",
                                            selectedIndex === index
                                                ? "bg-accent dark:bg-zinc-700/60 text-foreground"
                                                : "text-foreground/80 hover:bg-muted dark:hover:bg-zinc-800/60"
                                        )}
                                    >
                                        <div className="flex-1 min-w-0 flex items-center gap-2">
                                            <span className="text-xs font-medium truncate">
                                                {checkpoint.name}
                                            </span>
                                            <span className="text-[10px] text-muted-foreground dark:text-zinc-500 tabular-nums flex-shrink-0">
                                                {formatRelativeTime(checkpoint.created_at)}
                                            </span>
                                        </div>
                                        <button
                                            onClick={(e) => {
                                                e.stopPropagation();
                                                setIsOpen(false);
                                                setConfirmDeleteId(checkpoint.id);
                                            }}
                                            className="p-1 rounded opacity-0 group-hover:opacity-100 hover:bg-red-500/20 transition-opacity"
                                        >
                                            <Trash2 className="h-3 w-3 text-red-600 dark:text-red-400" />
                                        </button>
                                    </button>
                                ))}
                            </div>
                        )}
                    </div>

                    {/* Keyboard hints */}
                    {(checkpoints.length > 0 || checkpointName.trim()) && (
                        <div className="px-2 py-1.5 border-t border-border/50 dark:border-zinc-700/30 flex items-center gap-3 text-[10px] text-muted-foreground dark:text-zinc-500">
                            {filteredCheckpoints.length > 0 && (
                                <span className="flex items-center gap-1">
                                    <kbd className="px-1 bg-foreground/[0.06] ring-1 ring-foreground/10 dark:ring-0 rounded text-muted-foreground">↑↓</kbd>
                                    nav
                                </span>
                            )}
                            <span className="flex items-center gap-1">
                                <kbd className="px-1 bg-foreground/[0.06] ring-1 ring-foreground/10 dark:ring-0 rounded text-muted-foreground">⏎</kbd>
                                {selectedIndex >= 0 ? 'restore' : checkpointName.trim() ? 'save' : 'restore'}
                            </span>
                            <span className="flex items-center gap-1">
                                <kbd className="px-1 bg-foreground/[0.06] ring-1 ring-foreground/10 dark:ring-0 rounded text-muted-foreground">esc</kbd>
                                close
                            </span>
                        </div>
                    )}
                </PopoverContent>
            </Popover>

            {/* Restore confirmation - portaled to escape navbar backdrop-filter clipping */}
            {confirmRestoreId && createPortal(
                <div className="fixed inset-0 z-[200] flex items-center justify-center">
                    <div
                        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
                        onClick={() => setConfirmRestoreId(null)}
                    />
                    <div className="relative bg-popover/95 backdrop-blur-xl border border-border dark:border-zinc-700/50 rounded-2xl shadow-2xl p-4 max-w-xs w-full mx-4 animate-in fade-in-0 zoom-in-95 duration-150">
                        <div className="flex items-start gap-3">
                            <div className="h-9 w-9 rounded-full bg-secondary flex items-center justify-center flex-shrink-0">
                                <RotateCcw className="h-4 w-4 text-muted-foreground" />
                            </div>
                            <div className="flex-1 min-w-0">
                                <h3 className="text-sm font-medium text-foreground">Restore version?</h3>
                                <p className="text-xs text-muted-foreground dark:text-zinc-500 mt-0.5 truncate">
                                    "{getCheckpointName(confirmRestoreId)}"
                                </p>
                            </div>
                        </div>
                        <p className="text-xs text-muted-foreground mt-3">
                            Your current workflow will be replaced with this saved version.
                        </p>
                        <div className="flex gap-2 mt-4">
                            <button
                                onClick={() => setConfirmRestoreId(null)}
                                className="flex-1 h-8 text-xs font-medium text-muted-foreground hover:text-foreground bg-muted dark:bg-zinc-800/60 hover:bg-accent rounded-lg transition-colors"
                            >
                                Cancel
                            </button>
                            <button
                                onClick={() => confirmRestoreId && handleRestoreCheckpoint(confirmRestoreId)}
                                disabled={isRestoring}
                                className="flex-1 h-8 text-xs font-medium text-primary-foreground bg-primary hover:bg-primary/90 rounded-lg transition-colors disabled:opacity-50"
                            >
                                {isRestoring ? 'Restoring...' : 'Restore'}
                            </button>
                        </div>
                    </div>
                </div>,
                document.body
            )}

            {/* Delete confirmation - portaled to escape navbar backdrop-filter clipping */}
            {confirmDeleteId && createPortal(
                <div className="fixed inset-0 z-[200] flex items-center justify-center">
                    <div
                        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
                        onClick={() => setConfirmDeleteId(null)}
                    />
                    <div className="relative bg-popover/95 backdrop-blur-xl border border-border dark:border-zinc-700/50 rounded-2xl shadow-2xl p-4 max-w-xs w-full mx-4 animate-in fade-in-0 zoom-in-95 duration-150">
                        <div className="flex items-start gap-3">
                            <div className="h-9 w-9 rounded-full bg-red-500/10 flex items-center justify-center flex-shrink-0">
                                <Trash2 className="h-4 w-4 text-red-600 dark:text-red-400" />
                            </div>
                            <div className="flex-1 min-w-0">
                                <h3 className="text-sm font-medium text-foreground">Delete version?</h3>
                                <p className="text-xs text-muted-foreground dark:text-zinc-500 mt-0.5 truncate">
                                    "{getCheckpointName(confirmDeleteId)}"
                                </p>
                            </div>
                        </div>
                        <p className="text-xs text-muted-foreground mt-3">
                            This action cannot be undone. The saved version will be permanently removed.
                        </p>
                        <div className="flex gap-2 mt-4">
                            <button
                                onClick={() => setConfirmDeleteId(null)}
                                className="flex-1 h-8 text-xs font-medium text-muted-foreground hover:text-foreground bg-muted dark:bg-zinc-800/60 hover:bg-accent rounded-lg transition-colors"
                            >
                                Cancel
                            </button>
                            <button
                                onClick={() => confirmDeleteId && handleDeleteCheckpoint(confirmDeleteId)}
                                disabled={isDeleting}
                                className="flex-1 h-8 text-xs font-medium text-white bg-red-500/80 hover:bg-red-500 rounded-lg transition-colors disabled:opacity-50"
                            >
                                {isDeleting ? 'Deleting...' : 'Delete'}
                            </button>
                        </div>
                    </div>
                </div>,
                document.body
            )}

            <UpgradePopup
                isOpen={!!planLimitError}
                onOpenChange={(open) => { if (!open) setPlanLimitError(null); }}
                errorMessage={planLimitError || ''}
            />
        </>
    );
}
