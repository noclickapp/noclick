// Generic multi-select hook for grid items.
// Supports Cmd/Ctrl+Click to toggle individual items and Shift+Click for range selection.

import { useState, useCallback, useRef } from 'react';

interface UseGridSelectionOptions {
    items: { id: string }[];
}

export function useGridSelection({ items }: UseGridSelectionOptions) {
    const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
    const lastClickedIdRef = useRef<string | null>(null);

    const handleClick = useCallback((itemId: string, event: React.MouseEvent | { metaKey?: boolean; ctrlKey?: boolean; shiftKey?: boolean }): 'selected' | 'open' => {
        const isMetaKey = event.metaKey || event.ctrlKey;
        const isShiftKey = event.shiftKey;

        if (isMetaKey) {
            setSelectedIds(prev => {
                const next = new Set(prev);
                if (next.has(itemId)) {
                    next.delete(itemId);
                } else {
                    next.add(itemId);
                }
                return next;
            });
            lastClickedIdRef.current = itemId;
            return 'selected';
        }

        if (isShiftKey) {
            if (lastClickedIdRef.current) {
                const ids = items.map(w => w.id);
                const lastIdx = ids.indexOf(lastClickedIdRef.current);
                const currentIdx = ids.indexOf(itemId);
                if (lastIdx !== -1 && currentIdx !== -1) {
                    const start = Math.min(lastIdx, currentIdx);
                    const end = Math.max(lastIdx, currentIdx);
                    const rangeIds = ids.slice(start, end + 1);
                    setSelectedIds(prev => {
                        const next = new Set(prev);
                        rangeIds.forEach(id => next.add(id));
                        return next;
                    });
                }
            } else {
                // No anchor yet — select just this item
                setSelectedIds(new Set([itemId]));
            }
            lastClickedIdRef.current = itemId;
            return 'selected';
        }

        // Plain click: clear selection and signal "open"
        setSelectedIds(new Set());
        lastClickedIdRef.current = itemId;
        return 'open';
    }, [items]);

    const isSelected = useCallback((itemId: string) => selectedIds.has(itemId), [selectedIds]);

    const clearSelection = useCallback(() => {
        setSelectedIds(new Set());
        lastClickedIdRef.current = null;
    }, []);

    const getSelectedArray = useCallback(() => Array.from(selectedIds), [selectedIds]);

    return { selectedIds, handleClick, isSelected, clearSelection, getSelectedArray };
}
