import { useEffect, useRef } from 'react';
import { Search, X } from 'lucide-react';

interface NodeSearchBarProps {
    searchQuery: string;
    onSearchChange: (event: React.ChangeEvent<HTMLInputElement>) => void;
    /** Clears the input. When provided, an X button renders inside the input
     *  whenever the query is non-empty; clicking it resets the search and
     *  returns focus to the input so the user can keep typing. */
    onClear?: () => void;
    /** In very compact mode, the input collapses to a search icon until clicked. */
    isVeryCompact: boolean;
    isSearchExpanded: boolean;
    onSearchExpandedChange: (expanded: boolean) => void;
    /** Counter — when it changes, the input focuses. Used to autofocus the
     *  search bar whenever FlowHelperView is opened via the canvas + button
     *  or a node's "+" hint, so the user can start typing immediately. */
    focusSignal?: number;
}

export function NodeSearchBar({
    searchQuery,
    onSearchChange,
    onClear,
    isVeryCompact,
    isSearchExpanded,
    onSearchExpandedChange,
    focusSignal,
}: NodeSearchBarProps) {
    const inputRef = useRef<HTMLInputElement>(null);

    // When the parent bumps the focus signal, expand the bar (in very-compact
    // mode) and focus the input. The expansion + focus on the next frame
    // handles the case where the input isn't mounted yet because the bar was
    // collapsed to an icon. preventScroll is required: this fires during the
    // panel's slide-up animation when the input still sits below the fold, so a
    // default focus would scroll an ancestor to reveal it — yanking the navbar
    // off-screen and back.
    useEffect(() => {
        if (focusSignal === undefined || focusSignal === 0) return;
        if (isVeryCompact && !isSearchExpanded) onSearchExpandedChange(true);
        requestAnimationFrame(() => {
            inputRef.current?.focus({ preventScroll: true });
            inputRef.current?.select();
        });
    }, [focusSignal, isVeryCompact, isSearchExpanded, onSearchExpandedChange]);

    // Focus when the bar expands from its collapsed icon (compact mode). Replaces
    // the native `autoFocus` prop, which scroll-reveals the input and could yank
    // the layout — same reason the signal effect uses preventScroll. Only fires on
    // the false→true expand, so it never steals focus on a re-render.
    useEffect(() => {
        if (isSearchExpanded) inputRef.current?.focus({ preventScroll: true });
    }, [isSearchExpanded]);

    if (isVeryCompact && !isSearchExpanded) {
        return (
            <button
                onClick={() => onSearchExpandedChange(true)}
                className="h-10 w-10 rounded-full bg-foreground/[0.02] border border-border dark:border-white/[0.05] text-muted-foreground dark:text-zinc-500 hover:text-foreground/80 hover:border-muted-foreground/40 dark:hover:border-white/[0.15] transition-colors flex items-center justify-center"
                title="Search nodes"
            >
                <Search className="h-4 w-4" />
            </button>
        );
    }

    const showClear = !!onClear && searchQuery.length > 0;

    return (
        <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground dark:text-zinc-500" />
            <input
                ref={inputRef}
                type="text"
                placeholder="Search nodes..."
                value={searchQuery}
                onChange={onSearchChange}
                onBlur={() => {
                    // Collapse search when empty and in very compact mode
                    if (isVeryCompact && !searchQuery.trim()) {
                        onSearchExpandedChange(false);
                    }
                }}
                // Focus is driven by the effects above (preventScroll), not the
                // native `autoFocus`, so expanding the bar never scroll-yanks the
                // layout during the panel's slide-up.
                // pr-10 (vs pr-4) reserves room for the absolutely-positioned
                // clear button so the X never sits on top of typed text.
                className={`w-48 h-10 pl-10 ${showClear ? 'pr-10' : 'pr-4'} text-sm bg-foreground/[0.02] border border-input dark:border-white/[0.05] rounded-full text-foreground/80 placeholder:text-[hsl(var(--placeholder))] focus:outline-none focus:border-muted-foreground/40 dark:focus:border-white/[0.15] transition-colors`}
            />
            {showClear && (
                <button
                    type="button"
                    onMouseDown={(e) => {
                        // Prevent the input's onBlur (collapse-on-empty in compact mode)
                        // from firing before our click handler runs.
                        e.preventDefault();
                    }}
                    onClick={() => {
                        onClear?.();
                        // Keep focus on the input so the user can keep typing.
                        // preventScroll so re-focusing never nudges the layout.
                        inputRef.current?.focus({ preventScroll: true });
                    }}
                    title="Clear search"
                    aria-label="Clear search"
                    className="absolute right-2 top-1/2 -translate-y-1/2 h-6 w-6 rounded-full text-muted-foreground dark:text-zinc-500 hover:text-foreground hover:bg-foreground/[0.1] transition-colors flex items-center justify-center"
                >
                    <X className="h-3.5 w-3.5" />
                </button>
            )}
        </div>
    );
}
