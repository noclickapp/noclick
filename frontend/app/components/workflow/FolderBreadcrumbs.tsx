// Breadcrumb navigation showing folder path with clickable segments
// Fetches path from backend and allows navigation to parent folders
// Each segment is also a drop zone — drag workflows onto a crumb to move them there

import { ChevronRight, Home } from 'lucide-react';
import { cn } from '~/lib/utils';
import { useDroppableFolder } from '~/hooks/useDroppableFolder';

const DROP_HIGHLIGHT_CLASS = 'bg-gradient-to-r from-foreground/10 via-foreground/15 to-foreground/10';

interface BreadcrumbSegment {
    id: string;
    name: string;
}

interface FolderBreadcrumbsProps {
    folderId: string | null;
    folderPath: BreadcrumbSegment[];
    onNavigate: (folderId: string | null) => void;
    className?: string;
    /** The root crumb's name; without one it reads "All" beside a home icon. */
    rootLabel?: string;
    /** False when the page titles the current folder itself: the trail stops at its parent. */
    includeCurrent?: boolean;
}

// Individual droppable breadcrumb segment
function DroppableCrumb({ folderId, onClick, className, children }: {
    folderId: string | null;
    onClick: () => void;
    className?: string;
    children: React.ReactNode;
}) {
    const { isOver, setNodeRef } = useDroppableFolder({
        folderId,
        idSuffix: `crumb-${folderId ?? 'root'}`,
    });

    return (
        <button
            ref={setNodeRef}
            onClick={onClick}
            className={cn(className, isOver && DROP_HIGHLIGHT_CLASS)}
        >
            {children}
        </button>
    );
}

export function FolderBreadcrumbs({
    folderId,
    folderPath,
    onNavigate,
    className,
    rootLabel,
    includeCurrent = true,
}: FolderBreadcrumbsProps) {
    // Path is derived from the shared folder tree in the parent — no backend fetch needed
    const path = includeCurrent ? folderPath : folderPath.slice(0, -1);
    const root = rootLabel ?? (
        <>
            <Home className="w-4 h-4" />
            <span>All</span>
        </>
    );

    // If no folder selected, show root only
    if (!folderId) {
        return (
            <div className={cn('flex items-center gap-1 text-sm', className)}>
                <button
                    onClick={() => onNavigate(null)}
                    className="flex items-center gap-1.5 px-2 py-1 rounded hover:bg-accent transition-colors text-muted-foreground hover:text-foreground"
                >
                    {rootLabel ?? (
                        <>
                            <Home className="w-4 h-4" />
                            <span>All Workflows</span>
                        </>
                    )}
                </button>
            </div>
        );
    }

    return (
        <div className={cn('flex items-center gap-1 text-sm overflow-x-auto scrollbar-subtle', className)}>
            {/* Root / Home — droppable to move workflows to root */}
            <DroppableCrumb
                folderId={null}
                onClick={() => onNavigate(null)}
                className={cn(
                    'flex items-center gap-1.5 rounded-md transition-colors text-muted-foreground hover:text-foreground flex-shrink-0',
                    rootLabel ? 'px-1 py-0.5 text-[13px]' : 'px-2 py-1 hover:bg-accent'
                )}
            >
                {root}
            </DroppableCrumb>

            {/* Breadcrumb Path — each segment is a droppable target */}
            {path.map((segment, index) => (
                <div key={segment.id} className="flex items-center gap-1 flex-shrink-0">
                    <ChevronRight className={cn('text-muted-foreground/70 dark:text-zinc-600', rootLabel ? 'h-3.5 w-3.5' : 'w-4 h-4')} />
                    <DroppableCrumb
                        folderId={segment.id}
                        onClick={() => onNavigate(segment.id)}
                        className={cn(
                            'rounded transition-colors truncate max-w-[150px]',
                            rootLabel ? 'px-1 py-0.5 text-[13px]' : 'px-2 py-1 hover:bg-accent',
                            includeCurrent && index === path.length - 1
                                ? 'text-foreground font-medium'
                                : 'text-muted-foreground hover:text-foreground'
                        )}
                    >
                        {segment.name}
                    </DroppableCrumb>
                </div>
            ))}
            {/* The page titles the current folder: the trail ends pointing at it. */}
            {!includeCurrent && <ChevronRight className={cn('flex-shrink-0 text-muted-foreground/70 dark:text-zinc-600', rootLabel ? 'h-3.5 w-3.5' : 'w-4 h-4')} />}
        </div>
    );
}
