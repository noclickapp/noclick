// TooltipPortal component renders tooltips to document.body to avoid clipping
// Uses React portal and absolute positioning based on trigger element bounds
// Includes hover persistence to allow interaction with tooltip content

import { useEffect, useRef, useState, useCallback } from 'react';
import { createPortal } from 'react-dom';

export interface TooltipPortalProps {
    children: React.ReactNode;
    isVisible: boolean;
    triggerRef: React.RefObject<HTMLElement | null>;
    placement?: 'top' | 'bottom' | 'left' | 'right';
    offset?: number;
    onVisibilityChange?: (visible: boolean) => void;
    delay?: number;  // Delay before hiding tooltip
}

export function TooltipPortal({ 
    children, 
    isVisible,
    triggerRef,
    placement = 'top',
    offset = 8,
    onVisibilityChange,
    delay = 200
}: TooltipPortalProps) {
    const [position, setPosition] = useState({ top: 0, left: 0 });
    const [internalVisible, setInternalVisible] = useState(false);
    const [isHoveringTooltip, setIsHoveringTooltip] = useState(false);
    const tooltipRef = useRef<HTMLDivElement>(null);
    const hideTimeoutRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

    useEffect(() => {
        if (!isVisible || !triggerRef.current) return;

        const updatePosition = () => {
            if (!triggerRef.current || !tooltipRef.current) return;

            const triggerRect = triggerRef.current.getBoundingClientRect();
            const tooltipRect = tooltipRef.current.getBoundingClientRect();
            
            let top = 0;
            let left = 0;

            switch (placement) {
                case 'top':
                    top = triggerRect.top - tooltipRect.height - offset;
                    left = triggerRect.left + (triggerRect.width - tooltipRect.width) / 2;
                    break;
                case 'bottom':
                    top = triggerRect.bottom + offset;
                    left = triggerRect.left + (triggerRect.width - tooltipRect.width) / 2;
                    break;
                case 'left':
                    top = triggerRect.top + (triggerRect.height - tooltipRect.height) / 2;
                    left = triggerRect.left - tooltipRect.width - offset;
                    break;
                case 'right':
                    top = triggerRect.top + (triggerRect.height - tooltipRect.height) / 2;
                    left = triggerRect.right + offset;
                    break;
            }

            // Ensure tooltip stays within viewport
            const viewportWidth = window.innerWidth;
            const viewportHeight = window.innerHeight;

            // Adjust horizontal position
            if (left < 0) {
                left = offset;
            } else if (left + tooltipRect.width > viewportWidth) {
                left = viewportWidth - tooltipRect.width - offset;
            }

            // Adjust vertical position
            if (top < 0) {
                top = offset;
            } else if (top + tooltipRect.height > viewportHeight) {
                top = viewportHeight - tooltipRect.height - offset;
            }

            setPosition({ top, left });
        };

        // Initial position update
        updatePosition();

        // Update on scroll or resize
        const handleUpdate = () => updatePosition();
        window.addEventListener('scroll', handleUpdate, true);
        window.addEventListener('resize', handleUpdate);

        return () => {
            window.removeEventListener('scroll', handleUpdate, true);
            window.removeEventListener('resize', handleUpdate);
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [internalVisible, placement, offset, triggerRef]);

    // Handle visibility changes with delay
    useEffect(() => {
        if (isVisible || isHoveringTooltip) {
            // Show immediately
            if (hideTimeoutRef.current) {
                clearTimeout(hideTimeoutRef.current);
                hideTimeoutRef.current = undefined;
            }
            setInternalVisible(true);
        } else {
            // Hide with delay
            hideTimeoutRef.current = setTimeout(() => {
                setInternalVisible(false);
                onVisibilityChange?.(false);
            }, delay);
        }

        return () => {
            if (hideTimeoutRef.current) {
                clearTimeout(hideTimeoutRef.current);
            }
        };
    }, [isVisible, isHoveringTooltip, delay, onVisibilityChange]);

    const handleTooltipMouseEnter = useCallback(() => {
        setIsHoveringTooltip(true);
    }, []);

    const handleTooltipMouseLeave = useCallback(() => {
        setIsHoveringTooltip(false);
    }, []);

    if (!internalVisible) return null;

    return createPortal(
        <div
            ref={tooltipRef}
            className="fixed z-[9999]"
            style={{
                top: `${position.top}px`,
                left: `${position.left}px`,
                pointerEvents: 'auto'  // Allow interaction with tooltip
            }}
            onMouseEnter={handleTooltipMouseEnter}
            onMouseLeave={handleTooltipMouseLeave}
        >
            {children}
        </div>,
        document.body
    );
}
