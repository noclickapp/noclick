// What workflows keep (their files and tables) and the account's own files, read through /v1 for the workspace the
// page shows (context.ts: a team workspace by its id, or `none` for the workflows in no workspace; absent, every
// workflow the account reads). Each list is read to its end, and read
// again before the links it handed out stop (an hour after they're listed). A file is deleted as the API deletes it,
// its preview's words first; one of a workflow shared to view only offers none.
import { useMemo } from 'react';
import { WorkflowFile, WorkflowTable, attachmentsPage, deleteAttachment, type Attachment, type NoClick, type Page } from 'noclick';
import type { FileEntry, FileKind, FileSource } from './files';
import { useClient } from '@/sdk/client';
import { invalidateV1, useV1 } from '@/sdk/useV1';
import { errorText } from '@/screens/console/pages/resources/shared';
import { useResources } from './context';
import type { DeletionImpact, Removal } from './platform';

/** A file or table, as the page lists it. */
export interface FileRef {
    entry: FileEntry;
    source: FileSource;
    /** How its page deletes it; absent where the viewer may not (a workflow shared with them to view). */
    removal?: Removal;
}

/** One of a workflow's tables: its rows are read through it. */
export interface TableRef extends FileRef {
    table: WorkflowTable;
}

const KEY = 'resources:kept:';
/** Every list is read again before the links it handed out stop answering (an hour after they're listed). */
const LINKS_LAST_MS = 50 * 60_000;
const PAGE = 100;

/** Every item of a paged list. */
async function every<T>(read: (cursor: string | null) => Promise<Page<T>>): Promise<T[]> {
    const found: T[] = [];
    for (let cursor: string | null = null; ; ) {
        const page = await read(cursor);
        found.push(...page.data);
        if (!page.nextCursor) return found;
        cursor = page.nextCursor;
    }
}

const ext = (name: string) => (name.includes('.') ? name.slice(name.lastIndexOf('.') + 1).toLowerCase() : '');

/** A stored file's kind, as the app's file listing has always read it: its content type, then its stored type, then
 *  its name (`dashboard_handler._file_kind`). */
export function storedFileKind(mime: string | null, type: string | null, name: string): FileKind {
    const m = (mime ?? '').toLowerCase();
    const e = ext(name);
    if (m.startsWith('image/') || type === 'image' || ['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg'].includes(e)) return 'image';
    if (m.startsWith('video/') || type === 'video' || ['mp4', 'webm', 'mov', 'm4v', 'mkv'].includes(e)) return 'video';
    if (m.startsWith('audio/') || type === 'audio' || ['mp3', 'wav', 'ogg', 'oga', 'm4a', 'aac'].includes(e)) return 'audio';
    if (type === 'dataset' || ['csv', 'tsv', 'xlsx', 'json', 'parquet'].includes(e)) return 'data';
    if (['py', 'js', 'ts', 'tsx', 'sh', 'sql', 'yaml', 'yml', 'toml'].includes(e)) return 'code';
    if (['zip', 'tar', 'gz', '7z'].includes(e)) return 'archive';
    if (type === 'document' || m.startsWith('text/') || ['pdf', 'md', 'txt', 'doc', 'docx'].includes(e)) return 'doc';
    return 'other';
}

const isPdf = (mime: string | null) => (mime ?? '').toLowerCase().includes('pdf');

/** The stored type a preview draws a file by. A file's link shows in place only a picture, a PDF, sound or video and
 *  saves anything else, so a document that isn't a PDF is previewed as a file (its text read, else offered to
 *  download) rather than framed, which would only save it. */
function previewType(type: string | null, mime: string | null): string {
    if (type && type !== 'document') return type;
    return isPdf(mime) ? 'document' : 'file';
}

async function previewDelete(client: NoClick, path: string): Promise<DeletionImpact> {
    try {
        return (await client.request<{ impact: DeletionImpact }>('POST', '/v1/delete_previews', { json: { method: 'DELETE', path } })).impact;
    } catch (error) {
        throw new Error(errorText(error));
    }
}

function removal(client: NoClick, what: 'file' | 'table', name: string, path: string, run: () => Promise<void>): Removal {
    return {
        label: 'Delete',
        confirm: `Delete ${what}`,
        preview: () => previewDelete(client, path),
        async run() {
            try {
                await run();
            } catch (error) {
                throw new Error(errorText(error));
            }
            invalidateV1(KEY);
            return { done: `Deleted ${name}`, gone: true };
        },
    };
}

