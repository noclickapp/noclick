// How a read-only canvas shows what the builder changed between two reads of a graph: each node it added or changed
// opens into the editing card the live canvas shows while the builder works on a node (nodes/base/nodeEditing), holds
// a moment, then closes on its new content. That opening is spatial motion, so where motion is reduced the cards keep
// their size and the change fades in instead.
import { useEffect, useState, type RefObject } from 'react';
import type { NodeEditInfo } from '~/components/workflow/WorkflowContext';
import type { ScaffoldBlob } from '~/lib/agentScaffold';

export type PreviewEdits = Record<string, NodeEditInfo>;

// How long a changed card stays open: past its 300ms opening, long enough to read what changed.
export const EDIT_HOLD_MS = 1600;
const NONE: PreviewEdits = {};

/** What changed from one read of a graph to the next, as the builder's edits: each node added, and each node whose
 *  type or config changed, with the fields that did. Positions are layout, not edits; a node removed simply goes, as
 *  it does on the live canvas. */
export function graphEdits(prev: ScaffoldBlob, next: ScaffoldBlob): PreviewEdits {
    const before = new Map(prev.nodes.map((node) => [node.id, node]));
    const edits: PreviewEdits = {};
    for (const node of next.nodes) {
        const config = node.config ?? {};
        const operation = typeof config.operation === 'string' ? config.operation : undefined;
        const was = before.get(node.id);
        if (!was) {
            edits[node.id] = { status: 'complete', action: 'added', operation };
            continue;
        }
        const old = was.config ?? {};
        const changed = [...new Set([...Object.keys(old), ...Object.keys(config)])].filter((key) => JSON.stringify(old[key]) !== JSON.stringify(config[key]));
        if (changed.length || was.type !== node.type) {
            edits[node.id] = { status: 'complete', action: 'updated', operation, config: Object.fromEntries(changed.map((key) => [key, config[key] ?? null])) };
        }
    }
    return edits;
}

/** Whether motion gives way to fades at `el`: a lab's Full/Reduced switch above it (`data-motion`) decides, else the
 *  OS setting. */
export function reducedMotionAt(el: Element | null): boolean {
    const forced = el?.closest('[data-motion]')?.getAttribute('data-motion');
    if (forced) return forced === 'reduced';
    return typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true;
}

/** Fades the nodes `ids` in where `frame` draws them (a React Flow canvas or the phone's ForkCanvas). */
export function fadeNodesIn(frame: Element | null, ids: string[]): void {
    const wanted = new Set(ids);
    frame?.querySelectorAll<HTMLElement>('.react-flow__node, [data-node-id]').forEach((el) => {
        if (wanted.has(el.dataset.id ?? el.dataset.nodeId ?? '')) el.animate([{ opacity: 0.2 }, { opacity: 1 }], { duration: 600, easing: 'ease-out' });
    });
}

/** The edits a read-only canvas of `blob` shows now: the nodes the latest read added or changed, held open for
 *  EDIT_HOLD_MS. The first read is where the canvas starts, so nothing on it reads as edited; with motion reduced, the
 *  changed nodes in `frame` fade in and none open. Off (`enabled` false), it shows none. */
export function usePreviewEdits(blob: ScaffoldBlob, frame: RefObject<Element | null>, enabled: boolean): PreviewEdits {
    const [seen, setSeen] = useState(blob);
    const [moment, setMoment] = useState({ edits: NONE, reduced: false });
    if (seen !== blob) {
        setSeen(blob);
        setMoment({ edits: enabled ? graphEdits(seen, blob) : NONE, reduced: reducedMotionAt(frame.current) });
    }
    useEffect(() => {
        const ids = Object.keys(moment.edits);
        if (!ids.length) return;
        // A node the read added is in the DOM a moment after its canvas takes the new graph.
        const timer = moment.reduced
            ? window.setTimeout(() => fadeNodesIn(frame.current, ids), 50)
            : window.setTimeout(() => setMoment((now) => (now === moment ? { edits: NONE, reduced: false } : now)), EDIT_HOLD_MS);
        return () => window.clearTimeout(timer);
    }, [moment, frame]);
    return moment.reduced ? NONE : moment.edits;
}
