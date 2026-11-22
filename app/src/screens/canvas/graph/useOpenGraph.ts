// Opening a workflow on the canvas: its record in the graph store told the canvas is drawing it, the graph read as the
// `canvas.graph.saves` slot reads it (the standard: `GET /v1/workflows/{id}/graph`) and taken as what the server holds,
// so opening it writes nothing; and when the canvas goes, the record told so after its last edits are sent. A record
// still holding the graph from an earlier visit (the store outlives the canvas) keeps it, edits not yet saved included,
// and is brought up to date as a commit heard is (followCommits.ts).
import { useEffect, useState } from 'react';
import { followCommit } from './followCommits';
import {
    flushGraphNow,
    graphRecords,
    recordDeletedNodes,
    reloadFromServer,
    seedSaveBaseline,
    setCanvasMounted,
    setGraphLoaded,
    setGraphVersion,
} from './liveGraphStore';

export type OpenGraph = { state: 'opening' } | { state: 'open' } | { state: 'failed'; message: string };

/** Opens `workflowId` while the canvas draws it (the module's header); `deleted` holds the steps the canvas removed that
 *  the store hasn't been told of yet, told before it closes. */
export function useOpenGraph(workflowId: string, deleted: { current: Set<string> }): OpenGraph {
    const [open, setOpen] = useState<OpenGraph>(() => (graphRecords[workflowId]?.loaded ? { state: 'open' } : { state: 'opening' }));

    useEffect(() => {
        let live = true;
        const known = graphRecords[workflowId]?.loaded;
        setCanvasMounted(workflowId, false, true);
        if (known) {
            setOpen({ state: 'open' });
            followCommit(workflowId, null);
        } else {
            setOpen({ state: 'opening' });
            void reloadFromServer(workflowId).then((read) => {
                if (!live) return;
                if (!read) {
                    setOpen({ state: 'failed', message: 'The workflow couldn’t be read. Check the key can read workflows, then open it again.' });
                    return;
                }
                // A whole read: the server's graph as it stands is the base, nothing held back, nothing to save.
                setGraphVersion(workflowId, graphRecords[workflowId]?.graphVersion ?? null);
                seedSaveBaseline(workflowId);
                setGraphLoaded(workflowId, true);
                setOpen({ state: 'open' });
            });
        }
        return () => {
            live = false;
            const removed = [...deleted.current];
            deleted.current.clear();
            if (removed.length) recordDeletedNodes(workflowId, removed);
            flushGraphNow(workflowId);
            setCanvasMounted(workflowId, false, false);
        };
    }, [workflowId, deleted]);

    return open;
}
