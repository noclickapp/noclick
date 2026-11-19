// A database's page body: its tables, each opening its rows (`?table=`), and a
// read-only query box (`?view=query`). A table's rows come a page at a time in
// a stable order (its primary key, else the row's own address), sort by a
// column and filter by one, open one at a time in full, and save as CSV, every
// page of what's shown. Every read is the platform's read-only query, cached
// like the rest of Resources and read again on Refresh or when the tab comes
// back. Values in columns that look secret stay hidden until asked; hiding is
// only what the page shows.
import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import { useSearchParams } from 'react-router';
import { toast } from 'sonner';
import { ChevronRight, Download, Loader2, RefreshCw, SquareTerminal, X } from 'lucide-react';
import { countOf } from '@/ui/primitives';
import { BUTTON_GHOST, BUTTON_PRIMARY, BUTTON_SECONDARY } from '@/ui/buttons';
import { FIELD } from '@/ui/fields';
import { isSecretColumn } from './cells';
import { DataGrid, GridPager, PAGE_ROWS, SECRET_NOTE, columnsOf, useReveal, type GridColumn, type GridRow, type GridSort } from './DataGrid';
import { RecordDrawer, type RecordField } from './RecordDrawer';
import { InnerLevel, PillSelect, Section, Surface } from './ui';
import { saveCsv } from '@/lib/tableCsv';
import { cn } from '@/ui/utils';
import { errorText } from '@/screens/console/pages/resources/shared';
import { invalidateV1, useV1, type V1State } from '@/sdk/useV1';
import type { Database, QueryResult, Table } from 'noclick';
import { FILTER_OPS, countQuery, firstRowsQuery, isReadQuery, pageQuery, sortable, takesValue, type FilterOp, type RowFilter, type Statement } from '@/lib/tableQuery';
import { Pending, ROW } from './parts';

/** Rows each read of a CSV download asks for. */
const CSV_PAGE_ROWS = 1000;

const readsOf = (database: Database) => `resources:databases/${database.id}`;

/** A row count as the schema has it: exact on SQLite, the planner's estimate on Postgres. */
function rowCountLabel(database: Database, table: Table): string | null {
    if (table.rowCount == null || table.rowCount < 0) return null;
    return `${database.engine === 'postgres' ? '≈ ' : ''}${countOf(table.rowCount, 'row')}`;
}

/** A column of a table's grid: its type, whether it hides its values, whether it sorts. */
function gridColumns(database: Database, table: Table): GridColumn[] {
    return table.columns.map((c) => ({
        name: c.name,
        type: c.type || undefined,
        key: c.primaryKey,
        secret: isSecretColumn(c.name, table.name),
        unsortable: !sortable(database.engine, c.type),
    }));
}

const run = (database: Database, statement: Statement) => database.query(statement.sql, statement.params);

export function DatabaseBody({ database }: { database: Database }) {
    const schema = useV1(`${readsOf(database)}/schema`, () => database.schema());
    const [params, setParams] = useSearchParams();
    const tableName = params.get('table');
    const querying = params.get('view') === 'query';
    // The query box keeps what was typed and what it ran while the page moves between tables.
    const [sql, setSql] = useState('');
    const [ran, setRan] = useState<{ result: QueryResult } | { error: string } | null>(null);
    useEffect(() => {
        setSql('');
        setRan(null);
    }, [database.id]);

    const go = (to: { table?: string; query?: boolean } | null) =>
        setParams((prev) => {
            const next = new URLSearchParams(prev);
            next.delete('table');
            next.delete('view');
            if (to?.table) next.set('table', to.table);
            if (to?.query) next.set('view', 'query');
            return next;
        });

    if (querying) {
        return (
            <QueryView
                database={database}
                schema={schema.data}
                sql={sql}
                setSql={setSql}
                ran={ran}
                setRan={setRan}
                onBack={() => go(tableName ? { table: tableName } : null)}
                backLabel={tableName ?? 'Tables'}
            />
        );
    }
    if (tableName) {
        const table = schema.data?.find((t) => t.name === tableName);
        return (
            <InnerLevel label="Tables" onBack={() => go(null)} trail={[{ label: 'Tables', onGo: () => go(null) }, { label: tableName, mono: true }]}>
                {table ? (
                    <TableRows
                        key={table.name}
                        database={database}
                        table={table}
                        onQuery={() => {
                            setSql(firstRowsQuery(database.engine, table, PAGE_ROWS));
                            setRan(null);
                            go({ table: table.name, query: true });
                        }}
                    />
                ) : schema.data ? (
                    <Surface>
                        <p className="px-4 py-10 text-center text-[13.5px] text-muted-foreground">
                            {database.name} has no table named {tableName}.{' '}
                            <button type="button" onClick={() => go(null)} className="font-medium text-foreground underline underline-offset-4">
                                See its tables
                            </button>
                        </p>
                    </Surface>
                ) : (
                    <Pending read={schema} rows={6} />
                )}
            </InnerLevel>
        );
    }
    return <TableList database={database} schema={schema} onOpen={(table) => go({ table })} onQuery={() => go({ query: true })} />;
}

