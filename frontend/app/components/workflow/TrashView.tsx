import { useCallback, useEffect, useState } from 'react';
import { Card } from '~/components/ui/card';
import { Button } from '~/components/ui/button';
import { PanelLeft, Trash2 } from 'lucide-react';
import { DeleteConfirmPopup } from '~/components/shared/popups/DeleteConfirmPopup';
import { sendEventWithCallback } from '~/lib/socket-sender';
import { clearRemovalTombstone } from '~/lib/workflowBrowserStore';
import {
    WorkflowListTrashRequest,
    WorkflowPermanentDeleteRequest,
    WorkflowRestoreRequest,
    type WorkflowTrashInfo,
} from '~/types/socket-events.generated';
import { WorkflowCardSkeleton } from './WorkflowBrowserCards';

interface TrashViewProps {
    isMobile: boolean;
    onOpenMobileSidebar: () => void;
}

export function TrashView({ isMobile, onOpenMobileSidebar }: TrashViewProps) {
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
            <div className="p-4 pt-1 space-y-1 min-h-full">
                <div className="flex items-center justify-between px-3 py-2.5">
                    <div className="flex items-center gap-2">
                        {isMobile && (
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
                        <Trash2 className="w-4 h-4 text-muted-foreground" />
                        <span className="text-sm font-medium text-foreground/80">Trash</span>
                    </div>
                </div>
                <p className="px-3 text-xs text-muted-foreground dark:text-zinc-500 pb-2">
                    Items in trash are automatically deleted after 30 days.
                </p>

                {loadingTrash ? (
                    <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-4 gap-3">
                        {Array.from({ length: 3 }).map((_, index) => (
                            <WorkflowCardSkeleton key={`skeleton-trash-${index}`} />
                        ))}
                    </div>
                ) : trashWorkflows.length === 0 ? (
                    <div className="flex flex-col items-center justify-center py-20 text-muted-foreground dark:text-zinc-500">
                        <Trash2 className="w-10 h-10 mb-3 text-muted-foreground/70 dark:text-zinc-600" />
                        <p className="text-sm">Trash is empty</p>
                    </div>
                ) : (
                    <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-4 gap-3">
                        {trashWorkflows.map((workflow) => (
                            <Card
                                key={workflow.id}
                                className="border border-border bg-sunken flex flex-col"
                            >
                                <div className="p-4 flex flex-col gap-3">
                                    <h3 className="text-sm font-medium text-foreground truncate">{workflow.name}</h3>
                                    {workflow.description && (
                                        <p className="text-xs text-muted-foreground dark:text-zinc-500 line-clamp-2">{workflow.description}</p>
                                    )}
                                    <div className="space-y-0.5">
                                        <p className="text-xs text-muted-foreground/70 dark:text-zinc-600 whitespace-nowrap">
                                            Deleted {Math.max(0, 30 - workflow.days_remaining)} days ago
                                        </p>
                                        <p className="text-xs text-amber-600/80 whitespace-nowrap">
                                            {workflow.days_remaining} days remaining
                                        </p>
                                    </div>
                                </div>
                                <div className="border-t border-border px-4 py-3 flex flex-wrap gap-2">
                                    <Button
                                        size="sm"
                                        variant="outline"
                                        onClick={() => handleRestoreWorkflow(workflow.id)}
                                        className="flex-1 min-w-[80px] text-xs h-8 bg-transparent border-emerald-300 dark:border-emerald-800/50 text-emerald-600 dark:text-emerald-400 hover:bg-emerald-50 dark:hover:bg-emerald-950 hover:text-emerald-700 dark:hover:text-emerald-300 rounded-full"
                                    >
                                        Restore
                                    </Button>
                                    <Button
                                        size="sm"
                                        variant="outline"
                                        onClick={() => setShowPermanentDeleteConfirm(workflow.id)}
                                        className="flex-1 min-w-[110px] text-xs h-8 bg-transparent border-red-300 dark:border-red-800/50 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950 hover:text-red-700 dark:hover:text-red-300 rounded-full"
                                    >
                                        Delete Forever
                                    </Button>
                                </div>
                            </Card>
                        ))}
                    </div>
                )}
            </div>

            {/* Permanent Delete Confirmation (for trash items) */}
            <DeleteConfirmPopup
                itemId={showPermanentDeleteConfirm}
                itemType="Workflow"
                isOpen={!!showPermanentDeleteConfirm}
                onOpenChange={(open) => !open && setShowPermanentDeleteConfirm(null)}
                onConfirmDelete={(workflowId) => {
                    if (workflowId) handlePermanentDeleteConfirm(workflowId);
                }}
                customMessage="This will permanently delete this workflow. This action cannot be undone."
            />
        </>
    );
}
