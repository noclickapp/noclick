// Fixtures for what workflows keep (their files and tables, a table's rows) and the account's own files: canned /v1
// answers shaped like the API's own, so Resources' lab and its tests run the real client. A file's link is a sealed
// address on a test host; a table's rows are made up from its index, as many as its row count, in pages as the route
// pages them. Deleting answers as the route does, and its preview says what the API's says.
import { DAY, HOUR, MIN, ago, apiError, fixtureId, ok, pageList, type FixtureReply, type FixtureRequest, type FixtureRoute } from '../core';

const workflowId = (n: number) => fixtureId(7, 150_000 + n);
const fileId = (n: number) => fixtureId(7, 151_000 + n);
const tableId = (n: number) => fixtureId(7, 152_000 + n);
const attachmentId = (n: number) => fixtureId(7, 153_000 + n);

/** A link the way the API hands one out: a sealed address that reads the file for an hour. */
const link = (name: string) => `https://files.example.test/f/fixture-${encodeURIComponent(name)}/${encodeURIComponent(name)}`;
const LINK_EXPIRES = ago(-HOUR);

const INTAKE = { id: workflowId(1), name: 'Order intake', step_types: ['trigger-webhook', 'agent:claude-code', 'automation-gmail'] };
const REPORT = { id: workflowId(2), name: 'Weekly report', step_types: ['trigger-cron', 'automation-google-sheets'] };
// Shared with the account to view: it reads the workflow's files, and deletes none.
const PRICING = { id: workflowId(3), name: 'Pricing', step_types: ['trigger-webhook', 'agent'] };

function file(n: number, workflow: typeof INTAKE, access: string, name: string, type: string, mime: string, size: number, at: string) {
    return {
        object: 'workflow_file', id: fileId(n), name, workflow, access, step_id: 'upload', type, mime_type: mime, size_bytes: size,
        url: link(name), url_expires_at: LINK_EXPIRES, created_at: at, updated_at: at,
    };
}

export const WORKFLOW_FILES = [
    file(1, INTAKE, 'owner', 'invoice-1042.pdf', 'document', 'application/pdf', 84_210, ago(2 * HOUR)),
    file(2, INTAKE, 'owner', 'receipt.png', 'image', 'image/png', 48_116, ago(5 * HOUR)),
    file(3, REPORT, 'owner', 'notes.md', 'document', 'text/markdown', 2_304, ago(DAY)),
    file(4, REPORT, 'owner', 'export.csv', 'file', 'text/csv', 18_442, ago(3 * DAY)),
    file(5, PRICING, 'viewer', 'price-list.pdf', 'document', 'application/pdf', 120_032, ago(6 * DAY)),
];

function table(n: number, workflow: typeof INTAKE, access: string, name: string, rows: number, databaseId: string | null, at: string) {
    return { object: 'workflow_table', id: tableId(n), name, workflow, access, step_id: 'table', row_count: rows, database_id: databaseId, created_at: at, updated_at: at };
}

export const WORKFLOW_TABLES = [
    table(1, INTAKE, 'owner', 'Orders', 2_500, fixtureId(7, 152_900), ago(30 * MIN)),
    table(2, INTAKE, 'owner', 'Customers', 42, fixtureId(7, 152_900), ago(4 * HOUR)),
    table(3, PRICING, 'viewer', 'Prices', 12, null, ago(8 * DAY)),
];

function attachment(n: number, name: string, mime: string, kind: string, size: number, at: string) {
    return { object: 'attachment', id: attachmentId(n), name, mime_type: mime, size_bytes: size, kind, voice: false, duration_ms: null, peaks: null, url: link(name), url_expires_at: LINK_EXPIRES, created_at: at, updated_at: at };
}

export const ACCOUNT_FILES = [
    attachment(1, 'Q3 summary.pdf', 'application/pdf', 'file', 58_703, ago(DAY + HOUR)),
    attachment(2, 'Sales by region.png', 'image/png', 'image', 181_369, ago(2 * DAY)),
];

const PLANS = ['Starter', 'Team', 'Business'];

