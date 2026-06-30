// @vitest-environment jsdom
//
// Regression: deleting a configured node and undoing must bring it back WITH its
// config (operation + credentials) intact. The bug was that captureState only
// refreshed `present` on a structural change (areStatesEqual compares id/position/
// type only), so config-only edits left `present` pointing at the node's blank
// add-time object — and the pre-delete snapshot wiped the user's config.

import { renderHook, act } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { Node, Edge } from '@xyflow/react';

import { useWorkflowUndoRedo } from '~/hooks/useWorkflowUndoRedo';

const node = (data: Record<string, any>): Node => ({
    id: 'stripe_1',
    type: 'automation-stripe',
    position: { x: 0, y: 0 },
    data,
});

function setup() {
    const restored: { nodes: Node[] } = { nodes: [] };
    const hook = renderHook(() =>
        useWorkflowUndoRedo([], [] as Edge[], {
            onNodesChange: (n) => { restored.nodes = n; },
            onEdgesChange: () => {},
        }),
    );
    return { hook, restored };
}

describe('useWorkflowUndoRedo — config survives delete + undo', () => {
    it('restores operation + credentials after deleting and undoing', () => {
        const { hook, restored } = setup();
        const empty = node({ credentialIds: {} });
        const configured = node({
            operation: 'on_charge_succeeded',
            credentialIds: { stripe_api_key: 'cred-123' },
            config: { operation: 'on_charge_succeeded' },
        });

        act(() => {
            hook.result.current.captureState([empty], []);        // node added (blank)
            hook.result.current.captureState([configured], []);   // configured (same id/pos/type)
            hook.result.current.captureState([], []);             // deleted
        });

        act(() => hook.result.current.undo());

        expect(restored.nodes).toHaveLength(1);
        expect(restored.nodes[0].data.operation).toBe('on_charge_succeeded');
        expect(restored.nodes[0].data.credentialIds).toEqual({ stripe_api_key: 'cred-123' });
    });

    it('does not create extra history entries for config-only edits', () => {
        const { hook } = setup();
        act(() => {
            hook.result.current.captureState([node({ credentialIds: {} })], []);
            hook.result.current.captureState([node({ operation: 'a' })], []);  // config-only
            hook.result.current.captureState([node({ operation: 'b' })], []);  // config-only
        });
        // Only the initial add is an undoable entry; config edits don't add steps.
        expect(hook.result.current.canUndo).toBe(true);
        act(() => hook.result.current.undo());
        // After one undo we're back to empty history (the add was the only entry).
        expect(hook.result.current.canUndo).toBe(false);
    });
});