function TableList({ database, schema, onOpen, onQuery }: { database: Database; schema: V1State<Table[]>; onOpen: (table: string) => void; onQuery: () => void }) {
    return (
        <Section
            title="Tables"
            meta={schema.data?.length || undefined}
            action={
                schema.data?.length ? (
                    <button type="button" className={BUTTON_SECONDARY} onClick={onQuery}>
                        <SquareTerminal className="h-4 w-4" />
                        Run a query
                    </button>
                ) : undefined
            }
        >
            <Pending read={schema} />
            {schema.data &&
                (schema.data.length ? (
                    <Surface>
                        <ul aria-label="Tables">
                            {schema.data.map((table) => {
                                const count = rowCountLabel(database, table);
                                return (
                                    <li key={table.name} className="border-b border-border last:border-0 dark:border-foreground/[0.06]">
                                        <button
                                            type="button"
                                            onClick={() => onOpen(table.name)}
                                            className={cn(ROW, 'group w-full border-0 text-left transition-colors hover:bg-foreground/[0.03] focus-visible:bg-foreground/[0.03] focus-visible:outline-none')}
                                        >
                                            <span className="min-w-0 flex-1">
                                                <span className="block truncate font-mono text-[13px] text-foreground">{table.name}</span>
                                                <span className="block truncate text-[12.5px] text-muted-foreground">{table.columns.map((c) => c.name).join(', ')}</span>
                                            </span>
                                            {count && <span className="shrink-0 text-[13px] tabular-nums text-muted-foreground">{count}</span>}
                                            <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground/60 transition-transform duration-200 group-hover:translate-x-0.5 group-hover:text-muted-foreground" />
                                        </button>
                                    </li>
                                );
                            })}
                        </ul>
                    </Surface>
                ) : (
                    <p className="text-[13.5px] text-muted-foreground">No tables yet. Your website or agent makes them, usually with a migration.</p>
                ))}
        </Section>
    );
}

const TOOL_FIELD = 'h-8 min-w-0 rounded-full border border-border bg-transparent px-3 text-[13px] text-foreground outline-none transition-colors placeholder:text-[hsl(var(--placeholder))] focus:border-foreground/25 dark:border-foreground/[0.1] dark:focus:border-foreground/25';

/** Narrows a table to the rows whose column holds a value, or is NULL. Applied on Enter or Filter. */
function FilterBar({ columns, filter, onFilter }: { columns: readonly GridColumn[]; filter: RowFilter | null; onFilter: (filter: RowFilter | null) => void }) {
    // Starts on the first text a person would look for (a name, an email), not the key.
    const [column, setColumn] = useState(filter?.column ?? (columns.find((c) => !c.secret && !c.key && /char|text|clob/i.test(c.type ?? '')) ?? columns[0])?.name ?? '');
    const [op, setOp] = useState<FilterOp>(filter?.op ?? 'contains');
    const [value, setValue] = useState(filter?.value ?? '');
    const submit = (e: FormEvent) => {
        e.preventDefault();
        if (takesValue(op) && value === '') onFilter(null);
        else onFilter({ column, op, value: takesValue(op) ? value : '' });
    };
    return (
        <form role="search" aria-label="Filter rows" onSubmit={submit} className="flex min-w-0 flex-wrap items-center gap-2">
            <PillSelect label="Column" value={column} options={columns.map((c) => ({ value: c.name, label: c.name }))} onChange={setColumn} className="font-mono" />
            <PillSelect label="Match" value={op} options={FILTER_OPS} onChange={setOp} />
            {takesValue(op) && <input aria-label="Value" value={value} onChange={(e) => setValue(e.target.value)} placeholder="Value" className={cn(TOOL_FIELD, 'w-44')} />}
            <button type="submit" className={cn(BUTTON_SECONDARY, 'h-8 px-3.5')}>
                Filter
            </button>
            {filter && (
                <button
                    type="button"
                    onClick={() => {
                        setValue('');
                        onFilter(null);
                    }}
                    className={cn(BUTTON_GHOST, 'h-8 px-2.5')}
                >
                    <X className="h-3.5 w-3.5" />
                    Clear
                </button>
            )}
        </form>
    );
}

