// A conversation's loops for its Beside (Work's conversations and the Chat page): those running, and those that
// stopped themselves. Read again when the backend says one moved (its `platform:agent` `wakeups` frames) or the agent
// took a turn, never on a timer.
import { useMemo } from 'react';
import { Agent } from 'noclick';
import { invalidateV1 } from '@/sdk/useV1';
import { useWorkV1 } from '../agents/reads';
import { useWorkFrames } from '@/sdk/live';
import { isLoop, loopItem, type BesideItem } from './besideItems';

/** `runningTurn`: the turn at work in the conversation, which a loop's run may be. */
export function useLoops(agentId: string | null, conversation: string | null, runningTurn: string | null = null): BesideItem[] {
    const key = agentId && conversation ? `work:agent:${agentId}:loops:${conversation}` : null;
    const read = useWorkV1(key, async (client) => {
        const agent = Agent.fromId(agentId!, { client });
        const [running, stopped] = await Promise.all([agent.wakeups({ conversation: conversation!, status: 'pending', limit: 100 }), agent.wakeups({ conversation: conversation!, status: 'failed', limit: 10 })]);
        return [...running, ...stopped].filter(isLoop);
    });
    useWorkFrames('platform:agent', (frame) => {
        if (key && frame.agent_id === agentId && (frame.change === 'turn' || (frame.change === 'wakeups' && (frame.conversation ?? conversation) === conversation))) invalidateV1(key);
    });
    return useMemo(() => (read.data ?? []).map((w) => loopItem(w, runningTurn)), [read.data, runningTurn]);
}
