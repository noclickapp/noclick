// An agent's message hands the work to the agents it @-mentions; naming itself hands nothing on.
import { describe, expect, it } from 'vitest';
import { handoffsOf } from '~/components/shell/channels/model';
import type { ChannelMember } from '~/components/shell/channels/types';

const agent = (id: string, name: string): ChannelMember => ({ id: `mem_${id}`, kind: 'agent', name, agentId: id });
const scout = agent('agt_scout', 'Scout');
const quill = agent('agt_quill', 'Quill');
const members = [scout, quill];

describe('an agent’s hand-offs', () => {
    it('are the other agents it mentions', () => {
        expect(handoffsOf({ type: 'agent', id: 'agt_scout', name: 'Scout' }, ['Quill'], members)).toEqual([quill]);
    });

    it('leave out the agent itself, alone or beside another', () => {
        expect(handoffsOf({ type: 'agent', id: 'agt_scout', name: 'Scout' }, ['Scout'], members)).toEqual([]);
        expect(handoffsOf({ type: 'agent', id: 'agt_scout', name: 'Scout' }, ['Scout', 'Quill'], members)).toEqual([quill]);
        // An automation's agent is its member's id.
        const node: ChannelMember = { id: 'mem_wf', kind: 'agent', name: 'Digest', workflowId: 'wf', nodeId: 'n1' };
        expect(handoffsOf({ type: 'workflow_agent', id: 'mem_wf', name: 'Digest' }, ['Digest', 'Scout'], [...members, node])).toEqual([scout]);
    });

    it('are none for a person’s message', () => {
        expect(handoffsOf({ type: 'account', id: null, name: 'owner' }, ['Scout'], members)).toEqual([]);
    });
});