/** The order a click on a header moves a sort to: up, down, then the table's own. */
function nextSort(sort: GridSort | null, column: string): GridSort | null {
    if (sort?.column !== column) return { column, dir: 'asc' };
    return sort.dir === 'asc' ? { column, dir: 'desc' } : null;
}

/** Where a row sits among the table's, for its panel: its key's values, else its place. */
function rowName(table: Table, row: GridRow, place: number): string {
    const key = table.columns.filter((c) => c.primaryKey);
    if (!key.length) return `Row ${place.toLocaleString('en-US')}`;
    return key.map((c) => `${c.name} ${row[c.name] === null ? 'NULL' : String(row[c.name])}`).join(' · ');
}

function TableRows({ database, table, onQuery }: { database: Database; table: Table; onQuery: () => void }) {
    const [sort, setSort] = useState<GridSort | null>(null);
    const [filter, setFilter] = useState<RowFilter | null>(null);
    const [offset, setOffset] = useState(0);
    const [open, setOpen] = useState<number | null>(null);
    const [saving, setSaving] = useState(false);
    const columns = useMemo(() => gridColumns(database, table), [database, table]);
    const view = { filter, sort, offset, limit: PAGE_ROWS + 1 };
    const pageKey = JSON.stringify({ t: table.name, f: filter, s: sort, o: offset });
    const page = useV1(`${readsOf(database)}/rows?${pageKey}`, () => run(database, pageQuery(database.engine, table, view)));
    const count = useV1(`${readsOf(database)}/count?${JSON.stringify({ t: table.name, f: filter })}`, () => run(database, countQuery(database.engine, table, filter)));
    const reveal = useReveal(table.name, pageKey);
    // The rows read on without a total: the pager says only which rows they are.
    useEffect(() => {
        if (count.error !== undefined) console.warn(`[resources] counting ${table.name}'s rows failed:`, count.error);
    }, [count.error, table.name]);

    const rows = page.data?.rows.slice(0, PAGE_ROWS);
    const more = (page.data?.rows.length ?? 0) > PAGE_ROWS;
    const counted = count.data?.rows[0]?.n;
    const total = typeof counted === 'number' ? counted : !filter && database.engine === 'sqlite' && table.rowCount != null ? table.rowCount : null;
    const totalLabel = total !== null ? total.toLocaleString('en-US') : !filter && table.rowCount != null && table.rowCount >= 0 ? `≈ ${table.rowCount.toLocaleString('en-US')}` : null;
    const expected = Math.min(PAGE_ROWS, Math.max(1, (total ?? table.rowCount ?? 8) - offset));
    const secret = columns.some((c) => c.secret);

    const move = (change: () => void) => {
        setOpen(null);
        change();
    };
    const saveRows = async () => {
        setSaving(true);
        const id = toast.loading(`Reading ${table.name}…`);
        try {
            const all: GridRow[] = [];
            for (;;) {
                const read = await run(database, pageQuery(database.engine, table, { filter, sort, offset: all.length, limit: CSV_PAGE_ROWS }));
                all.push(...read.rows);
                if (read.rows.length < CSV_PAGE_ROWS) break;
                toast.loading(`Reading ${table.name}… ${countOf(all.length, 'row')}`, { id });
            }
            saveCsv(all, table.name, table.columns.map((c) => c.name));
            toast.success(`Saved ${countOf(all.length, 'row')} as ${table.name}.csv`, { id });
        } catch (error) {
            toast.error(`Download failed: ${errorText(error)}`, { id });
        } finally {
            setSaving(false);
        }
    };

    const openRow = open !== null ? rows?.[open] : undefined;
    const fields: RecordField[] = openRow
        ? columns.map((c) => ({
              name: c.name,
              type: c.type,
              value: openRow[c.name],
              hidden: c.secret && !reveal.shown(open!, c.name),
              onReveal: () => reveal.showCell(open!, c.name),
          }))
        : [];

    return (
        <>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
                <FilterBar
                    columns={columns}
                    filter={filter}
                    onFilter={(next) =>
                        move(() => {
                            setFilter(next);
                            setOffset(0);
                        })
                    }
                />
                <span className="ml-auto flex items-center gap-1">
                    <button type="button" onClick={onQuery} className={cn(BUTTON_GHOST, 'h-8 px-2.5')}>
                        <SquareTerminal className="h-4 w-4" />
                        Query
                    </button>
                    <button type="button" onClick={() => void saveRows()} disabled={saving} className={cn(BUTTON_GHOST, 'h-8 px-2.5')}>
                        {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
                        Download CSV
                    </button>
                    <button type="button" aria-label="Refresh" title="Read it again" onClick={() => invalidateV1(readsOf(database))} className={cn(BUTTON_GHOST, 'h-8 w-8 justify-center px-0')}>
                        <RefreshCw className="h-4 w-4" />
                    </button>
                </span>
            </div>
            {page.error !== undefined && page.data === undefined ? (
                <Surface>
                    <p role="alert" className="px-4 py-6 text-[13.5px] text-muted-foreground">
                        {errorText(page.error)}{' '}
                        <button type="button" onClick={() => void page.refresh()} className="font-medium text-foreground underline underline-offset-4">
                            Try again
                        </button>
                    </p>
                </Surface>
            ) : (
                <DataGrid
                    label={`Rows of ${table.name}`}
                    columns={columns}
                    rows={rows}
                    loadingRows={expected}
                    sort={sort}
                    onSort={(column) =>
                        move(() => {
                            setSort(nextSort(sort, column));
                            setOffset(0);
                        })
                    }
                    onOpen={setOpen}
                    openRow={open}
                    reveal={reveal}
                    empty={filter ? 'No rows match this filter.' : 'No rows yet.'}
                    footer={
                        rows && (rows.length > 0 || offset > 0) ? (
                            <GridPager
                                from={offset}
                                shown={rows.length}
                                total={totalLabel}
                                onPrevious={offset > 0 ? () => move(() => setOffset(Math.max(0, offset - PAGE_ROWS))) : undefined}
                                onNext={more ? () => move(() => setOffset(offset + PAGE_ROWS)) : undefined}
                            />
                        ) : undefined
                    }
                />
            )}
            {secret && <p className="text-[12.5px] leading-snug text-muted-foreground">{SECRET_NOTE}</p>}
            <RecordDrawer
                open={!!openRow}
                onOpenChange={(o) => !o && setOpen(null)}
                title={table.name}
                description={openRow ? rowName(table, openRow, offset + open! + 1) : undefined}
                fields={fields}
                steps={
                    openRow && rows
                        ? {
                              where: `Row ${(offset + open! + 1).toLocaleString('en-US')}${totalLabel ? ` of ${totalLabel}` : ''}`,
                              onPrevious: open! > 0 ? () => setOpen(open! - 1) : undefined,
                              onNext: open! < rows.length - 1 ? () => setOpen(open! + 1) : undefined,
                          }
                        : undefined
                }
                note={secret ? 'Hidden values are hidden on this page only.' : undefined}
            />
        </>
    );
}

/** A query's result as rows, a page at a time on the page: it's read whole. */
function ResultRows({ result, label }: { result: QueryResult; label: string }) {
    const [offset, setOffset] = useState(0);
    const [open, setOpen] = useState<number | null>(null);
    useEffect(() => {
        setOffset(0);
        setOpen(null);
    }, [result]);
    const columns = useMemo(() => columnsOf(result.rows, result.columns), [result]);
    const reveal = useReveal(result.columns.join('\u0000'), String(offset));
    const rows = result.rows.slice(offset, offset + PAGE_ROWS);
    const openRow = open !== null ? rows[open] : undefined;
    const turn = (to: number) => {
        setOpen(null);
        setOffset(to);
    };
    return (
        <>
            <DataGrid
                label={label}
                columns={columns}
                rows={rows}
                onOpen={setOpen}
                openRow={open}
                reveal={reveal}
                empty="The query returned no rows."
                footer={
                    result.rows.length > PAGE_ROWS ? (
                        <GridPager
                            from={offset}
                            shown={rows.length}
                            total={result.rows.length.toLocaleString('en-US')}
                            onPrevious={offset > 0 ? () => turn(offset - PAGE_ROWS) : undefined}
                            onNext={offset + PAGE_ROWS < result.rows.length ? () => turn(offset + PAGE_ROWS) : undefined}
                        />
                    ) : undefined
                }
            />
            {columns.some((c) => c.secret) && <p className="text-[12.5px] leading-snug text-muted-foreground">{SECRET_NOTE}</p>}
            <RecordDrawer
                open={!!openRow}
                onOpenChange={(o) => !o && setOpen(null)}
                title="Result"
                description={openRow ? `Row ${(offset + open! + 1).toLocaleString('en-US')} of ${result.rows.length.toLocaleString('en-US')}` : undefined}
                fields={
                    openRow
                        ? columns.map((c) => ({ name: c.name, value: openRow[c.name], hidden: c.secret && !reveal.shown(open!, c.name), onReveal: () => reveal.showCell(open!, c.name) }))
                        : []
                }
                steps={
                    openRow
                        ? {
                              where: `Row ${(offset + open! + 1).toLocaleString('en-US')}`,
                              onPrevious: open! > 0 ? () => setOpen(open! - 1) : undefined,
                              onNext: open! < rows.length - 1 ? () => setOpen(open! + 1) : undefined,
                          }
                        : undefined
                }
            />
        </>
    );
}

function QueryView({
    database,
    schema,
    sql,
    setSql,
    ran,
    setRan,
    onBack,
    backLabel,
}: {
    database: Database;
    schema: Table[] | undefined;
    sql: string;
    setSql: (sql: string) => void;
    ran: { result: QueryResult } | { error: string } | null;
    setRan: (ran: { result: QueryResult } | { error: string } | null) => void;
    onBack: () => void;
    backLabel: string;
}) {
    const [running, setRunning] = useState(false);
    const box = useRef<HTMLTextAreaElement>(null);
    // Opened by asking to run a query: the box is where the next keystroke goes.
    useEffect(() => box.current?.focus(), []);
    const typed = sql.trim().length > 0;
    const readable = isReadQuery(sql);
    const first = schema?.[0];
    const runQuery = async () => {
        if (!readable || running) return;
        setRunning(true);
        try {
            setRan({ result: await database.query(sql.trim()) });
        } catch (error) {
            setRan({ error: errorText(error) });
        } finally {
            setRunning(false);
        }
    };
    const result = ran && 'result' in ran ? ran.result : null;
    return (
        <InnerLevel label={backLabel} onBack={onBack} trail={[{ label: backLabel, onGo: onBack, mono: backLabel !== 'Tables' }, { label: 'Query' }]}>
            <form
                className="space-y-2"
                onSubmit={(e) => {
                    e.preventDefault();
                    void runQuery();
                }}
            >
                <textarea
                    aria-label="SQL"
                    rows={5}
                    spellCheck={false}
                    ref={box}
                    value={sql}
                    onChange={(e) => setSql(e.target.value)}
                    onKeyDown={(e) => {
                        if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                            e.preventDefault();
                            void runQuery();
                        }
                    }}
                    placeholder={first ? firstRowsQuery(database.engine, first, 20) : 'select 1'}
                    className={cn(FIELD, 'h-auto min-h-[7.5rem] resize-y py-2.5 font-mono text-[13px] leading-relaxed')}
                />
                <div className="flex flex-wrap items-center gap-3">
                    <p className={cn('m-0 min-w-0 flex-1 text-[12.5px]', typed && !readable ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground')}>
                        {typed && !readable
                            ? 'Only a single select runs here: anything that writes, or a second statement, is refused.'
                            : `Read-only: one select at a time, on the ${database.engine === 'postgres' ? 'Postgres' : 'SQLite'} database itself.`}
                    </p>
                    <button type="submit" disabled={!readable || running} className={BUTTON_PRIMARY}>
                        {running && <Loader2 className="h-4 w-4 animate-spin" />}
                        Run
                    </button>
                </div>
            </form>
            {ran && 'error' in ran && (
                <p role="alert" className="m-0 rounded-xl border border-red-500/20 bg-red-500/[0.04] px-4 py-3 font-mono text-[12.5px] leading-relaxed text-red-700 dark:text-red-300">
                    {ran.error}
                </p>
            )}
            {result && (
                <>
                    <div className="flex flex-wrap items-center gap-3 pt-2">
                        <span className="text-[13px] tabular-nums text-muted-foreground">
                            {countOf(result.rows.length, 'row')}
                            {result.durationMs !== null && ` · ${result.durationMs < 1 ? 'under 1' : Math.round(result.durationMs).toLocaleString('en-US')} ms`}
                        </span>
                        {result.rows.length > 0 && (
                            <button type="button" onClick={() => saveCsv(result.rows, `${database.name}-query`, result.columns)} className={cn(BUTTON_GHOST, 'ml-auto h-8 px-2.5')}>
                                <Download className="h-4 w-4" />
                                Download CSV
                            </button>
                        )}
                    </div>
                    <ResultRows result={result} label="Query result" />
                </>
            )}
        </InnerLevel>
    );
}
