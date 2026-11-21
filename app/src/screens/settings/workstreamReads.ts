// Settings → Workstreams' read: the account's workstreams, open and archived, each with what it spent this month,
// read with GET /v1/workstreams through the client its host hands it (`ClientProvider`), renamed and archived with
// PATCH /v1/workstreams/{id}. Read again on the host's live frames (`WorkLiveContext`): one renamed or archived anywhere
// (a `workstream` resource), a charge (a new one arrives with its first, and spend moves), or a `reset`; never on a
// timer. A change here has the Usage page read again too, since it names each charge's workstream.
import { useCallback } from 'react';
import { Workstream } from 'noclick';
import { useClient } from '@/sdk/client';
import { useWorkFrames } from '@/sdk/live';
import { invalidateV1, useV1 } from '@/sdk/useV1';
import { readUsageAgain } from '@/screens/usage/reads';

/** The read's key in the client's cache. */
export const WORKSTREAMS_READ = 'settings:workstreams';

/** Reads the workstreams again wherever they're drawn: what a host calls when it hears of a change its own way. */
export function readWorkstreamsAgain(): void {
    invalidateV1(WORKSTREAMS_READ);
}

/** One workstream as the section shows it. */
export interface WorkstreamRow {
    id: string;
    name: string;
    spentUsd: number;
    archived: boolean;
}

export interface WorkstreamsState {
    /** The open ones, most spent this month first, and the archived ones; null while they're read. */
    open: WorkstreamRow[] | null;
    archived: WorkstreamRow[] | null;
    /** Why they didn't load, with nothing to show. */
    error: string | null;
    retry: () => void;
    /** Renames one, resolving to the workstream it reads as now (another one's, when it merged) once the list is
     *  read again; rejects with the API's refusal. */
    rename: (id: string, name: string) => Promise<WorkstreamRow>;
    /** Archives one, or brings it back, once the list is read again; rejects with the API's refusal. */
    setArchived: (id: string, archived: boolean) => Promise<void>;
}

const rowOf = (w: Workstream): WorkstreamRow => ({ id: w.id, name: w.name, spentUsd: w.spentUsd, archived: w.archived });

export function useWorkstreams(): WorkstreamsState {
    const client = useClient();
    const read = useV1(
        WORKSTREAMS_READ,
        async () => {
            const [open, archived] = await Promise.all([Workstream.list({ client }), Workstream.list({ client, archived: true })]);
            return { open: open.map(rowOf), archived: archived.map(rowOf) };
        },
        { client }
    );
    useWorkFrames('platform:resource', (frame) => {
        if (frame.kind === 'workstream') readWorkstreamsAgain();
    });
    useWorkFrames('platform:usage', readWorkstreamsAgain);
    useWorkFrames('reset', readWorkstreamsAgain);
    const { refresh } = read;

    const rename = useCallback(
        async (id: string, name: string) => {
            const now = rowOf(await Workstream.rename(id, name, { client }));
            await refresh();
            readUsageAgain();
            return now;
        },
        [client, refresh]
    );
    const setArchived = useCallback(
        async (id: string, archived: boolean) => {
            await (archived ? Workstream.archive(id, { client }) : Workstream.unarchive(id, { client }));
            await refresh();
        },
        [client, refresh]
    );

    return {
        open: read.data?.open ?? null,
        archived: read.data?.archived ?? null,
        error: read.data || read.error === undefined ? null : read.error instanceof Error ? read.error.message : 'Your workstreams didn’t load.',
        retry: () => void refresh(),
        rename,
        setArchived,
    };
}
