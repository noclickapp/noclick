// A canvas save as /v1 edits (`POST /v1/workflows/{id}/edits` with `source: canvas`): the graph the canvas holds,
// diffed against its per-step base (what the server holds, as far as the canvas knows), into the ops the TS SDK's
// `EditBatch` makes. Each step, connection and the Interface tab layout the canvas changed is a group of ops; nothing
// else is sent, so a save on a workflow that moved on lands only what this canvas changed, and an echo of what's stored
// is no edit at all. The server keeps a canvas's settings as written, so what lands is what a whole-graph save would
// have stored.
import type { EditBatch, JsonObject } from 'noclick';
import type { SerializedWorkflowEdge, SerializedWorkflowNode } from '@/screens/canvas/applyNodeUpdate';

/** Each step and connection as the server holds it (serialized as a save sends it), and the Interface tab layout. */
export interface GraphBase {
    nodes: Map<string, string>;
    edges: Map<string, string>;
    /** JSON of the layout as last loaded or saved; undefined when the canvas never knew it. */
    interface?: string | null;
}

/** What the canvas holds now, as a save sends it. */
export interface CanvasGraph {
    nodes: SerializedWorkflowNode[];
    edges: SerializedWorkflowEdge[];
    interface: unknown;
}

/** What a group of ops brings to the server: what the base holds of it once they land. */
export type Covers =
    | { kind: 'node'; id: string; json: string | null }
    | { kind: 'edge'; id: string; json: string | null }
    | { kind: 'interface'; json: string };

export interface OpGroup {
    covers: Covers[];
    /** Queues the group's ops on a batch. */
    queue: (batch: EditBatch) => void;
    /** How many ops it queues. */
    size: number;
}

// Config keys an op of their own carries (`set_connection`, `mock_step`/`unmock_step`); `operation` rides update_step's
// own field.
const OWN_OP_KEYS = new Set(['operation', 'credentialIds', 'mockedOutput']);
// The `_`-prefixed keys a person writes (the server's authored keys); every other one is set by the
// server on a run, and no write of a graph keeps it.
const AUTHORED_KEYS = new Set([
    '_settings',
    '_anchor_after',
    '_anchor_before',
    '_anchor_near',
    '_anchor_direction',
    '_anchor_width',
    '_anchor_height',
]);
const NOTE = 'stickyNote';
// An agent's tools edge, as the canvas draws it and the server names it.
const TOOLS_SOURCE = 'top';
const TOOLS_TARGET = 'bottom';
// What add_note gives a note when it names no colour.
const NOTE_DEFAULT_COLOR = 8;
// /v1 edits' own bounds (a move's and a note's).
const MAX_SIZE = 10000;
const MAX_COLOR = 20;

const json = (value: unknown) => JSON.stringify(value);

function isRuntimeKey(key: string): boolean {
    return key.startsWith('_') && !AUTHORED_KEYS.has(key);
}

/** A config's settings as an edit writes them: no key an op of its own carries, no runtime key. */
function settingsOf(config: Record<string, unknown>, also: ReadonlySet<string> = new Set()): Record<string, unknown> {
    return Object.fromEntries(
        Object.entries(config).filter(([key]) => !OWN_OP_KEYS.has(key) && !isRuntimeKey(key) && !also.has(key)),
    );
}

/** The settings that differ from `before` to `after`, a removed one as null (an edit's way of taking it out). */
function changedSettings(before: Record<string, unknown>, after: Record<string, unknown>): Record<string, unknown> {
    const changed: Record<string, unknown> = {};
    for (const key of new Set([...Object.keys(before), ...Object.keys(after)])) {
        if (json(before[key]) === json(after[key])) continue;
        changed[key] = key in after ? after[key] : null;
    }
    return changed;
}

/** A size /v1 takes (a positive number up to its bound), else undefined. */
function size(value: unknown): number | undefined {
    return typeof value === 'number' && Number.isFinite(value) && value > 0 && value <= MAX_SIZE ? value : undefined;
}

function connectionsOf(config: Record<string, unknown>): Record<string, string> {
    const held = config.credentialIds;
    if (!held || typeof held !== 'object') return {};
    return Object.fromEntries(
        Object.entries(held as Record<string, unknown>).filter(
            (entry): entry is [string, string] => typeof entry[1] === 'string' && entry[1].trim() !== '',
        ),
    );
}

