// The reads a database's table page makes through the platform's read-only
// query (`POST /v1/databases/{id}/query` with `read_only`): a page of rows in
// a stable order (its primary key, else SQLite's rowid or Postgres's ctid),
// sorted by a column and filtered by one, and how many rows match. Values
// travel as `?` parameters, which the platform binds for either engine.
import type { DatabaseEngine } from 'noclick';

/** What a table page needs of a table: its name and its columns. */
export interface TableShape {
    name: string;
    columns: readonly { name: string; type: string; primaryKey: boolean }[];
}

export type FilterOp = 'contains' | 'equals' | 'null' | 'not_null';

export interface RowFilter {
    column: string;
    op: FilterOp;
    /** What `contains` and `equals` look for. */
    value: string;
}

export interface RowSort {
    column: string;
    dir: 'asc' | 'desc';
}

export interface Statement {
    sql: string;
    params: string[];
}

export const FILTER_OPS: { value: FilterOp; label: string }[] = [
    { value: 'contains', label: 'contains' },
    { value: 'equals', label: 'equals' },
    { value: 'null', label: 'is NULL' },
    { value: 'not_null', label: 'is not NULL' },
];

/** Whether `op` compares with a value the person types. */
export const takesValue = (op: FilterOp) => op === 'contains' || op === 'equals';

/** One read statement (`select`, `with`), after leading comments: what a query box runs. */
export function isReadQuery(sql: string): boolean {
    const body = sql.replace(/^(\s*(--[^\n]*(\n|$)|\/\*[\s\S]*?\*\/))*/, '').trim();
    const single = body.replace(/;\s*$/, '');
    return /^(select|with)\b/i.test(single) && !single.includes(';');
}

export function quoteIdentifier(name: string): string {
    return `"${name.replace(/"/g, '""')}"`;
}

/** A table as a statement names it: Postgres lists a table outside `public` as `schema.table`. */
export function tableRef(engine: DatabaseEngine, name: string): string {
    const dot = name.indexOf('.');
    if (engine !== 'postgres' || dot < 0) return quoteIdentifier(name);
    return `${quoteIdentifier(name.slice(0, dot))}.${quoteIdentifier(name.slice(dot + 1))}`;
}

/** What orders a table's rows the same way every read: its primary key, else the row's own address. */
export function stableOrder(engine: DatabaseEngine, table: TableShape): string[] {
    const key = table.columns.filter((c) => c.primaryKey).map((c) => quoteIdentifier(c.name));
    if (key.length) return key;
    if (engine === 'postgres') return ['ctid'];
    // A column may shadow the rowid's names, as the platform's own export allows for.
    const taken = new Set(table.columns.map((c) => c.name.toLowerCase()));
    const rowid = ['rowid', '_rowid_', 'oid'].find((alias) => !taken.has(alias));
    return rowid ? [rowid] : table.columns.map((c) => quoteIdentifier(c.name));
}

/** Postgres has no ordering for `json` (`jsonb` has one). */
export function sortable(engine: DatabaseEngine, type: string): boolean {
    return !(engine === 'postgres' && /^(json|xml|point|line|lseg|box|path|polygon|circle)$/i.test(type.trim()));
}

function where(engine: DatabaseEngine, filter: RowFilter | null): Statement {
    if (!filter) return { sql: '', params: [] };
    const column = quoteIdentifier(filter.column);
    switch (filter.op) {
        case 'null':
            return { sql: ` where ${column} is null`, params: [] };
        case 'not_null':
            return { sql: ` where ${column} is not null`, params: [] };
        case 'equals':
            return { sql: ` where cast(${column} as text) = ?`, params: [filter.value] };
        case 'contains': {
            // instr/strpos, not LIKE: a typed % or _ is looked for as itself.
            const find = engine === 'postgres' ? 'strpos' : 'instr';
            return { sql: ` where ${find}(lower(cast(${column} as text)), lower(cast(? as text))) > 0`, params: [filter.value] };
        }
    }
}

/** One page of `table`'s rows: `limit` of them from `offset`, in `sort`'s order and then the table's own. */
export function pageQuery(
    engine: DatabaseEngine,
    table: TableShape,
    { filter, sort, offset, limit }: { filter: RowFilter | null; sort: RowSort | null; offset: number; limit: number }
): Statement {
    const clause = where(engine, filter);
    const order = [...(sort ? [`${quoteIdentifier(sort.column)} ${sort.dir}`] : []), ...stableOrder(engine, table)];
    const page = `limit ${Math.max(0, Math.floor(limit))} offset ${Math.max(0, Math.floor(offset))}`;
    return { sql: `select * from ${tableRef(engine, table.name)}${clause.sql} order by ${order.join(', ')} ${page}`, params: clause.params };
}

/** How many of `table`'s rows `filter` matches. */
export function countQuery(engine: DatabaseEngine, table: TableShape, filter: RowFilter | null): Statement {
    const clause = where(engine, filter);
    return { sql: `select count(*) as n from ${tableRef(engine, table.name)}${clause.sql}`, params: clause.params };
}

/** A query box's starting point for a table: its first rows. */
export function firstRowsQuery(engine: DatabaseEngine, table: TableShape, limit = 50): string {
    return `select * from ${tableRef(engine, table.name)} order by ${stableOrder(engine, table).join(', ')} limit ${limit}`;
}