/** Where a workflow's files and tables are listed: the workflow, drawn by its marks. */
function workflowSource(item: WorkflowFile | WorkflowTable): FileSource {
    const workflow = item.workflow;
    const name = workflow.name || 'Untitled workflow';
    return {
        id: `resources:${workflow.id}`,
        kind: 'resources',
        writable: item.access !== 'viewer',
        label: name,
        sublabel: 'Uploads & outputs',
        workflow: { id: workflow.id, name, marks: workflow.stepTypes },
        files: [],
    };
}

const ACCOUNT_SOURCE: FileSource = { id: 'resources:account', kind: 'resources', writable: true, label: 'Personal files', sublabel: 'Uploads & attachments', files: [] };

const iso = (at: Date | null) => (at ?? new Date(0)).toISOString();

function fileRef(client: NoClick, file: WorkflowFile): FileRef {
    const source = workflowSource(file);
    const entry: FileEntry = {
        path: file.name,
        size: file.sizeBytes ?? 0,
        mtime: iso(file.updatedAt),
        kind: storedFileKind(file.mimeType, file.type, file.name),
        resourceId: file.id,
        resourceType: previewType(file.type, file.mimeType),
        mime: file.mimeType,
        url: file.url,
        rows: null,
    };
    const path = `/v1/workflows/files/${encodeURIComponent(file.id)}`;
    return { entry, source, removal: source.writable ? removal(client, 'file', file.name, path, () => file.delete()) : undefined };
}

function tableRef(client: NoClick, table: WorkflowTable): TableRef {
    const source = workflowSource(table);
    const entry: FileEntry = {
        path: table.name,
        size: 0,
        mtime: iso(table.updatedAt),
        kind: storedFileKind(null, 'dataset', table.name),
        resourceId: table.id,
        resourceType: 'dataset',
        mime: null,
        url: null,
        rows: table.rowCount,
        databaseId: table.databaseId,
    };
    const path = `/v1/workflows/tables/${encodeURIComponent(table.id)}`;
    return { entry, source, table, removal: source.writable ? removal(client, 'table', table.name, path, () => table.delete()) : undefined };
}

function accountRef(client: NoClick, file: Attachment): FileRef {
    const id = file.id!;
    const entry: FileEntry = {
        path: file.name,
        size: file.sizeBytes ?? 0,
        mtime: iso(file.updatedAt ?? file.createdAt),
        kind: storedFileKind(file.mimeType, null, file.name),
        resourceId: id,
        resourceType: previewType(null, file.mimeType),
        mime: file.mimeType,
        url: file.url || null,
        rows: null,
    };
    const path = `/v1/attachments/${encodeURIComponent(id)}`;
    return { entry, source: ACCOUNT_SOURCE, removal: removal(client, 'file', file.name, path, () => deleteAttachment(id, { client })) };
}

export interface Kept {
    /** The workflows' files, then the account's own. */
    files: FileRef[];
    tables: TableRef[];
    loading: { files: boolean; tables: boolean };
    /** Why a list couldn't be read, in a sentence. */
    errors: { files?: string; tables?: string };
}

/** Reads every list again: after a change elsewhere (an upload, a delete). */
export function refreshKept(): void {
    invalidateV1(KEY);
}

export function useKept(): Kept {
    const client = useClient();
    const { workspace } = useResources();
    const links = { pollMs: LINKS_LAST_MS };
    const files = useV1(`${KEY}files:${workspace ?? '*'}`, () => every((cursor) => WorkflowFile.listPage({ client, organizationId: workspace, cursor, limit: PAGE })), links);
    const tables = useV1(`${KEY}tables:${workspace ?? '*'}`, () => every((cursor) => WorkflowTable.listPage({ client, organizationId: workspace, cursor, limit: PAGE })));
    const account = useV1(`${KEY}account`, () => every((cursor) => attachmentsPage({ client, cursor, limit: PAGE })), links);
    const fileRefs = useMemo(
        () => [...(files.data ?? []).map((f) => fileRef(client, f)), ...(account.data ?? []).filter((f) => f.id).map((f) => accountRef(client, f))],
        [client, files.data, account.data]
    );
    const tableRefs = useMemo(() => (tables.data ?? []).map((t) => tableRef(client, t)), [client, tables.data]);
    /** Why a read failed, where it has nothing to show. */
    const failed = (...reads: { error: unknown; data: unknown }[]) => {
        const error = reads.find((r) => r.error !== undefined && r.data === undefined)?.error;
        return error === undefined ? undefined : errorText(error);
    };
    return {
        files: fileRefs,
        tables: tableRefs,
        loading: { files: files.loading || account.loading, tables: tables.loading },
        errors: { files: failed(files, account), tables: failed(tables) },
    };
}
