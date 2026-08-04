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

// Regression (2026-07-30 graph-wipe incident): the hook mounts with an empty
// canvas, so without re-anchoring at the loaded graph, that empty state sits
// at the bottom of the undo stack — repeated Cmd+Z walks a loaded workflow
// down to zero nodes, and the autosave persists the wipe.
describe('useWorkflowUndoRedo — resetBaseline floors the stack at the loaded graph', () => {
    it('undo cannot walk below the baseline set after workflow load', () => {
        const { hook, restored } = setup();
        const loaded = node({ operation: 'on_charge_succeeded' });

        act(() => {
            // Pre-load churn (cache restore etc.) lands in history…
            hook.result.current.captureState([loaded], []);
            // …then the authoritative load re-anchors: no past, no future.
            hook.result.current.resetBaseline([loaded], []);
        });
        expect(hook.result.current.canUndo).toBe(false);
        expect(hook.result.current.canRedo).toBe(false);

        // A real post-load edit is still undoable — but only back to the
        // loaded graph, never to the empty pre-load state.
        act(() => hook.result.current.captureState([], []));
        act(() => hook.result.current.undo());
        expect(restored.nodes).toHaveLength(1);
        expect(hook.result.current.canUndo).toBe(false);
    });

    it('Cmd+Z while typing in an input/textarea/contentEditable does not touch the canvas', () => {
        const { hook, restored } = setup();
        const loaded = node({});
        act(() => {
            hook.result.current.resetBaseline([loaded], []);
            hook.result.current.captureState([], []); // deletable edit → canUndo
        });
        const marker = { nodes: 'untouched' };
        restored.nodes = marker.nodes as never;

        for (const make of [
            () => document.createElement('input'),
            () => document.createElement('textarea'),
            () => {
                const div = document.createElement('div');
                div.setAttribute('contenteditable', 'true');
                return div;
            },
        ]) {
            const el = make();
            document.body.appendChild(el);
            act(() => {
                el.dispatchEvent(
                    new KeyboardEvent('keydown', {
                        key: 'z',
                        metaKey: true,
                        ctrlKey: true,
                        bubbles: true,
                    }),
                );
            });
            el.remove();
        }
        // No undo fired: onNodesChange never ran.
        expect(restored.nodes).toBe(marker.nodes);
        expect(hook.result.current.canUndo).toBe(true);

        // Sanity: the same keystroke on the document body DOES undo.
        act(() => {
            document.body.dispatchEvent(
                new KeyboardEvent('keydown', {
                    key: 'z',
                    metaKey: true,
                    ctrlKey: true,
                    bubbles: true,
                }),
            );
        });
        expect(restored.nodes).toHaveLength(1);
    });
});

// A position-less node in canvas state (the 2026-08-04 incident: one bad node
// crashed every state-capture comparison for the whole session) must compare
// safely instead of throwing.
describe('positionless node resilience', () => {
    it('captures history without throwing when a node lacks position', () => {
        const { hook } = setup();
        const bad = { id: 'ghost', type: 'agent', data: {} } as unknown as Node;
        const good = { id: 'n1', type: 'agent', position: { x: 1, y: 2 }, data: {} } as Node;
        expect(() => {
            act(() => {
                hook.result.current.captureState([good, bad], []);
                hook.result.current.captureState([good, bad], []); // equal-state compare path
                hook.result.current.captureState(
                    [good, { ...bad, position: { x: 3, y: 4 } } as Node], []
                );
            });
        }).not.toThrow();
    });
});
