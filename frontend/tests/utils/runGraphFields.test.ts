import { describe, expect, it } from 'vitest';
import { runGraphFields } from '~/utils/runGraphFields';

type Graph = Parameters<typeof runGraphFields>[1];

const executed = { nodes: [{ id: 'a' }], edges: [] } as unknown as Graph;
const replay = {
    nodes: [{ id: 'a' }, { id: 'b' }],
    edges: [{ source: 'a', target: 'b' }],
} as unknown as Graph;

describe('runGraphFields', () => {
    it("sends an editor's canvas graph, with the whole graph to replay", () => {
        expect(runGraphFields(true, executed, replay)).toEqual({
            nodes: executed.nodes,
            edges: executed.edges,
            replay_nodes: replay.nodes,
            replay_edges: replay.edges,
        });
    });

    it('sends no graph for a viewer, so the saved workflow runs', () => {
        expect(runGraphFields(false, executed, replay)).toEqual({});
    });
});
