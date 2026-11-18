// The console's one list of like objects (each resource kind, keys, users, runs,
// Home's agents): no lines. Rows stand apart by their height, aligned columns
// and type (what the row is at body size in ink, the other facts muted, a status
// as a dot and a word), with a soft rounded fill on hover and on the open row;
// the column heads are small muted labels with nothing under them, and a row
// `⋯` menu ends each row. One renderer, a look from `ListStyleContext`: A (bare
// rows, the default), B (the rows on one faint panel), C (faint alternate rows).
// The developers lab switches it with `?listStyle=`; nothing else does.
// Per-column priority hides columns on narrower screens (2 below md, 3 below
// lg), so a phone shows what the row is, one fact and its status, and never
// scrolls sideways. The row runs a little past the text on both sides, so its
// fill frames the text. Cursor "Load more", skeletons on the same grid; a
// failure with rows showing stays above them (or in the Load more footer). The
// wrapper clips rather than hides overflow: `overflow-hidden` would make it the
// sticky header's scroll container, and it never scrolls.
import { createContext, useContext, type ReactNode } from 'react';
import { clickableRow } from '@/ui/primitives';
import { cn } from '@/ui/utils';
import { ConsoleButton } from './Button';
import { ErrorPanel } from './ErrorPanel';
import { MoreMenu, copyId, type MenuItem } from './MoreMenu';

export type ColumnPriority = 1 | 2 | 3;

export interface Column<T> {
    id: string;
    header: ReactNode;
    cell: (row: T) => ReactNode;
    priority?: ColumnPriority;
    align?: 'left' | 'right';
    /** A CSS width for the column (`8rem`, `20%`); others share what's left. */
    width?: string;
    className?: string;
}

export const PRIORITY_CLASS: Record<ColumnPriority, string> = {
    1: '',
    2: 'hidden md:table-cell',
    3: 'hidden lg:table-cell',
};

/** How every list in the console looks: A bare rows, B the rows on one faint panel, C faint alternate rows. None draws a line. */
export type ListStyle = 'A' | 'B' | 'C';
export const DEFAULT_LIST_STYLE: ListStyle = 'A';
export const LIST_STYLES: readonly ListStyle[] = ['A', 'B', 'C'];
export const ListStyleContext = createContext<ListStyle>(DEFAULT_LIST_STYLE);

export function parseListStyle(value: string | null | undefined): ListStyle {
    return LIST_STYLES.find((s) => s === value?.toUpperCase()) ?? DEFAULT_LIST_STYLE;
}

const LOOKS: Record<ListStyle, { panel: string; stripe: boolean; stickyHead: boolean }> = {
    A: { panel: '', stripe: false, stickyHead: true },
    B: { panel: 'rounded-2xl bg-foreground/[0.025] p-1.5 dark:bg-foreground/[0.035]', stripe: false, stickyHead: false },
    C: { panel: '', stripe: true, stickyHead: true },
};

/** A row's fill is painted on its cells, so the first and last can round it. */
const ROUNDED = '[&>td:first-child]:rounded-l-lg [&>td:last-child]:rounded-r-lg';
const FILL_HOVER = '[&:hover>td]:bg-foreground/[0.04] dark:[&:hover>td]:bg-foreground/[0.05]';
const FILL_OPEN = '[&>td]:bg-foreground/[0.05] dark:[&>td]:bg-foreground/[0.06]';
const FILL_STRIPE = '[&>td]:bg-foreground/[0.02] dark:[&>td]:bg-foreground/[0.025]';

const STRIP = 'rounded-none border-0 bg-transparent px-3 py-3';

export interface DataTableProps<T> {
    columns: readonly Column<T>[];
    rows: readonly T[];
    getRowId: (row: T) => string;
    /** Accessible name for the table. */
    label: string;
    loading?: boolean;
    /** A failed read: the whole body without rows, a strip above them otherwise. Retry calls `onRetry`. */
    error?: unknown;
    onRetry?: () => void;
    /** A failed "Load more", shown in the footer; Retry calls `onLoadMore`. */
    loadMoreError?: unknown;
    /** Rendered in place of the rows when there are none. */
    empty?: ReactNode;
    onRowClick?: (row: T) => void;
    selectedId?: string | null;
    /** The row's own `⋯` menu (or other control) in the last column. */
    rowActions?: (row: T) => ReactNode;
    /** With no `rowActions`, a `⋯` menu that opens the row and copies its id, named by this noun ("database"). */
    rowMenu?: string;
    nextCursor?: string | null;
    onLoadMore?: () => void;
    loadingMore?: boolean;
    skeletonRows?: number;
    /** Shorter rows, for logs read many at a time. */
    dense?: boolean;
    className?: string;
}

