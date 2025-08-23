import React, { useState, useRef, useCallback, useMemo } from 'react';

export type ResizeHandle = 'n' | 's' | 'e' | 'w' | 'ne' | 'nw' | 'se' | 'sw';

interface ResizeHandleConfig {
    handle: ResizeHandle;
    className: string;
    cursor: string;
}

interface UseResizableOptions {
    initialSize?: { width: number; height: number };
    minWidth?: number;
    minHeight?: number;
}

export function useResizable(options: UseResizableOptions = {}) {
    const {
        initialSize = { width: 375, height: 667 },
        minWidth = 320,
        minHeight = 568,
    } = options;

    const [size, setSize] = useState(initialSize);
    const [isResizing, setIsResizing] = useState(false);
    const resizeStartData = useRef<{
        handle: string;
        x: number;
        y: number;
        width: number;
        height: number;
    } | null>(null);

    // Resize handle configurations
    const resizeHandles: ResizeHandleConfig[] = useMemo(() => [
        { handle: 'n', className: 'absolute -top-3 left-0 right-0 h-6', cursor: 'ns-resize' },
        { handle: 's', className: 'absolute -bottom-3 left-0 right-0 h-6', cursor: 'ns-resize' },
        { handle: 'w', className: 'absolute -left-3 top-0 bottom-0 w-6', cursor: 'ew-resize' },
        { handle: 'e', className: 'absolute -right-3 top-0 bottom-0 w-6', cursor: 'ew-resize' },
        { handle: 'nw', className: 'absolute -top-3 -left-3 h-6 w-6', cursor: 'nwse-resize' },
        { handle: 'ne', className: 'absolute -top-3 -right-3 h-6 w-6', cursor: 'nesw-resize' },
        { handle: 'sw', className: 'absolute -bottom-3 -left-3 h-6 w-6', cursor: 'nesw-resize' },
        { handle: 'se', className: 'absolute -bottom-3 -right-3 h-6 w-6', cursor: 'nwse-resize' },
    ], []);

    const startResizing = useCallback((e: React.MouseEvent, handle: ResizeHandle) => {
        e.preventDefault();
        e.stopPropagation();
        resizeStartData.current = {
            handle,
            x: e.clientX,
            y: e.clientY,
            width: size.width,
            height: size.height,
        };
        setIsResizing(true);
    }, [size.width, size.height]);

    const handleResizeMouseMove = useCallback((e: React.MouseEvent) => {
        if (!resizeStartData.current) return;

        const { handle, x, y, width, height } = resizeStartData.current;
        const dx = e.clientX - x;
        const dy = e.clientY - y;

        let newWidth = width;
        let newHeight = height;

        // Horizontal resizing
        if (['e', 'ne', 'se'].includes(handle)) {
            newWidth = width + dx * 2;
        } else if (['w', 'nw', 'sw'].includes(handle)) {
            newWidth = width - dx * 2;
        }

        // Vertical resizing
        if (['s', 'se', 'sw'].includes(handle)) {
            newHeight = height + dy * 2;
        } else if (['n', 'ne', 'nw'].includes(handle)) {
            newHeight = height - dy * 2;
        }

        setSize({
            width: Math.round(Math.max(minWidth, newWidth)),
            height: Math.round(Math.max(minHeight, newHeight)),
        });
    }, [minWidth, minHeight]);

    const stopResizing = useCallback(() => {
        setIsResizing(false);
        resizeStartData.current = null;
    }, []);

    const getResizeCursor = useCallback(() => {
        if (!resizeStartData.current) return 'auto';
        const { handle } = resizeStartData.current;
        const handleConfig = resizeHandles.find(h => h.handle === handle);
        return handleConfig?.cursor || 'auto';
    }, [resizeHandles]);

    const renderResizeHandles = useCallback(() => (
        <>
            {resizeHandles.map(({ handle, className, cursor }) => {
                // Map cursor values to explicit Tailwind classes
                const cursorClass = cursor === 'ns-resize' ? 'cursor-ns-resize' :
                                   cursor === 'ew-resize' ? 'cursor-ew-resize' :
                                   cursor === 'nwse-resize' ? 'cursor-nwse-resize' :
                                   cursor === 'nesw-resize' ? 'cursor-nesw-resize' : '';
                
                return (
                    <div
                        key={handle}
                        role="button"
                        tabIndex={0}
                        onMouseDown={(e) => startResizing(e, handle)}
                        onKeyDown={(e) => {
                            if (e.key === 'Enter' || e.key === ' ') {
                                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                                startResizing(e as any, handle);
                            }
                        }}
                        className={`${className} ${cursorClass} z-20`}
                        aria-label={`Resize ${handle}`}
                    />
                );
            })}
        </>
    ), [startResizing, resizeHandles]);

    const renderResizeOverlay = useCallback(() => {
        if (!isResizing) return null;
        
        return (
            <div
                role="button"
                tabIndex={-1}
                className="fixed inset-0 z-50"
                style={{ cursor: getResizeCursor() }}
                onMouseMove={handleResizeMouseMove}
                onMouseUp={stopResizing}
                aria-label="Resize overlay"
            />
        );
    }, [isResizing, getResizeCursor, handleResizeMouseMove, stopResizing]);

    return {
        size,
        setSize,
        isResizing,
        startResizing,
        stopResizing,
        renderResizeHandles,
        renderResizeOverlay,
    };
} 