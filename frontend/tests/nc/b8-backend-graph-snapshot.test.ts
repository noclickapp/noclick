// B8 verification: getBackendGraphSnapshot() must return the live canvas graph
// (DB-shaped) when the store is a trustworthy source, so a builder resume hands
// the brain the agent's just-added nodes instead of the debounced/stale DB row.
// Runs in the real browser via the nc bridge — exercises the actual store +
// serializers, and (by importing the new export) confirms the FE change compiles.
import {
    getBackendGraphSnapshot,
    recordGraphSnapshot,
    setGraphLoaded,
    setCanvasMounted,
    graphRecords,
} from '~/lib/liveGraphStore';
import { createWorkflowNode } from '~/lib/applyNodeUpdate';

export default async function () {
    const wf = 'b8-test-' + Math.random().toString(36).slice(2);
    try {
        const node = createWorkflowNode(
            'n1', 'automation-google-sheets', { x: 0, y: 0 }, {}, { label: 'Sheets' },
        );
        recordGraphSnapshot(wf, false, { nodes: [node], edges: [] }, false);
        setGraphLoaded(wf, true);
        setCanvasMounted(wf, false, true);

        const snap = getBackendGraphSnapshot(wf);
        if (!snap) throw new Error('expected a snapshot when loaded + mounted');
        if (snap.workflow_id !== wf) throw new Error('workflow_id mismatch: ' + snap.workflow_id);
        if (!Array.isArray(snap.nodes) || snap.nodes.length !== 1) {
            throw new Error('expected 1 node, got ' + JSON.stringify(snap.nodes));
        }
        const n0 = snap.nodes[0] as { id?: string; type?: string };
        if (n0.id !== 'n1') throw new Error('node id not preserved: ' + JSON.stringify(n0));
        if (n0.type !== 'automation-google-sheets') throw new Error('node type not preserved');

        // Unmounted canvas => null, so the backend falls back to its DB read
        // rather than trusting a store that the agent's mutations bypass.
        setCanvasMounted(wf, false, false);
        if (getBackendGraphSnapshot(wf) !== null) {
            throw new Error('expected null when canvas unmounted');
        }

        // Unknown workflow => null.
        if (getBackendGraphSnapshot('no-such-wf') !== null) {
            throw new Error('expected null for unknown workflow');
        }

        return { ok: true, nodeId: n0.id, nodeKeys: Object.keys(n0) };
    } finally {
        delete (graphRecords as Record<string, unknown>)[wf];
    }
}
