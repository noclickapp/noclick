import { useCallback, useEffect, useState } from 'react';
import { Button } from '~/components/ui/button';
import { Skeleton } from '~/components/ui/skeleton';
import { ChevronRight, PanelLeft, RotateCcw, Trash2 } from 'lucide-react';
import { PhoneBarBack, useInPhoneShell } from '~/components/shell/AppShell';
import { cn } from '~/lib/utils';
import { DeleteConfirmPopup } from '~/components/shared/popups/DeleteConfirmPopup';
import { sendEventWithCallback } from '~/lib/socket-sender';
import { clearRemovalTombstone } from '~/lib/workflowBrowserStore';
import {
    WorkflowListTrashRequest,
    WorkflowPermanentDeleteRequest,
    WorkflowRestoreRequest,
    type WorkflowTrashInfo,
} from '~/types/socket-events.generated';
import { PAGE_TITLE } from '~/components/shell/titles';

interface TrashViewProps {
    isMobile: boolean;
    /** A host with a folder sidebar: the phone button that opens it. */
    onOpenMobileSidebar?: () => void;
    /** A host without one: back to the automations. */
    onBack?: () => void;
}

export function TrashView({ isMobile, onOpenMobileSidebar, onBack }: TrashViewProps) {
    const inPhone = useInPhoneShell();
    const [trashWorkflows, setTrashWorkflows] = useState<WorkflowTrashInfo[]>([]);
    const [loadingTrash, setLoadingTrash] = useState(false);
    const [showPermanentDeleteConfirm, setShowPermanentDeleteConfirm] = useState<string | null>(null);

    const fetchTrashWorkflows = useCallback(() => {
        setLoadingTrash(true);
        sendEventWithCallback(WorkflowListTrashRequest.create({}), (response) => {
            setLoadingTrash(false);
            if (response.error) {
                console.error('Failed to load trash:', response.error);
            } else {
                setTrashWorkflows(response.workflows || []);
            }
        });
    }, []);

    useEffect(() => {
        fetchTrashWorkflows();
    }, [fetchTrashWorkflows]);

    const handleRestoreWorkflow = useCallback(
        (workflowId: string) => {
            const restoredItem = trashWorkflows.find((w) => w.id === workflowId);
            setTrashWorkflows((prev) => prev.filter((w) => w.id !== workflowId));
            // A delete within the last 15s tombstoned this id (list responses drop
            // it); restoring must lift that or the grid hides the restored flow.
            clearRemovalTombstone(workflowId);

            sendEventWithCallback(
                WorkflowRestoreRequest.create({ workflow_id: workflowId }),
                (response) => {
                    if (response.error) {
                        console.error('Failed to restore workflow:', response.error);
                        alert(`Failed to restore workflow: ${response.error}`);
                        if (restoredItem) {
                            setTrashWorkflows((prev) => [...prev, restoredItem]);
                        }
                    }
                }
            );
        },
        [trashWorkflows]
    );

    const handlePermanentDeleteConfirm = useCallback(
        (workflowId: string) => {
            setTrashWorkflows((prev) => prev.filter((w) => w.id !== workflowId));
            setShowPermanentDeleteConfirm(null);

            sendEventWithCallback(
                WorkflowPermanentDeleteRequest.create({ workflow_id: workflowId }),
                (response) => {
                    if (response.error) {
                        console.error('Failed to permanently delete workflow:', response.error);
                        alert(`Failed to permanently delete workflow: ${response.error}`);
                        fetchTrashWorkflows();
                    }
                }
            );
        },
        [fetchTrashWorkflows]
    );

    return (
        <>
            <div className="mx-auto min-h-full w-full max-w-[1240px] px-4 pb-24 pt-3 sm:px-8 sm:pt-10">
                {onBack && <PhoneBarBack label="Automations" onBack={onBack} />}
                <header className="mb-6 flex items-start gap-2 sm:mb-7">
                    {isMobile && onOpenMobileSidebar && (
                        <Button
                            size="sm"
                            variant="ghost"
                            className="h-8 w-8 p-0 hover:bg-accent flex-shrink-0"
                            onClick={onOpenMobileSidebar}
                            title="Browse folders"
                        >
                            <PanelLeft className="w-4 h-4 text-muted-foreground" />
                        </Button>
                    )}
                    <div className="min-w-0">
                        {onBack && !inPhone && (
                            <nav aria-label="Breadcrumb" className="-ml-1 mb-1 flex items-center gap-1 text-[13px] text-muted-foreground">
                                <button type="button" onClick={onBack} className="rounded-md px-1 py-0.5 transition-colors hover:text-foreground">
                                    Automations
                                </button>
                                <ChevronRight className="h-3.5 w-3.5 opacity-60" />
                            </nav>
                        )}
                        {!(inPhone && !onBack) && (
                            <h1 className={PAGE_TITLE}>Trash</h1>
                        )}
                        <p className="mt-1 text-[14px] text-muted-foreground">Deleted automations stay here for 30 days, then they’re gone for good.</p>
                    </div>
                </header>

                {loadingTrash ? (
                    <div className="divide-y divide-border overflow-hidden rounded-2xl border border-border dark:divide-foreground/[0.06] dark:border-foreground/[0.08]">
                        {Array.from({ length: 3 }).map((_, index) => (
                            <div key={`skeleton-trash-${index}`} className="flex items-center gap-3 px-4 py-3.5">
                                <div className="flex-1 space-y-1.5">
                                    <Skeleton className={cn('h-3.5', index % 2 ? 'w-1/3' : 'w-1/2')} />
                                    <Skeleton className="h-3 w-1/4" />
                                </div>
                            </div>
                        ))}
                    </div>
                ) : trashWorkflows.length === 0 ? (
                    <div className="flex flex-col items-center px-6 py-20 text-center">
                        <span className="grid h-11 w-11 place-items-center rounded-full bg-foreground/[0.05]">
                            <Trash2 className="h-5 w-5 text-foreground/60" strokeWidth={1.75} />
                        </span>
                        <p className="mt-4 text-[15px] font-semibold text-foreground">Trash is empty</p>
                        <p className="mt-1 max-w-sm text-[14px] leading-relaxed text-muted-foreground">Automations you delete wait here for 30 days in case you want them back.</p>
                    </div>
                ) : (
                    <div className="divide-y divide-border overflow-hidden rounded-2xl border border-border bg-card dark:divide-foreground/[0.06] dark:border-foreground/[0.08] dark:bg-foreground/[0.02]">
                        {trashWorkflows.map((workflow) => (
                            <div key={workflow.id} className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3.5 sm:flex-nowrap">
                                <div className="min-w-0 flex-1">
                                    <p className="truncate text-[14px] font-medium text-foreground">{workflow.name}</p>
                                    <p className="mt-0.5 truncate text-[12.5px] text-muted-foreground">
                                        {workflow.description ? `${workflow.description} · ` : ''}
                                        <span className={cn(workflow.days_remaining <= 3 && 'text-amber-600 dark:text-amber-400')}>
                                            {workflow.days_remaining <= 0
                                                ? 'Gone today'
                                                : `Gone in ${workflow.days_remaining} ${workflow.days_remaining === 1 ? 'day' : 'days'}`}
                                        </span>
                                    </p>
                                </div>
                                <div className="flex shrink-0 items-center gap-1">
                                    <button
                                        type="button"
                                        onClick={() => setShowPermanentDeleteConfirm(workflow.id)}
                                        className="inline-flex h-8 items-center rounded-full px-3 text-[13px] text-muted-foreground transition-colors hover:bg-red-500/10 hover:text-red-600 dark:hover:text-red-400"
                                    >
                                        Delete forever
                                    </button>
                                    <button
                                        type="button"
                                        onClick={() => handleRestoreWorkflow(workflow.id)}
                                        className="inline-flex h-8 items-center gap-1.5 rounded-full bg-secondary px-3.5 text-[13px] font-medium text-foreground transition-colors hover:bg-accent dark:bg-foreground/[0.07] dark:hover:bg-foreground/[0.11]"
                                    >
                                        <RotateCcw className="h-3.5 w-3.5" />
                                        Restore
                                    </button>
                                </div>
                            </div>
                        ))}
                    </div>
                )}
            </div>

            {/* Permanent Delete Confirmation (for trash items) */}
            <DeleteConfirmPopup
                itemId={showPermanentDeleteConfirm}
                itemType="Automation"
                isOpen={!!showPermanentDeleteConfirm}
                onOpenChange={(open) => !open && setShowPermanentDeleteConfirm(null)}
                onConfirmDelete={(workflowId) => {
                    if (workflowId) handlePermanentDeleteConfirm(workflowId);
                }}
                customMessage="This deletes the automation for good. It can’t be undone."
            />
        </>
    );
}
