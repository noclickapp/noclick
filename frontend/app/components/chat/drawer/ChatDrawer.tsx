// Animation wrapper component that handles slide-up/down behavior
// Reads content from context and renders with smooth transitions
// Supports opt-in resizable height via drag handle (when drawer registered with resizable: true)
// Memoized to prevent unnecessary re-renders during FlowCanvas drag operations

import { useRef, useEffect, memo } from 'react';
import { createPortal } from 'react-dom';
import { cn } from '~/lib/utils';
import { useDrawer } from '~/hooks/useDrawer';
import { useResizableDrawer } from '~/hooks/useResizableDrawer';
import { useEmphasizedCutouts } from '~/hooks/useEmphasizedCutouts';
import { BorderBeam } from '~/components/ui/BorderBeam';
import { MENU_SURFACE } from '~/components/shell/menus';
import { EmphasizedBackdrop } from './EmphasizedBackdrop';

const DEFAULT_MAX_HEIGHT = 'calc(50vh - 2rem)';

export const ChatDrawer = memo(function ChatDrawer() {
    const { isOpen, content, visibleDrawer } = useDrawer();
    const drawerRef = useRef<HTMLDivElement>(null);
    // When the drawer is portaled to document.body (emphasized mode), the
    // resizable hook can't read its parent's geometry. We render an invisible
    // anchor where the drawer would naturally sit and feed its rect to the hook.
    const anchorRef = useRef<HTMLDivElement>(null);

    const isClosing = visibleDrawer?.isClosing || false;
    const drawerId = visibleDrawer?.id || null;
    const isResizable = visibleDrawer?.options?.resizable || false;
    const isEmphasized = visibleDrawer?.options?.emphasized || false;

    const { height, isDragging, handleDragStart } = useResizableDrawer({
        drawerId,
        isOpen,
        isResizable,
        drawerRef,
        anchorRef: isEmphasized ? anchorRef : undefined,
    });

    const cutoutRects = useEmphasizedCutouts({
        enabled: isEmphasized && isOpen && !isClosing,
        drawerRef,
        anchorRef,
    });

    // Force reflow when isOpen or isClosing changes to prevent CSS transition conflicts
    useEffect(() => {
        if (drawerRef.current) {
            drawerRef.current.offsetHeight;
        }
    }, [isOpen, isClosing]);

    // A docked drawer is drawn by DockedDrawer, in the flow above the composer.
    if ((!content && !isOpen) || visibleDrawer?.options?.docked) {
        return null;
    }

    const backdrop = isOpen ? (
        isEmphasized ? (
            <EmphasizedBackdrop
                cutoutRects={cutoutRects}
                isDragging={isDragging}
                isResizable={isResizable}
            />
        ) : (
            <div
                className={cn(
                    // Transparent in light so the drawer + sidebar aren't washed
                    // gray (the black scrim showed through the translucent
                    // bg-popover/70 drawer); dark keeps its ~invisible dim.
                    "fixed inset-0 z-40 bg-transparent dark:bg-black/10 transition-colors duration-200",
                    isDragging && isResizable ? "pointer-events-auto cursor-ns-resize" : "pointer-events-none"
                )}
                aria-hidden="true"
            />
        )
    ) : null;

    const drawer = (
        <div
            ref={drawerRef}
            className={cn(
                'flex flex-col',
                isResizable ? 'fixed max-h-[90vh] rounded-t-xl bg-popover/70 backdrop-blur-md dark:bg-zinc-800/70' : cn('absolute bottom-2 left-3 right-3 max-h-full overflow-hidden rounded-2xl', MENU_SURFACE),
                isEmphasized && 'z-[61]',
                (isOpen && !isClosing && content && isResizable) && 'border border-border dark:border-zinc-600/50 shadow-2xl',
                (isOpen && !isClosing) ? 'translate-y-0 opacity-100 pointer-events-auto' : 'translate-y-3 opacity-0 pointer-events-none',
                !(isDragging && isResizable) && 'transition-[transform,opacity] duration-150 ease-out',
                (isDragging && isResizable) && 'select-none'
            )}
            role="dialog"
            aria-modal="true"
            aria-label="Command drawer"
            data-drawer-content
        >
            {/* Handle - decorative for standard, interactive for resizable */}
            {!isClosing && content && (
                isResizable ? (
                    <div
                        onMouseDown={handleDragStart}
                        className={cn(
                            "h-3 cursor-ns-resize flex items-center justify-center shrink-0 group transition-colors rounded-t-xl",
                            isDragging ? "bg-accent dark:bg-zinc-700/50" : "hover:bg-accent/50 dark:hover:bg-zinc-700/30"
                        )}
                    >
                        <div className={cn(
                            "w-10 h-1 rounded-full transition-colors",
                            isDragging ? "bg-muted-foreground" : "bg-border dark:bg-zinc-600/50 group-hover:bg-muted-foreground/70 dark:group-hover:bg-zinc-500"
                        )} />
                    </div>
                ) : null
            )}

            {/* Content */}
            <div
                className="flex flex-col min-h-0 overflow-hidden"
                style={isResizable ? { height } : { maxHeight: DEFAULT_MAX_HEIGHT }}
            >
                {content}
            </div>

            {/* Emphasized glow border — animated beam around the drawer */}
            {isEmphasized && isOpen && !isClosing && (
                <BorderBeam
                    duration={8}
                    borderWidth={1.5}
                    size={420}
                    colorFrom="transparent"
                    colorTo="rgba(255,255,255,0.45)"
                />
            )}
        </div>
    );

    // Emphasized: portal both backdrop and drawer to document.body so they
    // escape the sidebar's z-10 stacking context and dim the entire viewport.
    // The anchor stays in place to feed the resize hook the sidebar geometry.
    if (isEmphasized && typeof document !== 'undefined') {
        return (
            <>
                <div ref={anchorRef} className="absolute inset-0 pointer-events-none" aria-hidden="true" />
                {createPortal(
                    <>
                        {backdrop}
                        {drawer}
                    </>,
                    document.body
                )}
            </>
        );
    }

    return (
        <>
            {backdrop}
            {drawer}
        </>
    );
});

/** The visible drawer when it's docked: in the flow just above the composer, where you'd answer anyway. */
export const DockedDrawer = memo(function DockedDrawer() {
    const { visibleDrawer } = useDrawer();
    if (!visibleDrawer?.options?.docked || visibleDrawer.isClosing) return null;
    return <div className="tl-open px-3 pb-1.5">{visibleDrawer.content}</div>;
});
