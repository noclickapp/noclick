// Walking the steps with the arrow keys (stepTraversal.ts).
import type { Node } from '@xyflow/react';
import { expect, it } from 'vitest';
import { selectOnly, stepInDirection } from './stepTraversal';

const at = (id: string, x: number, y: number, selected = false): Node => ({ id, position: { x, y }, data: {}, selected });
const STEPS = [at('hook', 0, 0), at('agent', 340, 0), at('tool', 340, 240), at('slack', 1040, -80)];
const walk = (from: string | null, arrow: 'ArrowRight' | 'ArrowLeft' | 'ArrowUp' | 'ArrowDown') =>
    stepInDirection(STEPS, STEPS.find((s) => s.id === from) ?? null, arrow)?.id ?? null;

it('starts at the top-left step, then takes the nearest one each way, sideways counted twice', () => {
    expect(walk(null, 'ArrowDown')).toBe('hook');
    expect(walk('hook', 'ArrowRight')).toBe('agent');
    expect(walk('agent', 'ArrowDown')).toBe('tool');
    expect(walk('tool', 'ArrowUp')).toBe('agent');
    expect(walk('agent', 'ArrowRight')).toBe('slack');
});

it('wraps round to the far edge when nothing is that way', () => {
    expect(walk('slack', 'ArrowRight')).toBe('hook');
    expect(walk('hook', 'ArrowLeft')).toBe('slack');
    expect(walk('tool', 'ArrowDown')).toBe('slack');
    expect(stepInDirection([at('only', 0, 0)], at('only', 0, 0), 'ArrowRight')).toBeNull();
    expect(stepInDirection([], null, 'ArrowRight')).toBeNull();
});

it('selects one step alone, keeping the others as they are where nothing changes', () => {
    const nodes = [at('a', 0, 0, true), at('b', 1, 0), at('c', 2, 0)];
    const after = selectOnly(nodes, 'b');
    expect(after.map((n) => !!n.selected)).toEqual([false, true, false]);
    expect(after[2]).toBe(nodes[2]);
});
