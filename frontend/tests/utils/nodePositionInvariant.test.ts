// hasValidPosition / ensureNodePosition — the canvas position invariant.
// A single position-less node entering canvas state broke deletion and undo
// for a whole session (2026-08-04); these helpers heal at the boundary and
// report the minting path.
import { describe, expect, it, vi } from 'vitest';
import type { Node } from '@xyflow/react';

vi.mock('~/lib/telemetry-errors', () => ({ reportInvariant: vi.fn() }));

import { ensureNodePosition, hasValidPosition } from '~/lib/applyNodeUpdate';
import { reportInvariant } from '~/lib/telemetry-errors';

describe('hasValidPosition', () => {
    it('accepts finite positions and rejects everything else', () => {
        expect(hasValidPosition({ position: { x: 0, y: 0 } })).toBe(true);
        expect(hasValidPosition({ position: { x: -12.5, y: 400 } })).toBe(true);
        expect(hasValidPosition({} as Node)).toBe(false);
        expect(hasValidPosition({ position: undefined })).toBe(false);
        expect(hasValidPosition({ position: { x: NaN, y: 2 } })).toBe(false);
        expect(hasValidPosition({ position: { x: 1 } } as unknown as Node)).toBe(false);
        expect(hasValidPosition(null)).toBe(false);
    });
});

describe('ensureNodePosition', () => {
    it('passes valid nodes through untouched and unreported', () => {
        const node = { id: 'a', type: 'agent', position: { x: 3, y: 4 }, data: {} } as Node;
        expect(ensureNodePosition(node, 'test')).toBe(node);
        expect(reportInvariant).not.toHaveBeenCalled();
    });

    it('heals positionless nodes to origin and reports the source', () => {
        const bad = { id: 'ghost', type: 'agent', data: {} } as unknown as Node;
        const healed = ensureNodePosition(bad, 'collab node:add');
        expect(healed.position).toEqual({ x: 0, y: 0 });
        expect(reportInvariant).toHaveBeenCalledWith(
            expect.stringContaining('collab node:add'),
            expect.any(String)
        );
    });
});
