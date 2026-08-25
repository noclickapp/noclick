// @vitest-environment jsdom
//
// Diagnostic test for "Bug 2": on the live canvas, node.data.configValid stays
// undefined on every node — the incomplete-node badges never light up and the
// Guided Setup pill can't list per-node issues.
//
// This exercises useNodeConfigValidation in isolation. If it passes here, the
// hook's logic is sound and the production failure is environmental (something
// in FlowCanvas keeps the debounce from firing). If it fails, the hook itself
// is broken.

import { describe, expect, test, vi } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';
import type { Node } from '@xyflow/react';
import { useNodeConfigValidation } from '~/hooks/useNodeConfigValidation';

function makeNode(id: string, type: string, data: Record<string, unknown>): Node {
    return { id, type, position: { x: 0, y: 0 }, data } as Node;
}

// These fixtures run an `opencode` agent, and a CLI harness with no credential
// validates as incomplete on its own — which would confound tests about WHEN
// the hook writes configValid. Link one so the flag reflects field state only.
const AGENT_CRED = { agent_opencode: 'c1' };

describe('useNodeConfigValidation', () => {
    test('writes configValid onto every node after the debounce', async () => {
        let current: Node[] = [
            makeNode('a1', 'agent', { operation: 'default', config: { model: 'opencode', message: 'Hi' }, credentialIds: AGENT_CRED }),
            makeNode('a2', 'agent', { operation: 'default', config: { model: 'opencode' }, credentialIds: AGENT_CRED }),
        ];
        const setNodes = vi.fn((updater: (prev: Node[]) => Node[]) => {
            current = updater(current);
        });
        const isDraggingRef = { current: false };

        renderHook(() => useNodeConfigValidation({ nodes: current, setNodes, isDraggingRef }));

        await waitFor(() => expect(setNodes).toHaveBeenCalled(), { timeout: 1000 });

        expect(current.find((n) => n.id === 'a1')?.data?.configValid).toBe(true);
        expect(current.find((n) => n.id === 'a2')?.data?.configValid).toBe(false);
    });

    test('re-populates configValid after an external re-sync wipes it', async () => {
        // The real-world failure: validation runs once and sets configValid, then a
        // workflow:get round-trip / cache-restore replaces the node objects with
        // fresh backend state — and configValid (a runtime-only field) is gone.
        // The hook must notice the flag is missing and recompute it; its internal
        // cache must not make it believe the work is already done.
        const isDraggingRef = { current: false };
        let captured: Node[] = [
            makeNode('a1', 'agent', { operation: 'default', config: { model: 'opencode', message: 'Hi' }, credentialIds: AGENT_CRED }),
        ];
        const setNodes = vi.fn((updater: (prev: Node[]) => Node[]) => {
            captured = updater(captured);
        });

        const { rerender } = renderHook(
            (props: { nodes: Node[] }) =>
                useNodeConfigValidation({ nodes: props.nodes, setNodes, isDraggingRef }),
            { initialProps: { nodes: captured } },
        );

        // Pass 1 — hook validates and writes configValid.
        await waitFor(() => expect(captured[0].data?.configValid).toBe(true), { timeout: 1000 });

        // Feed the validated nodes back in (mirrors store → re-render); settle.
        rerender({ nodes: captured });
        await act(() => new Promise((r) => setTimeout(r, 200)));

        // External re-sync: brand-new node objects, configValid stripped.
        const resynced: Node[] = [
            makeNode('a1', 'agent', { operation: 'default', config: { model: 'opencode', message: 'Hi' }, credentialIds: AGENT_CRED }),
        ];
        captured = resynced;
        rerender({ nodes: resynced });

        // The hook must re-write configValid onto the fresh node.
        await waitFor(() => expect(captured[0].data?.configValid).toBe(true), { timeout: 1000 });
    });

    test('does not run while a drag is in progress', async () => {
        const current: Node[] = [
            makeNode('a1', 'agent', { operation: 'default', config: { model: 'opencode', message: 'Hi' }, credentialIds: AGENT_CRED }),
        ];
        const setNodes = vi.fn();
        const isDraggingRef = { current: true };

        renderHook(() => useNodeConfigValidation({ nodes: current, setNodes, isDraggingRef }));

        await new Promise((r) => setTimeout(r, 300));
        expect(setNodes).not.toHaveBeenCalled();
    });
});
