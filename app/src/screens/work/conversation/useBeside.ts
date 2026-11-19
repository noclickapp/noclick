// What works beside a session, read: its harness's subagents from its thread, and the NoClick agents it started
// with their tasks' operations, where each agent stands and what its task has cost (its session's charges).
// Read again when one of those agents moves (its `platform:agent` frames), never on a timer.
import { useMemo } from 'react';
import { Agent, Operation, type Browser, type HarnessRequest } from 'noclick';
import { invalidateV1 } from '@/sdk/useV1';
import { useAgentStates, useWorkV1 } from '../agents/reads';
import { useWorkFrames } from '@/sdk/live';
import { agentItem, browserItems, startedAgents, subagentItems, type BesideItem } from './besideItems';
import { readActiveSession } from './sessions';
import type { Thread } from '@/lib/agentThread/thread';

/** `browser`: the conversation's own, drawn in the card as its live tile. */
export function useBeside(thread: Thread, requests: readonly HarnessRequest[], browser: Browser | null = null): BesideItem[] {
    const started = useMemo(() => startedAgents(thread), [thread]);
    const jobIds = started.flatMap((s) => (s.child.jobId ? [s.child.jobId] : []));
    const agentIds = started.map((s) => s.child.agentId);
    const jobsKey = jobIds.length ? `work:beside:jobs:${jobIds.join(',')}` : null;
    const spendKey = agentIds.length ? `work:beside:spend:${agentIds.join(',')}` : null;
    // A task it can't read stays where its agent stands.
    const jobs = useWorkV1(jobsKey, async (client) =>
        (await Promise.allSettled(jobIds.map((id) => Operation.fromId(id, { client }).refresh()))).flatMap((r) => (r.status === 'fulfilled' ? [r.value] : []))
    );
    // Each task's own charges: its agent was started for it, so its session is that task. One it can't read shows no
    // spend.
    const spend = useWorkV1(spendKey, async (client) =>
        new Map(
            (await Promise.allSettled(agentIds.map(async (id) => [id, (await Agent.fromId(id, { client }).conversation(await readActiveSession(client, id)).usage()).costUsd] as const))).flatMap((r) =>
                r.status === 'fulfilled' ? [r.value] : []
            )
        )
    );
    const states = useAgentStates(null);
    useWorkFrames('platform:agent', (frame) => {
        if (!agentIds.includes(frame.agent_id)) return;
        if (jobsKey) invalidateV1(jobsKey);
        if (spendKey && frame.change === 'turn') invalidateV1(spendKey);
    });
    return useMemo(
        () => [
            ...subagentItems(thread, requests),
            ...started.map((s) =>
                agentItem(
                    s,
                    jobs.data?.find((j) => j.id === s.child.jobId),
                    states.data?.find((x) => x.agentId === s.child.agentId),
                    spend.data?.get(s.child.agentId) ?? null
                )
            ),
            ...browserItems(browser),
        ],
        [thread, requests, started, jobs.data, states.data, spend.data, browser]
    );
}
