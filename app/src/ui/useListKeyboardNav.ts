// Keyboard navigation for a search-results list: ↑/↓ move a highlight, Enter
// selects the highlighted item, Esc runs an escape handler. Shared by the
// workflow browser list search and the sidebar search so both behave identically.
// Owns the highlight index; callers reset it (e.g. on query change) via setIndex
// and do their own scroll-into-view, since DOM layouts differ.
import { useCallback, useState } from 'react';

interface UseListKeyboardNavOptions {
    /** Number of navigable rows. */
    count: number;
    /** When false, arrow/Enter are ignored (Esc still fires). */
    active: boolean;
    onSelect: (index: number) => void;
    onEscape?: () => void;
    /** When true, ↓ past the last row wraps to the first (and ↑ vice versa).
     *  Defaults to false, which clamps at the ends. */
    wrap?: boolean;
}

export function useListKeyboardNav({
    count,
    active,
    onSelect,
    onEscape,
    wrap = false,
}: UseListKeyboardNavOptions) {
    const [index, setIndex] = useState(0);

    const handleKeyDown = useCallback(
        (e: React.KeyboardEvent) => {
            if (e.key === 'Escape') {
                e.preventDefault();
                onEscape?.();
                return;
            }
            if (!active || count === 0) return;
            if (e.key === 'ArrowDown') {
                e.preventDefault();
                setIndex((i) => (wrap ? (i + 1) % count : Math.min(i + 1, count - 1)));
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                setIndex((i) => (wrap ? (i - 1 + count) % count : Math.max(i - 1, 0)));
            } else if (e.key === 'Enter') {
                e.preventDefault();
                onSelect(index);
            }
        },
        [active, count, index, onSelect, onEscape, wrap]
    );

    return { index, setIndex, handleKeyDown };
}