/** The ops that bring the step's connections from `before`'s to `after`'s: each slot placed or taken off. */
function connectionOps(id: string, before: Record<string, unknown>, after: Record<string, unknown>) {
    const was = connectionsOf(before);
    const now = connectionsOf(after);
    const ops: Array<(batch: EditBatch) => void> = [];
    for (const slot of new Set([...Object.keys(was), ...Object.keys(now)])) {
        if (was[slot] === now[slot]) continue;
        const connection = now[slot] ?? null;
        ops.push((batch) => batch.setConnection(id, connection, { slot }));
    }
    return ops;
}

function mockOps(id: string, before: Record<string, unknown>, after: Record<string, unknown>) {
    if (json(before.mockedOutput) === json(after.mockedOutput)) return [];
    return [
        after.mockedOutput === undefined
            ? (batch: EditBatch) => batch.unmockStep(id)
            : (batch: EditBatch) => batch.mockStep(id, after.mockedOutput),
    ];
}

/** The ops that add a step the server doesn't hold, as the canvas holds it. */
function addOps(node: SerializedWorkflowNode): Array<(batch: EditBatch) => void> {
    const config = node.config ?? {};
    const width = size(node.width);
    const height = size(node.height);
    const ops: Array<(batch: EditBatch) => void> = [];
    if (node.type === NOTE) {
        const color = config.color;
        const named = typeof color === 'number' && Number.isInteger(color) && color >= 0 && color <= MAX_COLOR;
        const content = typeof config.content === 'string' ? config.content : '';
        ops.push((batch) => {
            batch.addNote(content, { id: node.id, position: node.position, ...(named ? { color } : {}) });
        });
        // What add_note made of it, then the rest of its settings as the canvas holds them.
        const made = { content, color: named ? color : NOTE_DEFAULT_COLOR };
        const rest = changedSettings(made, settingsOf(config));
        if (Object.keys(rest).length) ops.push((batch) => batch.updateStep(node.id, { settings: rest as JsonObject }));
    } else {
        const operation = typeof config.operation === 'string' && config.operation ? config.operation : undefined;
        const settings = settingsOf(config) as JsonObject;
        ops.push((batch) => {
            batch.addStep(node.type ?? '', { id: node.id, operation, settings, position: node.position });
        });
        ops.push(...connectionOps(node.id, {}, config));
        ops.push(...mockOps(node.id, {}, config));
    }
    if (width !== undefined || height !== undefined) {
        ops.push((batch) => batch.move(node.id, node.position, { width, height }));
    }
    return ops;
}

/** The ops that bring a step the server holds as `before` to the canvas's `after` (the same type). */
function changeOps(before: SerializedWorkflowNode, after: SerializedWorkflowNode): Array<(batch: EditBatch) => void> {
    const was = before.config ?? {};
    const now = after.config ?? {};
    const ops: Array<(batch: EditBatch) => void> = [];
    const operation =
        typeof now.operation === 'string' && now.operation && now.operation !== was.operation ? now.operation : undefined;
    const settings = changedSettings(settingsOf(was), settingsOf(now));
    if (operation || Object.keys(settings).length) {
        ops.push((batch) =>
            batch.updateStep(after.id, {
                ...(operation ? { operation } : {}),
                ...(Object.keys(settings).length ? { settings: settings as JsonObject } : {}),
            }),
        );
    }
    ops.push(...connectionOps(after.id, was, now));
    ops.push(...mockOps(after.id, was, now));
    const width = size(after.width);
    const height = size(after.height);
    const resized =
        (width !== undefined && json(before.width) !== json(after.width)) ||
        (height !== undefined && json(before.height) !== json(after.height));
    if (json(before.position) !== json(after.position) || resized) {
        ops.push((batch) =>
            batch.move(after.id, after.position, resized ? { width, height } : {}),
        );
    }
    return ops;
}

function connectOp(edge: SerializedWorkflowEdge): (batch: EditBatch) => void {
    const tools = edge.sourceHandle === TOOLS_SOURCE && edge.targetHandle === TOOLS_TARGET;
    return (batch) =>
        batch.connect(edge.source, edge.target, {
            kind: tools ? 'tools' : 'data',
            id: edge.id,
            ...(tools ? {} : { handle: edge.sourceHandle ?? undefined, targetHandle: edge.targetHandle ?? undefined }),
        });
}

function group(covers: Covers[], ops: Array<(batch: EditBatch) => void>): OpGroup {
    return { covers, size: ops.length, queue: (batch) => ops.forEach((op) => op(batch)) };
}

