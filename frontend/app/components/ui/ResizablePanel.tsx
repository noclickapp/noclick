// This isn't from shadcn/ui, created it custom for the chat component
// Memoized to prevent unnecessary re-renders during FlowCanvas drag operations
import { useState, useEffect, ReactNode, MouseEvent, memo } from 'react';
import { getDefaultPanelWidth, getMinPanelWidth, getMaxPanelWidth } from '~/lib/constants';

interface ResizablePanelProps {
    isExpanded: boolean;
    /** Skip the width open/close transition (set for keyboard "/" toggles). */
    noAnimation?: boolean;
    minWidth?: number;
    maxWidth?: number;
    defaultWidth?: number;
    children: ReactNode;
    onWidthChange?: (width: number) => void;
    onExpandChange?: (expanded: boolean) => void;
    onDragChange?: (isDragging: boolean) => void;
}

export const ResizablePanel = memo(function ResizablePanel({
    isExpanded,
    noAnimation,
    // Defaults derive from the low-res-aware getters so the resize clamp,
    // mount-time width, and ceiling all shrink together on smaller laptops
    // instead of leaving a 420px floor while the rest of the UI is at 75%.
    minWidth = getMinPanelWidth(),
    maxWidth = getMaxPanelWidth(),
    defaultWidth = getDefaultPanelWidth(),
    children,
    onWidthChange,
    onExpandChange,
    onDragChange,
}: ResizablePanelProps) {
    const [width, setWidth] = useState(defaultWidth);
    const [isDragging, setIsDragging] = useState(false);

    const handleMouseDown = (e: MouseEvent) => {
        e.stopPropagation();
        setIsDragging(true);
    };

    useEffect(() => {
        if (isDragging) {
            const handleGlobalMouseMove = (e: globalThis.MouseEvent) => {
                if (isDragging && isExpanded) {
                    const newWidth = e.clientX;
                    const constrainedWidth = Math.min(
                        Math.max(minWidth, newWidth),
                        maxWidth
                    );
                    setWidth(constrainedWidth);
                    onWidthChange?.(constrainedWidth);
                }
            };

            const handleGlobalMouseUp = () => {
                setIsDragging(false);
            };

            document.addEventListener('mousemove', handleGlobalMouseMove);
            document.addEventListener('mouseup', handleGlobalMouseUp);

            return () => {
                document.removeEventListener(
                    'mousemove',
                    handleGlobalMouseMove
                );
                document.removeEventListener('mouseup', handleGlobalMouseUp);
            };
        }
    }, [isDragging, isExpanded, minWidth, maxWidth, onWidthChange]);

    useEffect(() => {
        onDragChange?.(isDragging);
    }, [isDragging, onDragChange]);

    return (
        <>
            {/* eslint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/no-static-element-interactions */}
            <div
                data-tour-target={!isExpanded ? 'sidebar-collapsed' : 'sidebar-expanded'}
                className={`fixed left-0 top-0 h-screen bg-background border-r border-border z-20
            ${!isExpanded && 'cursor-pointer'}
            ${isDragging ? 'select-none' : ''}`}
                style={{
                    width: isExpanded ? `${width}px` : '50px',
                    transition: isDragging || noAnimation ? 'none' : 'width 300ms ease-in-out',
                    // CSS containment to isolate sidebar from affecting main canvas
                    // layout/paint. When collapsed we drop `paint` so the
                    // "Open chat" hover tooltip can overflow the 50px bar (paint
                    // containment would clip it); `layout` isolation is retained.
                    contain: isExpanded ? 'layout paint' : 'layout',
                }}
                onClick={() => !isExpanded && onExpandChange?.(true)}
            >
                {isExpanded && (
                    // eslint-disable-next-line jsx-a11y/no-static-element-interactions
                    <div
                        className="absolute right-0 top-0 w-1 h-full cursor-ew-resize hover:bg-blue-500/50 z-50"
                        onMouseDown={handleMouseDown}
                    />
                )}
                {children}
            </div>
            {/* Overlay to capture mouse events during dragging - prevents iframe interference */}
            {isDragging && (
                <div
                    className="fixed inset-0 z-50 cursor-ew-resize"
                    style={{ pointerEvents: 'auto' }}
                />
            )}
        </>
    );
});
