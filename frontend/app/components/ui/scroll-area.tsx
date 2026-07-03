// Radix-backed scroll area with custom overlay scrollbars (native bars are
// hidden). Unlike native scrollbars — which always span the full scroll box —
// these can be offset (e.g. start the track below a sticky table header via
// scrollBarClassName="mt-[41px]") and don't reserve layout space.

import * as React from 'react';
import * as ScrollAreaPrimitive from '@radix-ui/react-scroll-area';

import { cn } from '~/lib/utils';

interface ScrollAreaProps
    extends React.ComponentPropsWithoutRef<typeof ScrollAreaPrimitive.Root> {
    /** Ref to the scrolling viewport element — e.g. an IntersectionObserver root. */
    viewportRef?: React.Ref<HTMLDivElement>;
    /** Classes for the viewport (the element that actually scrolls), e.g. max-h. */
    viewportClassName?: string;
    /** Extra classes for the vertical scrollbar, e.g. a margin-top offset so the
     * track starts below a sticky header. */
    scrollBarClassName?: string;
    /** Also render a horizontal scrollbar. Radix disables horizontal scrolling
     * entirely when no horizontal scrollbar is mounted, so wide content (tables)
     * needs this. */
    horizontal?: boolean;
}

const ScrollArea = React.forwardRef<
    React.ElementRef<typeof ScrollAreaPrimitive.Root>,
    ScrollAreaProps
>(
    (
        {
            className,
            children,
            viewportRef,
            viewportClassName,
            scrollBarClassName,
            horizontal = false,
            ...props
        },
        ref
    ) => (
        <ScrollAreaPrimitive.Root
            ref={ref}
            className={cn('relative overflow-hidden', className)}
            {...props}
        >
            <ScrollAreaPrimitive.Viewport
                ref={viewportRef}
                className={cn(
                    'h-full w-full rounded-[inherit]',
                    viewportClassName
                )}
            >
                {children}
            </ScrollAreaPrimitive.Viewport>
            <ScrollBar className={scrollBarClassName} />
            {horizontal && <ScrollBar orientation="horizontal" />}
            <ScrollAreaPrimitive.Corner />
        </ScrollAreaPrimitive.Root>
    )
);
ScrollArea.displayName = ScrollAreaPrimitive.Root.displayName;

const ScrollBar = React.forwardRef<
    React.ElementRef<typeof ScrollAreaPrimitive.ScrollAreaScrollbar>,
    React.ComponentPropsWithoutRef<
        typeof ScrollAreaPrimitive.ScrollAreaScrollbar
    >
>(({ className, orientation = 'vertical', ...props }, ref) => (
    <ScrollAreaPrimitive.ScrollAreaScrollbar
        ref={ref}
        orientation={orientation}
        className={cn(
            'flex touch-none select-none transition-colors',
            orientation === 'vertical' &&
                'h-full w-2.5 border-l border-l-transparent p-[1px]',
            orientation === 'horizontal' &&
                'h-2.5 flex-col border-t border-t-transparent p-[1px]',
            className
        )}
        {...props}
    >
        <ScrollAreaPrimitive.ScrollAreaThumb className="relative flex-1 rounded-full bg-zinc-700/60 hover:bg-zinc-600/70 transition-colors" />
    </ScrollAreaPrimitive.ScrollAreaScrollbar>
));
ScrollBar.displayName = ScrollAreaPrimitive.ScrollAreaScrollbar.displayName;

export { ScrollArea, ScrollBar };
