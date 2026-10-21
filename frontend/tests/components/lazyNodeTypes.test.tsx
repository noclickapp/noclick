// @vitest-environment jsdom
//
// A canvas node draws as its outline until its definition loads, and keeps its size when the real node replaces
// it. React Flow reads a node's handles only when it measures the node, so without a re-measure the edges of a
// node first drawn as an outline were never drawn (every edge between same-size nodes on a freshly opened canvas).
import type { NodeProps } from '@xyflow/react';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

const updateNodeInternals = vi.fn();
vi.mock('@xyflow/react', async (importOriginal) => ({
    ...(await importOriginal<typeof import('@xyflow/react')>()),
    useUpdateNodeInternals: () => updateNodeInternals,
}));
// The real node needs React Flow's store; what matters here is when the drawn node replaces the outline.
vi.mock('~/components/workflow/nodes/nodeTypeComponent', () => ({
    nodeTypeComponent: (definition: { type: string }) => () => <div data-testid="drawn">{definition.type}</div>,
}));

import { buildLazyNodeTypes } from '~/components/workflow/nodes/lazyNodeTypes';
import { loadNodeDefinitions } from '~/components/workflow/nodes/nodeDefinitions';

const props = (id: string) => ({ id }) as unknown as NodeProps;

afterEach(() => {
    cleanup();
    updateNodeInternals.mockClear();
});

describe('lazy canvas node types', () => {
    it('re-measures a node once its definition replaces the outline, so its edges draw', async () => {
        const Log = buildLazyNodeTypes().log;
        const { container } = render(<Log {...props('log_1')} />);
        expect(container.querySelector('[data-node-outline="log"]')).not.toBeNull();
        expect(updateNodeInternals).not.toHaveBeenCalled();

        await screen.findByTestId('drawn');
        await waitFor(() => expect(updateNodeInternals).toHaveBeenCalledWith('log_1'));
        expect(updateNodeInternals).toHaveBeenCalledTimes(1);
    }, 30_000);

    it('draws a node whose definition has loaded at once, with nothing to re-measure', async () => {
        await loadNodeDefinitions(['delay']);
        const Delay = buildLazyNodeTypes().delay;
        const { container } = render(<Delay {...props('delay_1')} />);
        expect(screen.getByTestId('drawn').textContent).toBe('delay');
        expect(container.querySelector('[data-node-outline]')).toBeNull();
        await new Promise((resolve) => setTimeout(resolve, 50));
        expect(updateNodeInternals).not.toHaveBeenCalled();
    }, 30_000);
});
