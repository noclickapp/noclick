// Every search box's clear: a muted ✕ on a round wash, so the boxes match the rest of the app. It replaces the
// browser's own ✕ (WebKit's blue cancel button on `type="search"`), which tailwind.css hides everywhere.
import type { RefObject } from 'react';
import { X } from 'lucide-react';
import { cn } from '~/lib/utils';

/** Shown only while the box holds text; clearing hands focus back to the box, so typing carries on. */
export function SearchClearButton({
    value,
    onClear,
    inputRef,
    className,
}: {
    value: string;
    onClear: () => void;
    inputRef: RefObject<HTMLInputElement | null>;
    className?: string;
}) {
    if (!value) return null;
    return (
        <button
            type="button"
            aria-label="Clear search"
            // The box keeps focus through the press.
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => {
                onClear();
                inputRef.current?.focus();
            }}
            className={cn(
                'grid h-7 w-7 shrink-0 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                className
            )}
        >
            <X aria-hidden className="h-3.5 w-3.5" strokeWidth={2} />
        </button>
    );
}