/**
 * The groups of ops that bring what the server holds (`base`) to what the canvas holds (`graph`), in the order they
 * apply: steps removed (their edges go with them), connections removed, steps added or changed, connections added,
 * then the Interface tab's layout. `skip`: steps the canvas holds only in part, which no op touches (the server keeps
 * them as stored).
 */
export function canvasEditGroups(base: GraphBase, graph: CanvasGraph, skip: ReadonlySet<string> = new Set()): OpGroup[] {
    const removed: OpGroup[] = [];
    const disconnected: OpGroup[] = [];
    const steps: OpGroup[] = [];
    const connected: OpGroup[] = [];
    const nodes = graph.nodes.filter((n) => !skip.has(n.id));
    const held = new Set(graph.nodes.map((n) => n.id));
    // Steps removed (or of another type now, so taken out and added again): their edges went with them.
    const gone = new Set<string>();

    for (const id of base.nodes.keys()) {
        if (!held.has(id)) gone.add(id);
    }
    for (const node of nodes) {
        const was = base.nodes.get(node.id);
        if (was === undefined) {
            steps.push(group([{ kind: 'node', id: node.id, json: json(node) }], addOps(node)));
            continue;
        }
        if (was === json(node)) continue;
        const before = JSON.parse(was) as SerializedWorkflowNode;
        if (before.type !== node.type) {
            gone.add(node.id);
            steps.push(group([{ kind: 'node', id: node.id, json: json(node) }], addOps(node)));
            continue;
        }
        const ops = changeOps(before, node);
        steps.push(group([{ kind: 'node', id: node.id, json: json(node) }], ops));
    }
    for (const id of gone) {
        const stillHeld = held.has(id);
        removed.push(
            group(stillHeld ? [] : [{ kind: 'node', id, json: null }], [(batch) => batch.removeStep(id)]),
        );
    }

    const reached = (id: string) => !skip.has(id) || base.nodes.has(id);
    const edges = graph.edges.filter((e) => reached(e.source) && reached(e.target));
    const now = new Map(edges.map((e) => [e.id, e]));
    for (const [id, was] of base.edges) {
        const edge = now.get(id);
        if (edge && json(edge) === was) continue;
        const before = JSON.parse(was) as SerializedWorkflowEdge;
        // An edge of a step removed above went with it.
        if (gone.has(before.source) || gone.has(before.target)) {
            if (!edge) disconnected.push(group([{ kind: 'edge', id, json: null }], []));
            continue;
        }
        disconnected.push(
            group(edge ? [] : [{ kind: 'edge', id, json: null }], [
                (batch) => batch.disconnect(before.source, before.target, { id }),
            ]),
        );
    }
    for (const edge of edges) {
        const was = base.edges.get(edge.id);
        const touchesGone = gone.has(edge.source) || gone.has(edge.target);
        if (was === json(edge) && !touchesGone) continue;
        connected.push(group([{ kind: 'edge', id: edge.id, json: json(edge) }], [connectOp(edge)]));
    }

    const groups = [...removed, ...disconnected, ...steps, ...connected];
    if (graph.interface != null && base.interface !== undefined && json(graph.interface) !== base.interface) {
        const layout = graph.interface as JsonObject;
        groups.push(group([{ kind: 'interface', json: json(layout) }], [(batch) => batch.updateWorkflow({ interface: layout })]));
    }
    return groups;
}

/** /v1 edits take at most this many ops in one batch. */
export const MAX_OPS = 200;

/** The groups split into batches /v1 takes, in order (a group's ops stay together). */
export function intoBatches(groups: OpGroup[]): OpGroup[][] {
    const batches: OpGroup[][] = [];
    let current: OpGroup[] = [];
    let ops = 0;
    for (const g of groups) {
        if (current.length && ops + g.size > MAX_OPS) {
            batches.push(current);
            current = [];
            ops = 0;
        }
        current.push(g);
        ops += g.size;
    }
    if (current.length) batches.push(current);
    return batches;
}

/** The base once `groups` landed: each step, connection and layout they bring as the canvas sent it. */
export function baseAfterGroups(base: GraphBase, groups: OpGroup[]): GraphBase {
    const next: GraphBase = { nodes: new Map(base.nodes), edges: new Map(base.edges), interface: base.interface };
    for (const g of groups) {
        for (const c of g.covers) {
            if (c.kind === 'interface') next.interface = c.json;
            else {
                const into = c.kind === 'node' ? next.nodes : next.edges;
                if (c.json === null) into.delete(c.id);
                else into.set(c.id, c.json);
            }
        }
    }
    return next;
}
