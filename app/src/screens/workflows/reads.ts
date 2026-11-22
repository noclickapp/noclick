// What the workflows pages read on the platform API, with the client their host hands them: the workflows the key can
// open (`GET /v1/workflows`) and the account's folders (`GET /v1/workflows/folders`), and a new workflow
// (`POST /v1/workflows`). The list reads again when the account's change stream says a workflow moved.
import { useCallback } from 'react';
import { Workflow, type NoClick } from 'noclick';
import { useClient } from '@/sdk/client';
import { useWorkFrames } from '@/sdk/live';
import { useV1 } from '@/sdk/useV1';
import { errorText } from '@/screens/console/lib/errorText';

/** A workflow as the list shows it. */
export interface WorkflowRow {
    id: string;
    name: string;
    description: string | null;
    /** When it last changed. */
    updatedAt: Date | null;
    /** The folder of the account's it's in; null at the top, and for one shared with the account. */
    folderId: string | null;
    /** What the key may do with it: `owner`, `editor` or `viewer`. */
    access: string;
    /** Its triggers are switched off: nothing starts it on its own. */
    paused: boolean;
}

/** One of the account's folders, as the list groups under it. */
export interface FolderRow {
    id: string;
    name: string;
    /** How deep it sits: 0 at the top. */
    depth: number;
    parentId: string | null;
}

export interface WorkflowList {
    workflows: WorkflowRow[];
    folders: FolderRow[];
}

export const WORKFLOWS_READ = 'workflows:list';

async function readWorkflows(client: NoClick): Promise<WorkflowList> {
    const [workflows, folders] = await Promise.all([Workflow.list({ client }), Workflow.folders({ client })]);
    return {
        workflows: workflows.map((w) => ({ id: w.id, name: w.name, description: w.description, updatedAt: w.updatedAt, folderId: w.folderId, access: w.access, paused: w.paused })),
        folders: folders.map((f) => ({ id: f.id, name: f.name, depth: f.depth, parentId: f.parentId })),
    };
}

export interface WorkflowListRead {
    list: WorkflowList | undefined;
    /** Why it couldn't be read, where it couldn't. */
    error: string | null;
    reload: () => Promise<void>;
}

/** The workflows and folders, read again when one is made, changed or deleted anywhere (the account's change stream). */
export function useWorkflowList(): WorkflowListRead {
    const client = useClient();
    const read = useV1(WORKFLOWS_READ, () => readWorkflows(client), { client });
    const { refresh } = read;
    const again = useCallback(() => void refresh(), [refresh]);
    useWorkFrames('platform:resource', (frame) => {
        if (frame.kind === 'workflow') again();
    });
    useWorkFrames('reset', again);
    return { list: read.data, error: read.error === undefined ? null : errorText(read.error), reload: refresh };
}

/** A new, empty workflow called `name`; answers its id. */
export async function createWorkflow(client: NoClick, name: string): Promise<string> {
    return (await Workflow.create(name, { client })).id;
}
