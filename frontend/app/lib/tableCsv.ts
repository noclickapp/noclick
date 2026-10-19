// An automation's tables as CSV: the one reader for a CSV a person brings (an
// interface's Table block imports one, a CSV file previews as one) and the
// writer a table downloads through, every row of it, a page at a time.
import { downloadText } from '~/lib/download';
import { sendEventAsync } from '~/lib/socket-sender';
import { ResourceDatasetRowsRequest } from '~/types/socket-events.generated';

export type TableRow = Record<string, unknown>;

/** What one read asks for: the most a page holds (`utils/dataset_store.MAX_PAGE_ROWS`). */
const PAGE_ROWS = 10_000;

/** A CSV's header and records (RFC 4180: a quoted field holds commas, line breaks and doubled quotes). */
export function parseCsv(text: string): { headers: string[]; rows: string[][] } {
    const records: string[][] = [];
    let record: string[] = [];
    let field = '';
    let quoted = false;
    const body = text.replace(/^\uFEFF/, '');
    for (let i = 0; i < body.length; i++) {
        const c = body[i];
        if (quoted) {
            if (c !== '"') field += c;
            else if (body[i + 1] === '"') {
                field += '"';
                i++;
            } else quoted = false;
        } else if (c === '"') quoted = true;
        else if (c === ',') {
            record.push(field);
            field = '';
        } else if (c === '\n' || c === '\r') {
            if (c === '\r' && body[i + 1] === '\n') i++;
            record.push(field);
            records.push(record);
            record = [];
            field = '';
        } else field += c;
    }
    if (field || record.length) records.push([...record, field]);
    const [headers = [], ...rows] = records.filter((r) => r.some((v) => v.trim() !== ''));
    return { headers: headers.map((h) => h.trim()), rows };
}

/** A CSV's records as a table's rows: one object each, keyed by the header, numbers read as numbers. */
export function csvToRows(text: string): TableRow[] {
    const { headers, rows } = parseCsv(text);
    return rows.map((values) =>
        Object.fromEntries(
            headers.map((h, i) => {
                const v = (values[i] ?? '').trim();
                return [h, v !== '' && !Number.isNaN(Number(v)) ? Number(v) : v];
            })
        )
    );
}

function cell(value: unknown): string {
    const text = value == null ? '' : typeof value === 'object' ? JSON.stringify(value) : String(value);
    return /[",\r\n]|^\s|\s$/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

/** Rows as CSV: `headers` in order, else one column per key in the order keys first appear (a sparse first row hides none). */
export function rowsToCsv(rows: TableRow[], headers: readonly string[] = [...new Set(rows.flatMap((r) => Object.keys(r)))]): string {
    return [headers, ...rows.map((r) => headers.map((h) => r[h]))].map((line) => line.map(cell).join(',')).join('\r\n');
}

/** Saves rows as `<name>.csv`. */
export function saveCsv(rows: TableRow[], name: string, headers?: readonly string[]): void {
    downloadText(rowsToCsv(rows, headers), /\.csv$/i.test(name) ? name : `${name}.csv`, 'text/csv;charset=utf-8');
}

/** Every row of a table, in order. */
export async function readAllRows(resourceId: string): Promise<TableRow[]> {
    const rows: TableRow[] = [];
    for (;;) {
        const page = await sendEventAsync(ResourceDatasetRowsRequest.create({ resource_id: resourceId, limit: PAGE_ROWS, offset: rows.length }));
        rows.push(...page.rows.map((r) => r.data as TableRow));
        if (!page.rows.length || rows.length >= page.total_count) return rows;
    }
}

/** Saves a table as `<name>.csv`. */
export async function downloadTableCsv(resourceId: string, name: string): Promise<void> {
    saveCsv(await readAllRows(resourceId), name);
}
