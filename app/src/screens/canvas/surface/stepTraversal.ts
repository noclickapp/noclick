// Walking the canvas's steps with the arrow keys: the step an arrow selects next, the nearest one in its direction
// (sideways distance counted twice), wrapping round to the far edge when none is that way; with none selected yet, the
// top-left-most step.
import type { Node } from '@xyflow/react';

export type StepArrow = 'ArrowRight' | 'ArrowLeft' | 'ArrowUp' | 'ArrowDown';

export function isStepArrow(key: string): key is StepArrow {
    return key === 'ArrowRight' || key === 'ArrowLeft' || key === 'ArrowUp' || key === 'ArrowDown';
}

/** The step `arrow` moves to from `current` among `steps` (sticky notes left out by the caller); null with no steps. */
export function stepInDirection(steps: readonly Node[], current: Node | null, arrow: StepArrow): Node | null {
    if (steps.length === 0) return null;
    if (!current) return steps.reduce((a, b) => (b.position.x + b.position.y < a.position.x + a.position.y ? b : a));

    const { x: cx, y: cy } = current.position;
    let best = Infinity;
    let target: Node | null = null;
    for (const n of steps) {
        if (n.id === current.id) continue;
        const dx = n.position.x - cx;
        const dy = n.position.y - cy;
        let score = Infinity;
        if (arrow === 'ArrowRight' && dx > 0) score = dx + 2 * Math.abs(dy);
        else if (arrow === 'ArrowLeft' && dx < 0) score = -dx + 2 * Math.abs(dy);
        else if (arrow === 'ArrowDown' && dy > 0) score = dy + 2 * Math.abs(dx);
        else if (arrow === 'ArrowUp' && dy < 0) score = -dy + 2 * Math.abs(dx);
        if (score < best) {
            best = score;
            target = n;
        }
    }
    if (target) return target;

    // Nothing that way: the far edge on the other side, so walking cycles instead of stopping.
    const others = steps.filter((n) => n.id !== current.id);
    if (arrow === 'ArrowRight') return others.reduce((a, b) => (b.position.x < a.position.x ? b : a), others[0]) ?? null;
    if (arrow === 'ArrowLeft') return others.reduce((a, b) => (b.position.x > a.position.x ? b : a), others[0]) ?? null;
    if (arrow === 'ArrowDown') return others.reduce((a, b) => (b.position.y < a.position.y ? b : a), others[0]) ?? null;
    return others.reduce((a, b) => (b.position.y > a.position.y ? b : a), others[0]) ?? null;
}

/** Selects `targetId` alone, keeping every other step as it is where its selection doesn't change. */
export function selectOnly(nodes: Node[], targetId: string): Node[] {
    return nodes.map((n) => (n.selected === (n.id === targetId) ? n : { ...n, selected: n.id === targetId }));
}