/** A table's row `index`, made up from it. */
function row(table: string, index: number) {
    return {
        object: 'table_row', id: `${table}-${index}`, index,
        data: { order: 10_000 + index, email: `customer${index}@example.test`, plan: PLANS[index % PLANS.length], total: Math.round((index % 97) * 12.5 * 100) / 100 },
        created_at: ago(DAY - index * MIN),
    };
}

function rows(request: FixtureRequest): FixtureReply {
    const found = WORKFLOW_TABLES.find((t) => t.id === request.params.id);
    if (!found || request.set !== 'populated') return apiError(404, 'not_found', `No table '${request.params.id}' in a workflow this account can open.`);
    const start = Number(request.query.get('cursor') ?? 0);
    const limit = Number(request.query.get('limit') ?? 100);
    const end = Math.min(found.row_count, start + limit);
    const data = Array.from({ length: Math.max(0, end - start) }, (_, i) => row(found.id, start + i));
    return ok({ object: 'list', data, total_count: found.row_count, next_cursor: end < found.row_count ? String(end) : null });
}

/** What deleting `path` does, as the API previews it; null for a path these fixtures don't hold. */
function impact(path: string): Record<string, unknown> | null {
    const [, , area, kind, id] = path.split('/');
    const named =
        area === 'workflows' && kind === 'files'
            ? WORKFLOW_FILES.find((f) => f.id === id)
            : area === 'workflows' && kind === 'tables'
              ? WORKFLOW_TABLES.find((t) => t.id === id)
              : area === 'attachments'
                ? ACCOUNT_FILES.find((f) => f.id === kind)
                : undefined;
    if (!named) return null;
    if ('row_count' in named) {
        return { deletes: `Deletes the table '${named.name}' of the workflow '${named.workflow.name}' for good.`, depends_on_it: ['A step or an interface that reads or adds to it fails on its next run.'], data_lost: [`Its ${named.row_count.toLocaleString('en-US')} rows: nothing keeps a copy.`], stops_billing: [], reversible: false, undo: null };
    }
    if ('workflow' in named) {
        return { deletes: `Deletes the file '${named.name}' of the workflow '${named.workflow.name}' for good.`, depends_on_it: ['A step that reads it by its id finds nothing there on its next run, and its links stop working.'], data_lost: [`Its contents (${named.size_bytes.toLocaleString('en-US')} bytes): nothing keeps a copy.`], stops_billing: [], reversible: false, undo: null };
    }
    return { deletes: `Deletes the file '${named.name}' from the account's files for good.`, depends_on_it: [], data_lost: [`Its contents (${named.size_bytes.toLocaleString('en-US')} bytes): nothing keeps a copy.`], stops_billing: [], reversible: false, undo: null };
}

export const routes: FixtureRoute[] = [
    { method: 'GET', path: '/v1/workflows/files', reply: (request) => pageList(request, WORKFLOW_FILES) },
    { method: 'GET', path: '/v1/workflows/tables', reply: (request) => pageList(request, WORKFLOW_TABLES) },
    { method: 'GET', path: '/v1/workflows/tables/:id/rows', reply: rows },
    { method: 'GET', path: '/v1/attachments', reply: (request) => pageList(request, ACCOUNT_FILES) },
    {
        method: 'POST',
        path: '/v1/delete_previews',
        reply: (request) => {
            const body = (request.body ?? {}) as { method?: string; path?: string };
            const found = body.method === 'DELETE' && body.path ? impact(body.path) : null;
            return found ? ok({ object: 'delete_preview', method: 'DELETE', path: body.path, impact: found }) : apiError(404, 'not_found', `No fixture previews DELETE ${body.path}.`);
        },
    },
    { method: 'DELETE', path: '/v1/workflows/files/:id', reply: (request) => ok({ object: 'workflow_file', id: request.params.id, deleted: true }) },
    { method: 'DELETE', path: '/v1/workflows/tables/:id', reply: (request) => ok({ object: 'workflow_table', id: request.params.id, deleted: true }) },
    { method: 'DELETE', path: '/v1/attachments/:id', reply: (request) => ok({ object: 'attachment', id: request.params.id, deleted: true }) },
];
