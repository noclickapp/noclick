// Unit tests for resolveBodyDropConnection — the pure resolver behind FlowCanvas's
// drop-on-node-body edge snapping. Pins the natural-counterpart ranking (default
// dataflow input beats error/state handles, provider top ↔ agent bottom) and the
// distance fallback for multi-branch nodes, with validity delegated to the caller.

import { describe, it, expect } from 'vitest';
import type { Connection } from '@xyflow/react';
import {
    resolveBodyDropConnection,
    type DropHandleCandidate,
} from '~/components/workflow/edges/connectionDropSnap';

const allow = () => true;

function resolve(
    overrides: Partial<Parameters<typeof resolveBodyDropConnection>[0]> & {
        candidates: DropHandleCandidate[];
    }
) {
    return resolveBodyDropConnection({
        fromNodeId: 'a',
        fromNodeType: 'automation-slack',
        fromHandleId: null,
        fromHandleType: 'source',
        dropNodeId: 'b',
        dropPoint: { x: 50, y: 50 },
        isValidConnection: allow,
        ...overrides,
    });
}

describe('resolveBodyDropConnection', () => {
    it('connects a dataflow drag to the default input even when another handle is closer', () => {
        // Serverless-style drop node: left input (no id) far, 'state' handle near.
        const connection = resolve({
            candidates: [
                { id: null, x: 0, y: 50 },
                { id: 'state', x: 48, y: 60 },
            ],
        });
        expect(connection).toEqual({
            source: 'a',
            sourceHandle: null,
            target: 'b',
            targetHandle: null,
        });
    });

    it('connects a provider top drag to the agent bottom handle', () => {
        const connection = resolve({
            fromHandleId: 'top',
            candidates: [
                { id: 'left', x: 0, y: 50 },
                { id: 'bottom', x: 50, y: 100 },
            ],
            // Mirror the canvas rule: top-handle sources only reach 'bottom'.
            isValidConnection: (c: Connection) => c.targetHandle === 'bottom',
        });
        expect(connection?.targetHandle).toBe('bottom');
    });

    it('prefers the state handle for state-manager sources', () => {
        const connection = resolve({
            fromNodeType: 'state-manager',
            fromHandleId: 'output',
            candidates: [
                { id: null, x: 45, y: 50 },
                { id: 'state', x: 48, y: 96 },
            ],
        });
        expect(connection?.targetHandle).toBe('state');
    });

    it('resolves a backwards drag from an agent bottom handle to the provider top', () => {
        const connection = resolve({
            fromNodeType: 'agent',
            fromHandleId: 'bottom',
            fromHandleType: 'target',
            candidates: [
                { id: 'right', x: 96, y: 50 },
                { id: 'top', x: 50, y: 0 },
            ],
        });
        expect(connection).toEqual({
            source: 'b',
            sourceHandle: 'top',
            target: 'a',
            targetHandle: 'bottom',
        });
    });

    it('falls back to the closest valid handle when no natural handle exists', () => {
        // Backwards drag from an input onto a conditional node: neither branch is
        // "natural", so the drop half decides.
        const connection = resolve({
            fromHandleType: 'target',
            dropPoint: { x: 90, y: 80 },
            candidates: [
                { id: 'true', x: 96, y: 30 },
                { id: 'false', x: 96, y: 70 },
            ],
        });
        expect(connection?.sourceHandle).toBe('false');
    });

    it('falls back past an invalid natural handle to another valid one', () => {
        const connection = resolve({
            candidates: [
                { id: null, x: 0, y: 50 },
                { id: 'state', x: 48, y: 96 },
            ],
            isValidConnection: (c: Connection) => c.targetHandle === 'state',
        });
        expect(connection?.targetHandle).toBe('state');
    });

    it('returns null when nothing is valid or when dropping on the origin node', () => {
        expect(
            resolve({
                candidates: [{ id: null, x: 0, y: 50 }],
                isValidConnection: () => false,
            })
        ).toBeNull();
        expect(
            resolve({
                dropNodeId: 'a',
                candidates: [{ id: null, x: 0, y: 50 }],
            })
        ).toBeNull();
    });
});
