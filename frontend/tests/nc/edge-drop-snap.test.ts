// Live regression for drop-on-node-body edge snapping (FlowCanvas onConnectEnd +
// resolveBodyDropConnection): simulates a real mouse drag from a node's source
// handle released over another node's BODY (far from any handle dot) and asserts
// the edge auto-connects to the resolved input handle. Cleans up by deleting the
// created edge through the real UI path (edge click → Backspace) so the graph —
// including the persisted save — ends exactly where it started.

import { nc } from '~/lib/nc';

interface EdgeInfo {
    id: string;
    source: string;
    target: string;
    sourceHandle?: string | null;
    targetHandle?: string | null;
}

const getEdges = () => nc.nodes.edges() as unknown as EdgeInfo[];

export default async function () {
    const nodes = nc.nodes.list() as Array<{ id: string; type?: string }>;
    const edgesBefore = getEdges();
    if (nodes.length < 2) {
        throw new Error('Open a workflow with at least 2 nodes on the canvas');
    }

    // Find a (source, target) pair a body drop should connect: source exposes a
    // plain dataflow source handle (not the provider top dot) and isn't already
    // provider-wired; target renders an input handle, isn't an MCP host, and the
    // edge doesn't exist yet.
    const SKIP_TYPES = new Set(['interface-html-react', 'stickyNote']);
    let pick: {
        sourceId: string;
        handleEl: Element;
        targetId: string;
        targetEl: Element;
    } | null = null;
    for (const s of nodes) {
        if (SKIP_TYPES.has(s.type ?? '')) continue;
        const handleEl = document.querySelector(
            `.react-flow__node[data-id="${s.id}"] .react-flow__handle.source:not([data-handleid="top"]):not([data-handleid="error"])`
        );
        if (!handleEl) continue;
        if (
            edgesBefore.some(
                (e) => e.source === s.id && e.sourceHandle === 'top'
            )
        ) {
            continue;
        }
        for (const t of nodes) {
            if (t.id === s.id) continue;
            if (SKIP_TYPES.has(t.type ?? '') || t.type === 'mcp-server') {
                continue;
            }
            if (
                edgesBefore.some((e) => e.source === s.id && e.target === t.id)
            ) {
                continue;
            }
            const targetEl = document.querySelector(
                `.react-flow__node[data-id="${t.id}"]`
            );
            if (!targetEl?.querySelector('.react-flow__handle.target')) {
                continue;
            }
            pick = { sourceId: s.id, handleEl, targetId: t.id, targetEl };
            break;
        }
        if (pick) break;
    }
    if (!pick) {
        throw new Error('No connectable node pair found on this canvas');
    }
    const { sourceId, handleEl, targetId, targetEl } = pick;

    // Drag: mousedown on the source handle dot → mousemove → mouseup on the
    // target node's BODY center (xyflow listens for mouse events on document;
    // the mouseup's event.target is what the snap handler resolves).
    const hr = handleEl.getBoundingClientRect();
    const tr = targetEl.getBoundingClientRect();
    const sx = hr.x + hr.width / 2;
    const sy = hr.y + hr.height / 2;
    const tx = tr.x + tr.width / 2;
    const ty = tr.y + tr.height / 2;
    const opts = (x: number, y: number): MouseEventInit => ({
        bubbles: true,
        cancelable: true,
        clientX: x,
        clientY: y,
        button: 0,
        view: window,
    });
    handleEl.dispatchEvent(new MouseEvent('mousedown', opts(sx, sy)));
    document.dispatchEvent(
        new MouseEvent('mousemove', opts((sx + tx) / 2, (sy + ty) / 2))
    );
    document.dispatchEvent(new MouseEvent('mousemove', opts(tx, ty)));
    targetEl.dispatchEvent(new MouseEvent('mouseup', opts(tx, ty)));

    await nc.wait.until(
        () =>
            getEdges().some(
                (e) => e.source === sourceId && e.target === targetId
            ),
        5000
    );
    const created = getEdges().find(
        (e) => e.source === sourceId && e.target === targetId
    )!;
    nc.assert.equal(
        getEdges().length,
        edgesBefore.length + 1,
        'Body drop should create exactly one edge'
    );

    // Cleanup through the real path: select the edge, delete via Backspace
    // (xyflow's default deleteKeyCode) so removal broadcasts + persists.
    // d3-drag suppresses the first click right after a drag gesture, so wait a
    // beat before clicking, then REQUIRE a provably safe selection (exactly the
    // created edge, zero nodes) before dispatching Backspace — xyflow's delete
    // key removes ALL selected elements, and a lingering node selection here
    // once deleted a real node instead of the test edge.
    await nc.wait.ms(100);
    const edgeEl = document.querySelector(
        `.react-flow__edge[data-id="${created.id}"]`
    );
    if (!edgeEl) {
        throw new Error(
            `Created edge ${created.id} not found in DOM — remove it manually`
        );
    }
    edgeEl.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    try {
        await nc.wait.until(() => {
            const selEdges = document.querySelectorAll(
                '.react-flow__edge.selected'
            );
            const selNodes = document.querySelectorAll(
                '.react-flow__node.selected'
            );
            return (
                selNodes.length === 0 &&
                selEdges.length === 1 &&
                selEdges[0].getAttribute('data-id') === created.id
            );
        }, 3000);
    } catch {
        throw new Error(
            `Edge created but selection is not safe for keyboard delete — remove edge ${created.id} manually`
        );
    }
    document.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'Backspace', bubbles: true })
    );
    await nc.wait.until(
        () => !getEdges().some((e) => e.id === created.id),
        5000
    );
    nc.assert.equal(
        nc.nodes.count(),
        nodes.length,
        'Cleanup must not remove any node'
    );
    nc.assert.equal(
        getEdges().length,
        edgesBefore.length,
        'Edge set should be back to baseline after cleanup'
    );

    return {
        draggedFrom: `${sourceId} (handle: ${created.sourceHandle ?? 'default'})`,
        droppedOnBodyOf: targetId,
        resolvedTargetHandle: created.targetHandle ?? 'default input',
        cleanedUp: true,
    };
}
