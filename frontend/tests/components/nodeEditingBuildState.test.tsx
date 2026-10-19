// @vitest-environment jsdom
// A node card opens while a build works on it. The canvas's own builder marks it in the editor store; a build the
// canvas didn't start (the coordinator's, an MCP client's, one reattached after a reload) marks it in the node's data
// (`mcpAnimationState`, liveGraphStore / useMCPBuilderEvents). A preview says for itself, with `_previewEditInfo`.
import { cleanup, render, renderHook, screen } from '@testing-library/react';
import { ReactFlowProvider, type NodeProps } from '@xyflow/react';
import { Bot } from 'lucide-react';
import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { useNodeEditingState } from '~/components/workflow/nodes/base/nodeEditing';
import { clearAllNodeEditInfo, setEditingNodeIds, setIsAiEditing, setNodeEditInfo } from '~/components/workflow/WorkflowContext';

beforeAll(() => {
    window.matchMedia ??= (query: string) =>
        ({ matches: false, media: query, onchange: null, addListener: () => {}, removeListener: () => {}, addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false }) as MediaQueryList;
});
afterEach(() => {
    cleanup();
    setIsAiEditing(false);
    setEditingNodeIds(new Set());
    clearAllNodeEditInfo();
});

const state = (building: unknown, previewEditInfo?: null) => renderHook(() => useNodeEditingState('agent', { building, previewEditInfo })).result.current;

function card(data: Record<string, unknown>) {
    const props = { id: 'gmail-1', type: 'automation-gmail', data, selected: false } as unknown as NodeProps;
    return render(
        <ReactFlowProvider>
            <AutomationNode {...props} Icon={Bot} iconColor="text-foreground" />
        </ReactFlowProvider>
    );
}

describe('a node a build from elsewhere is working on', () => {
    it('opens while it’s being added or configured', () => {
        expect(state('adding')).toEqual({ isBeingEdited: true, editInfo: { status: 'processing', action: 'added' }, remoteEditorName: undefined });
        expect(state('editing')).toMatchObject({ isBeingEdited: true, editInfo: { status: 'processing', action: 'updated' } });
    });

    it('closes once it’s done, or when nothing is building it', () => {
        expect(state('complete').isBeingEdited).toBe(false);
        expect(state(undefined).isBeingEdited).toBe(false);
    });

    it('leaves a preview to say for itself', () => {
        expect(state('editing', null).isBeingEdited).toBe(false);
    });
});

describe('an integration card on the live canvas', () => {
    it('opens while the canvas’s own builder edits it', async () => {
        setIsAiEditing(true);
        setEditingNodeIds(new Set(['gmail-1']));
        setNodeEditInfo('gmail-1', { status: 'processing', action: 'updated', operation: 'send_email' });
        card({ config: {} });
        expect(await screen.findByText('Updating...')).toBeTruthy();
        expect(screen.getByText('send_email')).toBeTruthy();
    });

    it('opens while a build from elsewhere adds it', () => {
        card({ config: {}, mcpAnimationState: 'adding' });
        expect(screen.getByText('Adding...')).toBeTruthy();
    });

    it('stays shut in a preview that says it isn’t being edited, whatever the editor holds', async () => {
        setIsAiEditing(true);
        setEditingNodeIds(new Set(['gmail-1']));
        card({ config: {}, _previewEditInfo: null, isReadOnly: true });
        await new Promise((r) => setTimeout(r, 150));
        expect(screen.queryByText('Updating...')).toBeNull();
    });
});
