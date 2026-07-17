// Verifies FlowHelperView opens on a real node CLICK but stays shut through a
// node DRAG. Regression guard: xyflow selects a node ~1px into a drag, and the
// open used to hang off onSelectionChange, so dragging popped the panel open.
// The open now lives on onNodeClick; d3-drag suppresses the trailing click
// after any pointer movement (nodeClickDistance defaults to 0), which is the
// mechanism this test exercises.

import { nc } from '~/lib/nc';

const OPEN_SEL = '[data-flow-helper-scroll]';

const isOpen = () => !!document.querySelector(OPEN_SEL);

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

function centerOf(el: Element) {
    const r = el.getBoundingClientRect();
    return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
}

// ReactFlow drives node position through the element transform. The harness's
// getNodes() only exposes {id, type, data}, so the DOM is the position source —
// and it's the layer the user actually sees anyway.
const transformOf = (el: Element) => (el as HTMLElement).style.transform;

// A real drag: down -> move past the 1px threshold -> up, then the trailing
// click a browser dispatches when down/up share a target. d3-drag must swallow
// that click, which is exactly what keeps the panel shut.
async function dragBy(el: Element, dx: number, dy: number) {
    const a = centerOf(el);
    mouse(el, 'mousedown', a.x, a.y);
    mouse(window, 'mousemove', a.x + dx / 2, a.y + dy / 2);
    mouse(window, 'mousemove', a.x + dx, a.y + dy);
    mouse(window, 'mouseup', a.x + dx, a.y + dy);
    mouse(el, 'click', a.x + dx, a.y + dy);
    await nc.wait.ms(350);
}

async function closeHelper() {
    if (!isOpen()) return;
    const pane = document.querySelector('.react-flow__pane');
    if (!pane) throw new Error('no react-flow pane');
    // Click just inside the pane's own rect — it's inset by the sidebar and top
    // bar, so viewport (4,4) misses it entirely and the helper never closes.
    const r = pane.getBoundingClientRect();
    const x = r.left + 8;
    const y = r.top + 8;
    // onPaneClick -> closeFlowHelperOnDeselect
    mouse(pane, 'mousedown', x, y);
    mouse(pane, 'mouseup', x, y);
    mouse(pane, 'click', x, y);
    await nc.wait.until(() => !isOpen(), 3000).catch(() => {});
}

export default async function () {
    const el = document.querySelector('.react-flow__node');
    if (!el) throw new Error('no node on canvas to exercise');
    const startTransform = transformOf(el);

    await closeHelper();
    const openAtStart = isOpen();

    // ── DRAG
    await dragBy(el, 80, 60);
    const openAfterDrag = isOpen();
    const draggedTransform = transformOf(el);
    const didActuallyDrag = draggedTransform !== startTransform;
    // The drag must still SELECT the node — that's what fires onSelectionChange,
    // the exact signal the open used to hang off. Selected + panel shut is the
    // proof the fix is load-bearing rather than the drag simply missing.
    const selectedAfterDrag = el.classList.contains('selected');

    // Drag back so the test leaves the workflow where it found it.
    await dragBy(el, -80, -60);
    await closeHelper();

    // ── CLICK: no movement between down and up.
    const b = centerOf(el);
    mouse(el, 'mousedown', b.x, b.y);
    mouse(el, 'mouseup', b.x, b.y);
    mouse(el, 'click', b.x, b.y);
    await nc.wait.ms(350);
    const openAfterClick = isOpen();

    const endTransform = transformOf(el);

    nc.assert.falsy(openAtStart, 'helper should start closed');
    nc.assert.truthy(
        didActuallyDrag,
        'drag must actually move the node, else the drag case proves nothing'
    );
    nc.assert.truthy(
        selectedAfterDrag,
        'drag must still select the node (the old open-trigger) — otherwise the ' +
            'drag case passes for the wrong reason'
    );
    nc.assert.falsy(openAfterDrag, 'DRAG must NOT open FlowHelperView');
    nc.assert.truthy(openAfterClick, 'CLICK must open FlowHelperView');
    nc.assert.equal(
        endTransform,
        startTransform,
        'test should leave the node where it found it'
    );

    return {
        openAtStart,
        didActuallyDrag,
        selectedAfterDrag,
        openAfterDrag,
        openAfterClick,
    };
}
