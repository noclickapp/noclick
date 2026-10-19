// Records read out of a resource as a table: a database table's page of rows,
// a query's result, an app's slowest routes. Each column is named over its
// type, sorts when the page lets it, and aligns numbers; NULL reads as itself
// and bytes by their size. A column that looks secret shows its values hidden
// until asked, a cell or the whole column at a time: what the page shows, never
// the data. A row opens its record in full.
import { useState, type ReactNode } from 'react';
import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight, Eye, EyeOff, PanelRightOpen } from 'lucide-react';
import { Skeleton } from '~/components/ui/skeleton';
import { cn } from '~/lib/utils';
import { BUTTON_GHOST } from '../buttons';
import { isNumericType, isSecretColumn, shownValue } from './cells';
import { Surface } from './ui';

/** Rows a page of a table shows. */
export const PAGE_ROWS = 50;

/** Under a table whose columns hide values: what hiding does, and doesn't. */
export const SECRET_NOTE =
    'Values in columns that look secret (passwords, tokens, keys, codes) are hidden here: click one to show it. Hiding changes only what this page shows; the data and a CSV download hold every value.';

export interface GridColumn {
    name: string;
    /** Its declared type, under its name. */
    type?: string;
    /** Its values are hidden until asked. */
    secret?: boolean;
    /** Not offered as a sort (a type its engine can't order). */
    unsortable?: boolean;
    /** Its values are numbers, where no type says so (a query's result): aligned as numbers are. */
    numeric?: boolean;
    /** Part of its table's primary key: said under its type. */
    key?: boolean;
}

export type GridRow = Record<string, unknown>;

export interface GridSort {
    column: string;
    dir: 'asc' | 'desc';
}

/** What's shown of the hidden values: whole columns, and single cells by row and column. */
export interface Reveal {
    shown(row: number, column: string): boolean;
    columnShown(column: string): boolean;
    showCell(row: number, column: string): void;
    toggleColumn(column: string): void;
}

/**
 * Columns for records no schema describes (a query's result, an automation's table): `names` in order, else each key
 * as it first appears; numbers aligned where every value is one, secret-looking ones hidden.
 */
export function columnsOf(rows: readonly GridRow[], names: readonly string[] = [...new Set(rows.flatMap((r) => Object.keys(r)))]): GridColumn[] {
    return names.map((name) => {
        const values = rows.map((r) => r[name]).filter((v) => v !== null && v !== undefined);
        return { name, secret: isSecretColumn(name), numeric: values.length > 0 && values.every((v) => typeof v === 'number') };
    });
}

const cellKey = (row: number, column: string) => `${row}\u0000${column}`;

/**
 * Hidden values shown on request. A column shown stays shown while `table` does; a cell shown is forgotten when
 * `page` changes, so the next rows start hidden.
 */
export function useReveal(table: string, page: string): Reveal {
    type State = { table: string; page: string; columns: Set<string>; cells: Set<string> };
    const [state, setState] = useState<State>(() => ({ table, page, columns: new Set(), cells: new Set() }));
    const current = (s: State): State => ({
        table,
        page,
        columns: s.table === table ? s.columns : new Set(),
        cells: s.table === table && s.page === page ? s.cells : new Set(),
    });
    const { columns, cells } = current(state);
    return {
        shown: (row, column) => columns.has(column) || cells.has(cellKey(row, column)),
        columnShown: (column) => columns.has(column),
        showCell: (row, column) =>
            setState((s) => {
                const now = current(s);
                return { ...now, cells: new Set(now.cells).add(cellKey(row, column)) };
            }),
        toggleColumn: (column) =>
            setState((s) => {
                const now = current(s);
                const next = new Set(now.columns);
                if (next.delete(column)) {
                    // Hiding a column hides each of its cells shown on their own too.
                    return { ...now, columns: next, cells: new Set([...now.cells].filter((key) => !key.endsWith(`\u0000${column}`))) };
                }
                return { ...now, columns: next.add(column) };
            }),
    };
}

/** A hidden value: says it's hidden and shows itself when clicked. */
export function HiddenValue({ onShow, className }: { onShow: () => void; className?: string }) {
    return (
        <button
            type="button"
            title="Hidden: click to show"
            onClick={(e) => {
                e.stopPropagation();
                onShow();
            }}
            className={cn(
                '-mx-1.5 inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 font-sans text-[12px] text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                className
            )}
        >
            <EyeOff className="h-3 w-3" />
            hidden
        </button>
    );
}

