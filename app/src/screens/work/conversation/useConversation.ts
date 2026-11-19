// An agent's session as Work shows it: the shared live thread (cloud/hooks/useAgentThread) through the agent the
// list already read, whose latest fields (name, harness, model) are what's shown, with what came in on its triggered
// turns beside it (cloud/hooks/useTurnActivity), followed by the same live events; and reading ahead what opening an
// agent shows, so a click after a hover paints at once.
import { useMemo, useRef, useState } from 'react';
import type { AgentEvent, NoClick } from 'noclick';
import { prefetchV1 } from '@/sdk/useV1';
import { readThread, threadKey, useAgentThread, type ConversationState } from '../hooks/useAgentThread';
import { useTurnActivity, type TurnActivityState } from '../hooks/useTurnActivity';
import { listedAgent, useAgents } from '../agents/reads';
import { useWorkClient } from '../client';
import { readActiveSession } from './sessions';

export type { ConversationState, Queued, SendInput } from '../hooks/useAgentThread';

/** Reads ahead what opening an agent shows (its session, and that session's thread), so a click after a hover paints
 *  at once. */
export function prefetchConversation(client: NoClick, agentId: string): void {
    const agent = listedAgent(client, agentId);
    if (!agent.isHydrated) return;
    readActiveSession(client, agentId).then(
        (session) => prefetchV1(client, threadKey(agentId, session), () => readThread(client, agent, session)),
        (e: unknown) => console.warn('[work] its session didn’t read ahead:', e)
    );
}

export interface WorkConversationState extends ConversationState {
    /** What came in on its triggered turns, and what it did with each. */
    activity: TurnActivityState;
}

export function useConversation(agentId: string, conversation: string): WorkConversationState {
    const client = useWorkClient();
    // Calls go through the agent the list already read (a lazy one reads it first, once, before anything else); what's
    // shown of it (name, harness, model) is the list's latest.
    const caller = useMemo(() => listedAgent(client, agentId), [agentId, client]);
    const heard = useRef<(event: AgentEvent) => void>(() => undefined);
    const state = useAgentThread(caller, conversation, { key: agentId, onEvent: (event) => heard.current(event) });
    const [activityError, setActivityError] = useState<string | null>(null);
    const activity = useTurnActivity(caller, agentId, conversation, state.thread, state.ready, setActivityError);
    heard.current = activity.heard;
    const { data: listed } = useAgents();
    return {
        ...state,
        agent: listed?.find((a) => a.id === agentId) ?? caller,
        // Drawn once what came in on its triggered turns is read too, so they never redraw as their chat.
        ready: state.ready && activity.ready,
        error: state.error ?? activityError,
        clearError: () => {
            state.clearError();
            setActivityError(null);
        },
        activity,
    };
}