export function DataTable<T>({
    columns,
    rows,
    getRowId,
    label,
    loading = false,
    error,
    onRetry,
    loadMoreError,
    empty,
    onRowClick,
    selectedId,
    rowActions,
    rowMenu,
    nextCursor,
    onLoadMore,
    loadingMore = false,
    skeletonRows = 8,
    dense = false,
    className,
}: DataTableProps<T>) {
    const look = LOOKS[useContext(ListStyleContext)];
    const menuFor =
        rowActions ??
        (rowMenu
            ? (row: T) => {
                  const id = getRowId(row);
                  const items: MenuItem[] = [...(onRowClick ? [{ label: 'Open', onSelect: () => onRowClick(row) }] : []), { label: 'Copy ID', onSelect: () => void copyId(id) }];
                  return <MoreMenu label={`Actions for this ${rowMenu}`} items={items} />;
              }
            : undefined);
    const span = columns.length + (menuFor ? 1 : 0);
    const rowHeight = dense ? 'h-11' : 'h-[54px]';
    const cellClass = (col: Column<T>, i: number) =>
        cn('px-3 align-middle', col.align === 'right' && 'text-right', i > 0 && 'text-foreground/75 dark:text-foreground/65', PRIORITY_CLASS[col.priority ?? 1], col.className);
    const showError = error !== undefined && !rows.length;
    const inlineError = error !== undefined && rows.length > 0 && error !== loadMoreError;
    const footerError = loadMoreError !== undefined && rows.length > 0;
    return (
        <div className={cn('-mx-3 min-w-0 overflow-clip', look.panel, className)}>
            {inlineError && <ErrorPanel error={error} onRetry={onRetry} className={STRIP} />}
            <table aria-label={label} className="w-full table-fixed border-separate border-spacing-0 text-[13px]">
                <thead className={cn(look.stickyHead && 'sticky top-0 z-10 bg-background')}>
                    <tr className="h-9">
                        {columns.map((col, i) => (
                            <th
                                key={col.id}
                                scope="col"
                                style={col.width ? { width: col.width } : undefined}
                                className={cn(cellClass(col, i), 'truncate text-left text-[12px] font-normal text-muted-foreground', col.align === 'right' && 'text-right')}
                            >
                                {col.header}
                            </th>
                        ))}
                        {menuFor && (
                            <th scope="col" className="pr-2" style={{ width: '3rem' }}>
                                <span className="sr-only">Actions</span>
                            </th>
                        )}
                    </tr>
                </thead>
                <tbody>
                    {loading && !rows.length
                        ? Array.from({ length: skeletonRows }, (_, i) => (
                              <tr key={`skeleton-${i}`} data-skeleton className={rowHeight}>
                                  {columns.map((col, c) => (
                                      <td key={col.id} className={cellClass(col, c)}>
                                          <span className={cn('block h-2.5 animate-pulse rounded bg-foreground/[0.07]', col.align === 'right' ? 'ml-auto w-1/2' : 'w-2/3')} />
                                      </td>
                                  ))}
                                  {menuFor && <td />}
                              </tr>
                          ))
                        : null}
                    {showError && (
                        <tr>
                            <td colSpan={span} className="px-3 py-4">
                                <ErrorPanel error={error} onRetry={onRetry} className="border-0 bg-transparent p-0" />
                            </td>
                        </tr>
                    )}
                    {!loading && !showError && !rows.length && (
                        <tr>
                            <td colSpan={span} className="px-3">
                                {empty ?? <p className="m-0 py-8 text-center text-[13px] text-muted-foreground">Nothing here yet.</p>}
                            </td>
                        </tr>
                    )}
                    {rows.map((row, index) => {
                        const id = getRowId(row);
                        const open = selectedId === id;
                        return (
                            <tr
                                key={id}
                                data-row-id={id}
                                aria-selected={open || undefined}
                                className={cn(
                                    'group [&>td]:transition-colors',
                                    rowHeight,
                                    ROUNDED,
                                    look.stripe && index % 2 === 1 && FILL_STRIPE,
                                    onRowClick && cn('cursor-pointer focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring', FILL_HOVER),
                                    open && FILL_OPEN
                                )}
                                {...clickableRow(onRowClick ? () => onRowClick(row) : undefined)}
                            >
                                {columns.map((col, i) => (
                                    <td key={col.id} className={cn(cellClass(col, i), 'truncate', i === 0 && 'text-[14px] text-foreground')}>
                                        {col.cell(row)}
                                    </td>
                                ))}
                                {menuFor && (
                                    <td className="pr-2 text-right" onClick={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()}>
                                        <span className="inline-flex">{menuFor(row)}</span>
                                    </td>
                                )}
                            </tr>
                        );
                    })}
                </tbody>
            </table>
            {footerError && <ErrorPanel error={loadMoreError} onRetry={onLoadMore} className={STRIP} />}
            {nextCursor && onLoadMore && rows.length > 0 && !footerError && (
                <div className="flex justify-center py-3">
                    <ConsoleButton variant="soft" onClick={onLoadMore} disabled={loadingMore}>
                        {loadingMore ? 'Loading…' : 'Load more'}
                    </ConsoleButton>
                </div>
            )}
        </div>
    );
}