/** One value in a cell: on one line, NULL and bytes muted. */
export function CellValue({ value, type }: { value: unknown; type?: string }) {
    const shown = shownValue(value, type);
    if (shown.kind === 'null') return <span className="text-[11.5px] tracking-wide text-muted-foreground">NULL</span>;
    if (shown.kind === 'binary') return <span className="text-muted-foreground">{shown.text}</span>;
    return <span className={cn(shown.kind === 'json' && 'text-foreground/80')}>{shown.text}</span>;
}

const ROW_LINE = 'border-b border-border last:border-0 dark:border-foreground/[0.06]';

export function DataGrid({
    label,
    columns,
    rows,
    sort,
    onSort,
    onOpen,
    openRow,
    reveal,
    empty,
    loadingRows = 8,
    footer,
}: {
    label: string;
    columns: readonly GridColumn[];
    /** Undefined while they're read: as many skeleton rows as `loadingRows`. */
    rows: readonly GridRow[] | undefined;
    sort?: GridSort | null;
    /** A header clicked: the page decides what that sort becomes. */
    onSort?: (column: string) => void;
    /** A row clicked, by its index. */
    onOpen?: (row: number) => void;
    /** The row open in full, marked. */
    openRow?: number | null;
    reveal?: Reveal;
    /** What no rows read as. */
    empty: ReactNode;
    loadingRows?: number;
    footer?: ReactNode;
}) {
    const numeric = (c: GridColumn) => c.numeric ?? isNumericType(c.type);
    // The way into a row leads it, where a wide table's scroll never hides it.
    const lead = onOpen ? <th scope="col" className="w-9 pl-2.5 pr-0"><span className="sr-only">Open</span></th> : null;
    return (
        <Surface>
            {/* Relative, so nothing positioned inside (the sr-only header) escapes the scroll and widens the page. */}
            <div className="relative overflow-x-auto scrollbar-subtle">
                <table aria-label={label} className="w-full border-collapse text-left">
                    <thead>
                        <tr className="border-b border-border dark:border-foreground/[0.06]">
                            {lead}
                            {columns.map((c) => {
                                const sorted = sort?.column === c.name ? sort.dir : null;
                                const Arrow = sorted === 'desc' ? ArrowDown : ArrowUp;
                                const name = (
                                    <>
                                        <span className="font-mono text-[12.5px] font-medium text-foreground/85">{c.name}</span>
                                        {sorted ? (
                                            <Arrow className="h-3 w-3 shrink-0 text-foreground" />
                                        ) : (
                                            onSort && !c.unsortable && <ArrowUp className="h-3 w-3 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-60" />
                                        )}
                                    </>
                                );
                                return (
                                    <th
                                        key={c.name}
                                        scope="col"
                                        aria-sort={sorted === 'asc' ? 'ascending' : sorted === 'desc' ? 'descending' : undefined}
                                        className={cn('whitespace-nowrap px-3 py-2 align-bottom font-normal first:pl-4 last:pr-4', numeric(c) && 'text-right')}
                                    >
                                        <span className={cn('flex items-center gap-1', numeric(c) && 'justify-end')}>
                                            {onSort && !c.unsortable ? (
                                                <button type="button" onClick={() => onSort(c.name)} className="group -mx-1 flex items-center gap-1 rounded px-1 transition-colors hover:bg-foreground/[0.05] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                                                    {name}
                                                </button>
                                            ) : (
                                                <span className="flex items-center gap-1">{name}</span>
                                            )}
                                            {c.secret && reveal && (
                                                <button
                                                    type="button"
                                                    aria-label={reveal.columnShown(c.name) ? `Hide ${c.name}` : `Show ${c.name}`}
                                                    title={reveal.columnShown(c.name) ? 'Hide this column again' : 'Hidden: click to show the column'}
                                                    onClick={() => reveal.toggleColumn(c.name)}
                                                    className="rounded p-0.5 text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                                                >
                                                    {reveal.columnShown(c.name) ? <Eye className="h-3 w-3" /> : <EyeOff className="h-3 w-3" />}
                                                </button>
                                            )}
                                        </span>
                                        {(c.type || c.key) && (
                                            <span className="mt-0.5 block font-mono text-[11px] lowercase text-muted-foreground">{[c.type, c.key && 'key'].filter(Boolean).join(' · ')}</span>
                                        )}
                                    </th>
                                );
                            })}
                        </tr>
                    </thead>
                    <tbody className="font-mono text-[12.5px] text-foreground">
                        {rows === undefined ? (
                            Array.from({ length: loadingRows }, (_, i) => (
                                <tr key={i} className={ROW_LINE} aria-busy>
                                    {onOpen && <td />}
                                    {columns.map((c, j) => (
                                        <td key={c.name} className="px-3 py-2.5 first:pl-4 last:pr-4">
                                            <Skeleton className={cn('h-3', (i + j) % 3 === 0 ? 'w-24' : (i + j) % 3 === 1 ? 'w-16' : 'w-20', numeric(c) && 'ml-auto w-10')} />
                                        </td>
                                    ))}
                                </tr>
                            ))
                        ) : rows.length === 0 ? (
                            <tr>
                                <td colSpan={columns.length + (onOpen ? 1 : 0)} className="px-4 py-10 text-center font-sans text-[13.5px] text-muted-foreground">
                                    {empty}
                                </td>
                            </tr>
                        ) : (
                            rows.map((row, i) => (
                                <tr
                                    key={i}
                                    onClick={onOpen ? () => onOpen(i) : undefined}
                                    className={cn(ROW_LINE, onOpen && 'group/row cursor-pointer transition-colors hover:bg-foreground/[0.025]', openRow === i && 'bg-foreground/[0.045] hover:bg-foreground/[0.045]')}
                                >
                                    {onOpen && (
                                        <td className="w-9 pl-2.5 pr-0">
                                            <button
                                                type="button"
                                                aria-label={`Open row ${i + 1}`}
                                                onClick={(e) => {
                                                    e.stopPropagation();
                                                    onOpen(i);
                                                }}
                                                className={cn(
                                                    'flex h-6 w-6 items-center justify-center rounded-md text-muted-foreground/60 transition-colors hover:bg-foreground/[0.06] hover:text-foreground group-hover/row:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                                                    openRow === i && 'text-foreground'
                                                )}
                                            >
                                                <PanelRightOpen className="h-3.5 w-3.5" />
                                            </button>
                                        </td>
                                    )}
                                    {columns.map((c) => (
                                        <td key={c.name} className={cn('px-3 py-2 first:pl-4 last:pr-4', numeric(c) && 'text-right tabular-nums')}>
                                            <span className="block max-w-[22rem] truncate whitespace-nowrap">
                                                {c.secret && reveal && !reveal.shown(i, c.name) && row[c.name] != null ? (
                                                    <HiddenValue onShow={() => reveal.showCell(i, c.name)} />
                                                ) : (
                                                    <CellValue value={row[c.name]} type={c.type} />
                                                )}
                                            </span>
                                        </td>
                                    ))}
                                </tr>
                            ))
                        )}
                    </tbody>
                </table>
            </div>
            {footer}
        </Surface>
    );
}

