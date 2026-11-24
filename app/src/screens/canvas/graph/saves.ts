// How the canvas's graph is saved and read again: what the `canvas.graph.saves` slot holds (declared in ../slots.ts,
// read by the graph store, liveGraphStore.ts, outside any component), and its standard. The store keeps one record per open workflow and does the saving itself:
// the debounce, one save at a time, its version, the per-step base a conflict's three-way merge reads, tombstones, a
// closing tab's last save. What it asks of whoever renders the canvas is this: which way a record saves, the host's own
// whole-graph save where it has one, the server's graph read again, and whether saves wait for now. The standard saves
// every record as the edits that changed it (`POST /v1/workflows/{id}/edits`) and reads `GET /v1/workflows/{id}/graph`,
// both through the client the canvas hands the store (`setCanvasEditsClient`). The SDK loads with the first read
// (../standardsSdk.ts).
import type { NoClick } from 'noclick';

/** How a record saves its graph: as the edits that changed it on `/v1` (`edits`), or whole through a host's own save
 *  over its socket (`socket`; NoClick's app has one, decided per workflow). Each record keeps the way it first saved. */
export type CanvasSaveTransport = 'socket' | 'edits';

/** The server's graph as a read or a conflict's answer carries it: steps and connections as a save sends them, and
 *  (on `/v1`) each step's withheld secrets by path. */
export interface ServerGraphData {
    nodes?: unknown[];
    edges?: unknown[];
    withheld?: unknown;
}

/** A save of the whole graph, as the store hands it to a host's own way of saving. */
export interface WholeGraphSave {
    workflowId: string;
    /** A skill's embedded workflow, which only the host's own save reaches. */
    isSkill: boolean;
    /** The graph as a save sends it: its steps, connections, the Interface tab's layout and, when any, its variables. */
    graph: Record<string, unknown>;
    /** The canvas's viewport and the like, which a skill's save carries. */
    displayMetadata: object | null;
    /** Steps the canvas removed whose removal hasn't landed yet. */
    deletedNodeIds: string[];
    /** Steps held only in part: the server keeps their settings as stored. */
    partialNodeIds: string[];
    /** The version the canvas holds, which the save is made on; null when none is known (it then lands as it is). */
    ifVersion: number | null;
    /** A closing tab's last save only: what it changed since its base, so a workflow that moved on takes only those. */
    changes?: { steps: string[]; edges_added: string[]; edges_removed: string[] };
}

/** A whole-graph save's answer: it landed (at the version it left, when known), it was refused for a stale version
 *  (with the graph and version as they stand, which the canvas merges and saves again on), or refused otherwise. */
export type WholeGraphAnswer =
    | { landed: true; version?: number }
    | { conflict: true; graph?: ServerGraphData; version: number | null }
    | { error: string };

/** A host's own whole-graph save. */
export interface WholeGraphSaves {
    /** Sends `save` and calls `answer` once with its answer; the returned function stops listening for it. */
    save: (save: WholeGraphSave, answer: (answer: WholeGraphAnswer) => void) => () => void;
    /** A closing tab's last save: sent at once, with nothing to wait for. */
    close: (save: WholeGraphSave) => void;
}

/** The server's graph read again: what it holds, its version and, where the read says so, what the reader may do with
 *  the workflow (`viewer`: only look), else why nothing was read. */
export type ServerGraphRead = { graph: ServerGraphData; version: number | null; access?: 'owner' | 'editor' | 'viewer' | null } | { graph: null; error?: string };

export interface GraphSaves {
    /** Which way a record saves, asked at its first save. */
    transportFor: (record: { workflowId: string; isSkill: boolean }) => CanvasSaveTransport;
    /** The host's own whole-graph save, for a record that saves `socket`; null where there is none. */
    socket: WholeGraphSaves | null;
    /** The server's graph read again (a save that never knew what the server holds, a step that couldn't be read
     *  whole), through `client` where the read is the API's. */
    read: (workflowId: string, client: NoClick | null) => Promise<ServerGraphRead>;
    /** True while another writer holds the graph (nothing saves until it's done). */
    paused: () => boolean;
}

/** The standard: every record saves through `/v1` edits, and the graph is read again from `/v1`. */
export const V1_GRAPH_SAVES: GraphSaves = {
    transportFor: () => 'edits',
    socket: null,
    read: async (workflowId, client) => {
        if (!client) return { graph: null, error: 'no client to read the workflow with (setCanvasEditsClient)' };
        const { Workflow } = await import('../standardsSdk');
        const graph = await Workflow.fromId(workflowId, { client }).graph();
        return { graph: graph.raw, version: graph.version, access: graph.access };
    },
    paused: () => false,
};
