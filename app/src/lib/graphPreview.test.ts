import { describe, expect, it } from 'vitest';
import { buildGraphPreview } from './graphPreview';

describe('buildGraphPreview', () => {
    it('keeps what a preview draws of each step: its place, size and the states the canvas shows', () => {
        const preview = buildGraphPreview({
            nodes: [
                { id: 'a', type: 'agent', position: { x: 0, y: 10 }, width: '320px', config: { model: 'opencode', mockedOutput: { ok: true } } },
                { id: 's', type: 'stickyNote', position: { x: 300, y: 0 }, config: { color: 3, model: 'ignored', disabled: true } },
                { id: 'g', type: 'automation-gmail', position: { x: 600, y: 0 }, config: { model: 'not an agent', operation: 'send' } },
                { id: 'lost', type: 'automation-slack', position: { x: 'far' }, config: {} },
            ],
            edges: [],
        });
        expect(preview?.nodes).toEqual([
            { id: 'a', type: 'agent', x: 0, y: 10, width: 320, height: undefined, agentModel: 'opencode', stickyColor: undefined, disabled: undefined, mocked: true },
            { id: 's', type: 'stickyNote', x: 300, y: 0, width: undefined, height: undefined, agentModel: undefined, stickyColor: 3, disabled: true, mocked: undefined },
            { id: 'g', type: 'automation-gmail', x: 600, y: 0, width: undefined, height: undefined, agentModel: undefined, stickyColor: undefined, disabled: undefined, mocked: undefined },
        ]);
    });

    it('keeps the connections between steps it drew, older ends included, and none the canvas never draws', () => {
        const at = { x: 0, y: 0 };
        const preview = buildGraphPreview({
            nodes: [
                { id: 'when', type: 'trigger-schedule', position: at },
                { id: 'agent', type: 'agent', position: at },
                { id: 'mail', type: 'automation-gmail', position: at },
            ],
            edges: [
                { source: 'when', target: 'agent' },
                { sourceId: 'mail', targetId: 'agent', targetHandle: 'bottom' },
                // A trigger can't also be an agent's tool.
                { source: 'when', target: 'agent', targetHandle: 'bottom' },
                { source: 'agent', target: 'gone' },
            ],
        });
        expect(preview?.edges).toEqual([
            { source: 'when', target: 'agent', targetHandle: undefined },
            { source: 'mail', target: 'agent', targetHandle: 'bottom' },
        ]);
    });

    it('draws an empty graph as empty, and nothing for an entry that carries none', () => {
        expect(buildGraphPreview({ nodes: [] })).toEqual({ nodes: [], edges: [] });
        expect(buildGraphPreview(undefined)).toBeUndefined();
        expect(buildGraphPreview({ edges: [] })).toBeUndefined();
    });
});
