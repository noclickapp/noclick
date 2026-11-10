// A long CSS grid drawn as only the rows near the viewport. The grid's own classes decide how many columns fit
// (read back from its computed tracks), and whichever ancestor scrolls the page scrolls it, so a page keeps its
// layout and its one scrollbar. For catalogs of hundreds of tiles: drawing every one cost seconds and a fetch of
// every icon.
import { useCallback, useLayoutEffect, useRef, useState } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';

/** The nearest ancestor that scrolls vertically, else the document's scroller. */
export function scrollParentOf(element: HTMLElement): HTMLElement {
    for (let node = element.parentElement; node; node = node.parentElement) {
        const { overflowY } = getComputedStyle(node);
        if (overflowY === 'auto' || overflowY === 'scroll' || overflowY === 'overlay') return node;
    }
    return (document.scrollingElement as HTMLElement | null) ?? document.documentElement;
}

/** How many columns a grid lays out: its resolved tracks ('none' when it has no explicit ones). */
export function gridColumnCount(element: HTMLElement): number {
    const tracks = getComputedStyle(element).gridTemplateColumns;
    if (!tracks || tracks === 'none') return 1;
    return Math.max(1, tracks.split(' ').filter(Boolean).length);
}

export interface VirtualGridRow {
    key: string | number | bigint;
    index: number;
    /** Offset of the row from the grid's top. */
    top: number;
    /** The items it holds: [from, to). */
    from: number;
    to: number;
}

export function useVirtualGrid({ count, estimateRowHeight, overscan = 3 }: { count: number; estimateRowHeight: number; overscan?: number }) {
    const gridRef = useRef<HTMLDivElement>(null);
    const [scroller, setScroller] = useState<HTMLElement | null>(null);
    const [columns, setColumns] = useState(1);
    const [scrollMargin, setScrollMargin] = useState(0);

    useLayoutEffect(() => {
        const grid = gridRef.current;
        if (!grid) return;
        const scrollElement = scrollParentOf(grid);
        setScroller(scrollElement);
        const measure = () => {
            setColumns(gridColumnCount(grid));
            const offset = grid.getBoundingClientRect().top - scrollElement.getBoundingClientRect().top + scrollElement.scrollTop;
            setScrollMargin(Math.max(0, Math.round(offset)));
        };
        measure();
        const observer = new ResizeObserver(measure);
        observer.observe(grid);
        observer.observe(scrollElement);
        return () => observer.disconnect();
    }, []);

    const rowCount = Math.ceil(count / columns);
    const virtualizer = useVirtualizer({
        count: rowCount,
        getScrollElement: () => scroller,
        estimateSize: () => estimateRowHeight,
        overscan,
        scrollMargin,
    });

    const rows: VirtualGridRow[] = virtualizer.getVirtualItems().map((row) => ({
        key: row.key,
        index: row.index,
        top: row.start - scrollMargin,
        from: row.index * columns,
        to: Math.min(count, (row.index + 1) * columns),
    }));
    const measureRow = useCallback((element: HTMLElement | null) => virtualizer.measureElement(element), [virtualizer]);

    return { gridRef, rows, height: virtualizer.getTotalSize(), measureRow };
}
