import type { MutableRefObject } from 'react';
import { Card } from '~/components/ui/card';
import { Folder, Workflow } from 'lucide-react';
import { DragOverlay } from '@dnd-kit/core';
import { CarbonGradient } from '~/components/shared/CarbonGradient';
import { WorkflowGraphPreview } from '~/components/workflow/WorkflowGraphPreview';
import { getNodeIconData } from '~/lib/nodeIconRegistry';
import type {
    WorkflowApp,
    FolderInfoLocal,
} from '~/hooks/useWorkflowBrowserData';

type FolderInfo = FolderInfoLocal;

interface WorkflowBrowserDragOverlayProps {
    activeWorkflow: WorkflowApp | null;
    activeFolder: FolderInfo | null;
    dragSource: 'grid' | 'sidebar' | 'list' | null;
    dragPreviewDimensionsRef: MutableRefObject<{
        width: number;
        height: number;
    }>;
    draggedWorkflowIdsRef: MutableRefObject<string[]>;
    draggedFolderIdsRef: MutableRefObject<string[]>;
}

export function WorkflowBrowserDragOverlay({
    activeWorkflow,
    activeFolder,
    dragSource,
    dragPreviewDimensionsRef,
    draggedWorkflowIdsRef,
    draggedFolderIdsRef,
}: WorkflowBrowserDragOverlayProps) {
    return (
        <DragOverlay dropAnimation={null}>
            {activeWorkflow && dragSource === 'grid' ? (
                <div
                    className="relative"
                    style={{
                        width: dragPreviewDimensionsRef.current.width,
                        height: dragPreviewDimensionsRef.current.height,
                    }}
                >
                    {draggedWorkflowIdsRef.current.length > 2 && (
                        <div
                            className="absolute bg-secondary border border-border dark:border-zinc-700 rounded-lg opacity-50"
                            style={{
                                width: dragPreviewDimensionsRef.current.width,
                                height: dragPreviewDimensionsRef.current.height,
                                top: 8,
                                left: 8,
                                transform: 'rotate(6deg)',
                            }}
                        />
                    )}
                    {draggedWorkflowIdsRef.current.length > 1 && (
                        <div
                            className="absolute bg-secondary border border-border dark:border-zinc-700 rounded-lg opacity-70"
                            style={{
                                width: dragPreviewDimensionsRef.current.width,
                                height: dragPreviewDimensionsRef.current.height,
                                top: 4,
                                left: 4,
                                transform: 'rotate(3deg)',
                            }}
                        />
                    )}
                    <Card
                        className="relative z-10 bg-card/50 backdrop-blur-sm border-border/50 dark:border-zinc-800/50 overflow-hidden shadow-2xl cursor-grabbing h-[280px]"
                        style={{
                            width: dragPreviewDimensionsRef.current.width,
                        }}
                    >
                        <div className="h-[180px] relative overflow-hidden">
                            {activeWorkflow.graph_preview ? (
                                <WorkflowGraphPreview
                                    graph={activeWorkflow.graph_preview}
                                    nodeIcons={getNodeIconData()}
                                    className="w-full h-full"
                                />
                            ) : (
                                <CarbonGradient
                                    identifier={
                                        activeWorkflow.id || activeWorkflow.name
                                    }
                                    width={Math.floor(
                                        dragPreviewDimensionsRef.current.width
                                    )}
                                    height={180}
                                    className="w-full h-full object-cover"
                                />
                            )}
                            <div className="absolute bottom-2 left-2 z-10">
                                <div className="flex items-center gap-1.5 px-2 py-1 rounded-full bg-card/80 border border-border dark:bg-black/60 dark:border-0 backdrop-blur-sm">
                                    <Workflow className="w-3.5 h-3.5 text-orange-600 dark:text-orange-400" />
                                    <span className="text-[10px] text-foreground/80">
                                        Workflow
                                    </span>
                                </div>
                            </div>
                        </div>
                        <div className="h-[100px] p-4">
                            <div className="space-y-1">
                                <h3 className="text-sm font-medium text-foreground line-clamp-1 break-all">
                                    {activeWorkflow.name}
                                </h3>
                                <p className="text-xs text-muted-foreground line-clamp-3">
                                    {activeWorkflow.description}
                                </p>
                            </div>
                        </div>
                    </Card>
                    {draggedWorkflowIdsRef.current.length > 1 && (
                        <div className="absolute -top-2 -right-2 bg-blue-600 text-white text-xs font-bold rounded-full w-6 h-6 flex items-center justify-center shadow-lg z-20">
                            {draggedWorkflowIdsRef.current.length}
                        </div>
                    )}
                </div>
            ) : activeWorkflow &&
              (dragSource === 'sidebar' || dragSource === 'list') ? (
                <div className="relative">
                    <div
                        className={
                            dragSource === 'list'
                                ? 'flex items-center gap-3 px-4 py-3 min-w-[280px] rounded-xl bg-card border border-border dark:border-white/[0.12] shadow-2xl dark:shadow-black/50 cursor-grabbing'
                                : 'flex items-center gap-2 px-3 py-2 bg-secondary border border-border dark:border-zinc-700 rounded-md shadow-xl cursor-grabbing'
                        }
                    >
                        <Workflow className="w-4 h-4 text-orange-600 dark:text-orange-400 flex-shrink-0" />
                        <span
                            className={
                                dragSource === 'list'
                                    ? 'text-sm font-medium text-foreground truncate max-w-[240px]'
                                    : 'text-sm text-foreground font-medium truncate max-w-[200px]'
                            }
                        >
                            {draggedWorkflowIdsRef.current.length > 1
                                ? `${draggedWorkflowIdsRef.current.length} workflows`
                                : activeWorkflow.name}
                        </span>
                    </div>
                    {draggedWorkflowIdsRef.current.length > 1 && (
                        <div className="absolute -top-2 -right-2 bg-blue-600 text-white text-xs font-bold rounded-full w-5 h-5 flex items-center justify-center shadow-lg">
                            {draggedWorkflowIdsRef.current.length}
                        </div>
                    )}
                </div>
            ) : activeFolder && dragSource === 'grid' ? (
                <div
                    className="relative"
                    style={{
                        width: dragPreviewDimensionsRef.current.width,
                        height: dragPreviewDimensionsRef.current.height,
                    }}
                >
                    {draggedFolderIdsRef.current.length > 2 && (
                        <div
                            className="absolute bg-secondary border border-border dark:border-zinc-700 rounded-lg opacity-50"
                            style={{
                                width: dragPreviewDimensionsRef.current.width,
                                height: dragPreviewDimensionsRef.current.height,
                                top: 8,
                                left: 8,
                                transform: 'rotate(6deg)',
                            }}
                        />
                    )}
                    {draggedFolderIdsRef.current.length > 1 && (
                        <div
                            className="absolute bg-secondary border border-border dark:border-zinc-700 rounded-lg opacity-70"
                            style={{
                                width: dragPreviewDimensionsRef.current.width,
                                height: dragPreviewDimensionsRef.current.height,
                                top: 4,
                                left: 4,
                                transform: 'rotate(3deg)',
                            }}
                        />
                    )}
                    <Card
                        className="relative z-10 bg-card/50 backdrop-blur-sm border-border/50 dark:border-zinc-800/50 overflow-hidden shadow-2xl cursor-grabbing h-[280px]"
                        style={{
                            width: dragPreviewDimensionsRef.current.width,
                        }}
                    >
                        <div className="h-[180px] relative overflow-hidden bg-gradient-to-br from-yellow-900/20 to-card/50">
                            <div className="absolute inset-0 flex items-center justify-center">
                                <Folder className="w-24 h-24 text-yellow-600/40" />
                            </div>
                            <div className="absolute bottom-2 left-2 z-10">
                                <div className="flex items-center gap-1.5 px-2 py-1 rounded-full bg-card/80 border border-border dark:bg-black/60 dark:border-0 backdrop-blur-sm">
                                    <Folder className="w-3.5 h-3.5 text-yellow-600/80" />
                                    <span className="text-[10px] text-foreground/80">
                                        Folder
                                    </span>
                                </div>
                            </div>
                        </div>
                        <div className="h-[100px] p-4">
                            <div className="space-y-1">
                                <h3 className="text-sm font-medium text-foreground line-clamp-1 break-all">
                                    {activeFolder.name}
                                </h3>
                            </div>
                        </div>
                    </Card>
                    {draggedFolderIdsRef.current.length > 1 && (
                        <div className="absolute -top-2 -right-2 bg-blue-600 text-white text-xs font-bold rounded-full w-6 h-6 flex items-center justify-center shadow-lg z-20">
                            {draggedFolderIdsRef.current.length}
                        </div>
                    )}
                </div>
            ) : activeFolder &&
              (dragSource === 'sidebar' || dragSource === 'list') ? (
                <div className="relative">
                    <div
                        className={
                            dragSource === 'list'
                                ? 'flex items-center gap-3 px-4 py-3 min-w-[280px] rounded-xl bg-card border border-border dark:border-white/[0.12] shadow-2xl dark:shadow-black/50 cursor-grabbing'
                                : 'flex items-center gap-2 px-3 py-2 bg-secondary border border-border dark:border-zinc-700 rounded-md shadow-xl cursor-grabbing'
                        }
                    >
                        <Folder className="w-4 h-4 text-yellow-600 flex-shrink-0" />
                        <span
                            className={
                                dragSource === 'list'
                                    ? 'text-sm font-medium text-foreground truncate max-w-[240px]'
                                    : 'text-sm text-foreground font-medium truncate max-w-[200px]'
                            }
                        >
                            {draggedFolderIdsRef.current.length > 1
                                ? `${draggedFolderIdsRef.current.length} folders`
                                : activeFolder.name}
                        </span>
                    </div>
                    {draggedFolderIdsRef.current.length > 1 && (
                        <div className="absolute -top-2 -right-2 bg-blue-600 text-white text-xs font-bold rounded-full w-5 h-5 flex items-center justify-center shadow-lg">
                            {draggedFolderIdsRef.current.length}
                        </div>
                    )}
                </div>
            ) : null}
        </DragOverlay>
    );
}