/** Under a page of rows: which rows they are (of how many, when that's known), and the pages either side. `noun` names what's paged ("Rows", "Items"). */
export function GridPager({
    from,
    shown,
    total,
    onPrevious,
    onNext,
    noun = 'Rows',
}: {
    from: number;
    shown: number;
    total: string | null;
    onPrevious?: () => void;
    onNext?: () => void;
    noun?: string;
}) {
    return (
        <div className="flex flex-wrap items-center gap-3 border-t border-border px-4 py-2 dark:border-foreground/[0.06]">
            <span className="text-[12.5px] tabular-nums text-muted-foreground">
                {shown ? `${noun} ${(from + 1).toLocaleString('en-US')}–${(from + shown).toLocaleString('en-US')}` : `No ${noun.toLowerCase()}`}
                {total !== null && ` of ${total}`}
            </span>
            <span className="ml-auto flex items-center gap-1">
                <button type="button" onClick={onPrevious} disabled={!onPrevious} className={cn(BUTTON_GHOST, 'h-8 px-2.5')}>
                    <ChevronLeft className="h-4 w-4" />
                    Previous
                </button>
                <button type="button" onClick={onNext} disabled={!onNext} className={cn(BUTTON_GHOST, 'h-8 px-2.5')}>
                    Next
                    <ChevronRight className="h-4 w-4" />
                </button>
            </span>
        </div>
    );
}
