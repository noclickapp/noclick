// Hook for making drawers resizable via drag handle
// Handles height persistence, drag events, and fixed positioning for tall drawers

import { useRef, useEffect, useLayoutEffect, useState, useCallback } from 'react';
import { getPositioningAncestors } from '~/lib/domGeometry';

const MIN_HEIGHT = 200;
const MAX_HEIGHT = 1500;
const DEFAULT_HEIGHT = 400;
const STORAGE_KEY_PREFIX = 'drawer-height-';

interface UseResizableDrawerOptions {
    drawerId: string | null;
    isOpen: boolean;
    isResizable: boolean;
    drawerRef: React.RefObject<HTMLDivElement | null>;
    /** Optional anchor element to compute positioning from. Defaults to drawer.parentElement. Used when the drawer is portaled out of its natural parent. */
    anchorRef?: React.RefObject<HTMLDivElement | null>;
}

export function useResizableDrawer({ drawerId, isOpen, isResizable, drawerRef, anchorRef }: UseResizableDrawerOptions) {
    const [height, setHeight] = useState(DEFAULT_HEIGHT);
    const [isDragging, setIsDragging] = useState(false);
    const dragStartY = useRef(0);
    const dragStartHeight = useRef(0);
    const currentHeightRef = useRef(DEFAULT_HEIGHT);

    // Sync ref with state for mouseup handler (avoids stale closure)
    useEffect(() => {
        currentHeightRef.current = height;
    }, [height]);

    // Load persisted height from localStorage
    useEffect(() => {
        if (!drawerId || !isResizable || typeof window === 'undefined') return;

        const saved = localStorage.getItem(STORAGE_KEY_PREFIX + drawerId);
        if (saved) {
            const parsed = parseInt(saved, 10);
            if (!isNaN(parsed)) {
                setHeight(Math.min(Math.max(parsed, MIN_HEIGHT), MAX_HEIGHT));
                return;
            }
        }
        setHeight(DEFAULT_HEIGHT);
    }, [drawerId, isResizable]);

    // Fixed positioning - directly manipulate DOM for snappy response
    useLayoutEffect(() => {
        if (!isResizable || !isOpen || !drawerRef.current) return;

        const drawer = drawerRef.current;
        const anchor = anchorRef?.current ?? drawer.parentElement;
        if (!anchor) return;

        const updatePosition = () => {
            const rect = anchor.getBoundingClientRect();
            drawer.style.left = `${rect.left + 24}px`;
            drawer.style.width = `${rect.width - 48}px`;
            drawer.style.bottom = `${window.innerHeight - rect.bottom}px`;
        };

        updatePosition();

        // The anchor's own size is fixed, but content mounting below it (credit
        // banner, invite/publish banners) grows an ancestor and shifts the
        // anchor's viewport position. ResizeObserver fires on size, not position,
        // so observe the offsetParent chain — those are the elements that resize.
        const resizeObserver = new ResizeObserver(updatePosition);
        getPositioningAncestors(anchor).forEach((el) => resizeObserver.observe(el));
        window.addEventListener('resize', updatePosition);

        return () => {
            resizeObserver.disconnect();
            window.removeEventListener('resize', updatePosition);
            drawer.style.left = '';
            drawer.style.width = '';
            drawer.style.bottom = '';
        };
    }, [isResizable, isOpen, drawerRef, anchorRef]);

    // Drag event handlers
    const handleDragStart = useCallback((e: React.MouseEvent) => {
        if (!isResizable) return;
        e.preventDefault();
        e.stopPropagation();
        setIsDragging(true);
        dragStartY.current = e.clientY;
        dragStartHeight.current = height;
    }, [height, isResizable]);

    useEffect(() => {
        if (!isDragging || !isResizable) return;

        const handleMouseMove = (e: MouseEvent) => {
            const deltaY = dragStartY.current - e.clientY;
            const newHeight = Math.min(Math.max(dragStartHeight.current + deltaY, MIN_HEIGHT), MAX_HEIGHT);
            setHeight(newHeight);
        };

        const handleMouseUp = () => {
            setIsDragging(false);
            if (drawerId) {
                localStorage.setItem(STORAGE_KEY_PREFIX + drawerId, currentHeightRef.current.toString());
            }
        };

        document.addEventListener('mousemove', handleMouseMove);
        document.addEventListener('mouseup', handleMouseUp);

        return () => {
            document.removeEventListener('mousemove', handleMouseMove);
            document.removeEventListener('mouseup', handleMouseUp);
        };
    }, [isDragging, drawerId, isResizable]);

    return {
        height,
        isDragging,
        handleDragStart,
    };
}
