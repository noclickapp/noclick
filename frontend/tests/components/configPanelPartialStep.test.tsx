// @vitest-environment jsdom
// A step a server write left the canvas holding only in part (a secret or an outsize setting the workflow's room
// held back, still being read whole) can't be edited: its panel shows it loading until it's whole, so no edit of
// the person's is saved over by the step as stored.
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createWorkflowNode } from '~/lib/applyNodeUpdate';

vi.mock('~/lib/analytics', () => ({ useAnalytics: () => ({ logActivity: vi.fn() }) }));
vi.mock('~/hooks/useNodeSchemas', () => ({ useNodeSchemas: () => true }));
vi.mock('~/components/workflow/NodeConfigLazy', () => ({ NodeConfig: () => <div>the step's settings</div> }));

import { ConfigTabContent } from '~/components/workflow/flowHelper/ConfigTabContent';
import { graphRecords, markStepPartial, recordGraphSnapshot, takeServerStep } from '~/lib/liveGraphStore';

const WF = 'wf-partial-panel';

afterEach(() => {
    cleanup();
    for (const k of Object.keys(graphRecords)) delete graphRecords[k];
});

function panel() {
    const node = createWorkflowNode('fetch', 'log', { x: 0, y: 0 }, { label: 'Fetch' });
    return (
        <ConfigTabContent
            selectedNode={node}
            workflowId={WF}
            nodeConfig={{}}
            credentialIds={{}}
            onSwitchToCredentials={() => undefined}
            onValidationChange={() => undefined}
            onConfigChange={() => undefined}
        />
    );
}

describe('the panel of a step held in part', () => {
    it('shows it loading until it is read whole', async () => {
        recordGraphSnapshot(WF, false, { nodes: [], edges: [] }, false);
        markStepPartial(WF, 'fetch');
        const { rerender } = render(panel());
        expect(screen.getByRole('status').textContent).toContain('Loading this step');
        expect(screen.queryByText('Label')).toBeNull();

        takeServerStep(WF, 'fetch', { label: 'Fetch', url: 'https://api.example' });
        await new Promise((resolve) => setTimeout(resolve, 0));
        rerender(panel());
        expect(screen.queryByRole('status')).toBeNull();
        expect(screen.getByText('Label')).toBeTruthy();
    });
});
