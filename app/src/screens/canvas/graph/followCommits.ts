// Following other writers' changes to an open workflow with no host's live room (decision D3 (a)): the account's
// change stream says a workflow's graph moved to a version (`watch`, as the app's live frames carry it, @/sdk/live),
// and the canvas reads the graph again and folds it in as it folds a refused save's answer (`reloadFromServer`: what
// it changed itself is kept, the rest is the server's). Its own saves' commits are heard too, and passed by once the
// canvas holds their version.
import { useEffect, useRef } from 'react';
import { subscribe } from 'valtio';
import { useWorkLive } from '@/sdk/live';
import { graphRecords, reloadFromServer } from './liveGraphStore';

interface Reading {
    /** Another commit was heard while the read was on its way. */
    again: boolean;
    /** The highest version those left, or null where one didn't say. */
    version: number | null;
}

const reading = new Map<string, Reading>();

/** Whether the canvas already holds `version` (null: the stream couldn't say which, so it doesn't know it does). */
function holds(workflowId: string, version: number | null): boolean {
    const known = graphRecords[workflowId]?.graphVersion;
    return version !== null && known != null && version <= known;
}

/** A commit to `workflowId` that left its graph at `version` (null: something may have changed that the stream
 *  couldn't name), heard while the canvas has it open: read again unless the canvas already holds that version. A
 *  save on its way lands first, since its answer may be the version heard. */
export function followCommit(workflowId: string, version: number | null): void {
    const rec = graphRecords[workflowId];
    // Before its load lands the canvas has nothing to fold in: the load reads it as it stands.
    if (!rec?.loaded || holds(workflowId, version)) return;
    if (rec.saveInFlight) {
        const stop = subscribe(rec, () => {
            if (graphRecords[workflowId]?.saveInFlight) return;
            stop();
            followCommit(workflowId, version);
        });
        return;
    }
    const busy = reading.get(workflowId);
    if (busy) {
        busy.version = !busy.again ? version : busy.version === null || version === null ? null : Math.max(busy.version, version);
        busy.again = true;
        return;
    }
    const mine: Reading = { again: false, version: null };
    reading.set(workflowId, mine);
    void reloadFromServer(workflowId).finally(() => {
        reading.delete(workflowId);
        if (mine.again) followCommit(workflowId, mine.version);
    });
}

/** Follows the account's change stream for `workflowId` while the canvas shows it: a commit to it, and a reset (the
 *  stream lost its place, so anything may have changed), each read again. */
export function useFollowCommits(workflowId: string): void {
    const live = useWorkLive();
    const id = useRef(workflowId);
    id.current = workflowId;
    useEffect(() => {
        const offChange = live.on('platform:resource', (frame) => {
            if (frame.kind === 'workflow' && frame.id === id.current) followCommit(id.current, typeof frame.version === 'number' ? frame.version : null);
        });
        const offReset = live.on('reset', () => followCommit(id.current, null));
        return () => {
            offChange();
            offReset();
        };
    }, [live]);
}
