// Exercises the agent tool drop: dropping palette nodes onto an agent wires them
// in as tool providers. Guards the placement rules a plain "wire it up" misses —
// the second tool must fan out instead of stacking on the first, and each tool
// must sit centred on the agent rather than corner-aligned.
//
// Drives real dnd-kit pointer drags from the Nodes-tab palette, since the point
// is dnd-kit's collision detection picking the right droppable.

import { nc } from '~/lib/nc';

const AGENT_ID = 'agent_1zhz';

interface EdgeLike {
    source: string;
    target: string;
    sourceHandle?: string | null;
    targetHandle?: string | null;
}

const harness = () => (window as any).__workflowTest;
const getNodes = (): Array<{ id: string; type: string }> => harness().getNodes();
const getEdges = (): EdgeLike[] => harness().getEdges();

function pointer(target: EventTarget, type: string, x: number, y: number) {
    target.dispatchEvent(
        new PointerEvent(type, {
            bubbles: true,
            cancelable: true,
            view: window,
            clientX: x,
            clientY: y,
            button: 0,
            buttons: type === 'pointerup' ? 0 : 1,
            pointerId: 1,
            pointerType: 'mouse',
            isPrimary: true,
        })
    );
}

function mouse(target: EventTarget, type: string, x: number, y: number) {
    target.dispatchEvent(
        new MouseEvent(type, {
            bubbles: true,
            cancelable: true,
            view: window,
            clientX: x,
            clientY: y,
            button: 0,
        })
    );
}

const centerOf = (el: Element) => {
    const r = el.getBoundingClientRect();
    return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
};

/** Flow-space box of a rendered node, read off ReactFlow's transform. */
function boxOf(id: string) {
    const el = document.querySelector(`[data-id="${id}"]`) as HTMLElement | null;
    if (!el) throw new Error(`node ${id} not rendered`);
    const m = /translate\(([-\d.]+)px,\s*([-\d.]+)px\)/.exec(el.style.transform);
    if (!m) throw new Error(`node ${id} has no transform`);
    return {
        x: +m[1],
        y: +m[2],
        width: el.offsetWidth,
        height: el.offsetHeight,
    };
}

async function openPalette(query: string) {
    const el = document.querySelector(`[data-id="${AGENT_ID}"]`);
    if (!el) throw new Error('agent node missing');
    const c = centerOf(el);
    mouse(el, 'mousedown', c.x, c.y);
    mouse(el, 'mouseup', c.x, c.y);
    mouse(el, 'click', c.x, c.y);
    await nc.wait.ms(600);
    const tab = [...document.querySelectorAll('button')].find(
        (b) => (b.textContent || '').trim() === 'Nodes'
    );
    if (!tab) throw new Error('no Nodes tab');
    (tab as HTMLElement).click();
    await nc.wait.until(
        () =>
            document.querySelectorAll('[aria-roledescription="draggable"]')
                .length > 0,
        5000
    );
    const input = [...document.querySelectorAll('input')].find(
        (i) => i.placeholder === 'Search nodes...'
    );
    if (!input) throw new Error('no palette search input');
    nc.dom.type(input, query);
    await nc.wait.ms(600);
}

function paletteDraggable(label: string): Element {
    const tile = [...document.querySelectorAll('[role="button"]')].find((e) =>
        (e.textContent || '').toLowerCase().includes(label.toLowerCase())
    );
    if (!tile) throw new Error(`no palette tile for "${label}"`);
    const el = tile.querySelector('[aria-roledescription="draggable"]');
    if (!el) throw new Error(`tile for "${label}" has no draggable`);
    return el;
}

async function dropOnAgent(label: string) {
    await openPalette(label);
    const src = paletteDraggable(label);
    const from = centerOf(src);
    const to = centerOf(document.querySelector(`[data-id="${AGENT_ID}"]`)!);
    pointer(src, 'pointerdown', from.x, from.y);
    await nc.wait.ms(60);
    pointer(document, 'pointermove', from.x + 8, from.y + 8);
    await nc.wait.ms(60);
    pointer(document, 'pointermove', to.x, to.y);
    await nc.wait.ms(150);
    pointer(document, 'pointermove', to.x, to.y);
    await nc.wait.ms(120);
    pointer(document, 'pointerup', to.x, to.y);
    await nc.wait.ms(900);
}

export default async function () {
    const before = getNodes().map((n) => n.id);
    const added: string[] = [];
    const results: Record<string, unknown> = {};

    try {
        // Four tools, matching the lopsided-row report: each addition must
        // re-centre the whole row under the agent, not march off to the right.
        for (const label of ['Stripe', 'Supabase', 'Cloudflare', 'Apify']) {
            const seen = getNodes().map((n) => n.id);
            await dropOnAgent(label);
            const fresh = getNodes().filter((n) => !seen.includes(n.id));
            nc.assert.equal(fresh.length, 1, `${label} drop should add one node`);
            added.push(...fresh.map((n) => n.id));
        }

        const agent = boxOf(AGENT_ID);
        const boxes = added.map(boxOf).sort((p, q) => p.x - q.x);

        // Only count edges from the nodes THIS run added — a canvas with other
        // tools already wired would otherwise fail on their edges.
        const toolEdges = getEdges().filter(
            (e) =>
                e.target === AGENT_ID &&
                e.sourceHandle === 'top' &&
                e.targetHandle === 'bottom' &&
                added.includes(e.source)
        );

        // No two tools may overlap.
        let overlap = false;
        for (let i = 1; i < boxes.length; i++) {
            if (boxes[i].x < boxes[i - 1].x + boxes[i - 1].width) overlap = true;
        }

        // The ROW as a whole must be centred on the agent.
        const agentCx = agent.x + agent.width / 2;
        const rowLeft = boxes[0].x;
        const rowRight = boxes[boxes.length - 1].x + boxes[boxes.length - 1].width;
        const rowCx = (rowLeft + rowRight) / 2;

        results.agentCentreX = Math.round(agentCx);
        results.rowCentreX = Math.round(rowCx);
        results.rowCentreOffset = Math.round(rowCx - agentCx);
        results.toolEdgeCount = toolEdges.length;
        results.overlap = overlap;
        results.toolXs = boxes.map((b) => Math.round(b.x));
        results.gaps = boxes
            .slice(1)
            .map((b, i) => Math.round(b.x - (boxes[i].x + boxes[i].width)));

        nc.assert.equal(toolEdges.length, 4, 'all four drops must wire as tools');
        nc.assert.falsy(overlap, 'tools must not overlap');
        nc.assert.truthy(
            Math.abs(rowCx - agentCx) <= 1,
            `the tool row should stay centred under the agent (off by ${Math.round(rowCx - agentCx)}px)`
        );
    } finally {
        for (const id of added) nc.nodes.deleteViaUI(id);
        await nc.wait.ms(600);
    }

    results.finalNodes = getNodes().map((n) => n.id);
    return results;
}
