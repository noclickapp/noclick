// What an agent's profile reads, through Work's client: the agent, what wakes it, its wake-ups and turns, the channels
// and spaces it's in, its month's spend, what it may do with each app, a conversation's tool servers and where a
// conversation of its runs. Each is a `work:agent:<id>:…` key, read again with `rereadAgent(id)` after a change and on
// the frames that say it moved.
import { Agent, Channel, Machine, Operation, Secret, Usage, Workspace, type NoClick } from 'noclick';
import { invalidateV1 } from '@/sdk/useV1';
import { useWorkFrames } from '@/sdk/live';
import { useWorkV1 } from '../agents/reads';
import { readMove } from '../moves/signIns';

const key = (agentId: string, what: string) => `work:agent:${agentId}:${what}`;
const agent = (client: NoClick, agentId: string) => Agent.fromId(agentId, { client });

export const useAgent = (agentId: string | null) => useWorkV1(agentId ? key(agentId, 'self') : null, (client) => Agent.get(agentId!, { client }));
export const triggersKey = (agentId: string) => key(agentId, 'triggers');
export const useTriggers = (agentId: string) => useWorkV1(triggersKey(agentId), (client) => agent(client, agentId).triggers());
export const useWakeups = (agentId: string) => useWorkV1(key(agentId, 'wakeups'), (client) => agent(client, agentId).wakeups({ status: 'pending', limit: 20 }));
export const useTurns = (agentId: string) => useWorkV1(key(agentId, 'turns'), async (client) => (await Operation.listPage({ client, agent: agentId, kind: 'agent.message', limit: 30 })).data);
export const useAgentChannels = (agentId: string) => useWorkV1(key(agentId, 'channels'), (client) => Channel.list({ client, agent: agentId, status: 'open' }));
export const useAgentSpaces = (agentId: string) => useWorkV1(key(agentId, 'spaces'), (client) => Workspace.list({ client, agent: agentId }));
export const useMachine = (machineId: string | null | undefined) => useWorkV1(machineId ? `work:machine:${machineId}` : null, (client) => Machine.get(machineId!, { client }));

/** What it spent this month. */
export const useMonthSpend = (agentId: string) => useWorkV1(key(agentId, 'spend'), async (client) => (await Usage.series({ client, agent: agentId })).totalUsd);

/** Where it runs (its session's sandbox, the agent's one), and whether it's up. */
export const useConversationSandbox = (agentId: string, conversation: string | null) =>
    useWorkV1(conversation ? key(agentId, `sandbox:${conversation}`) : null, (client) => agent(client, agentId).sandbox(conversation!).get());

/** The account's secrets (an agent lists the ones in its shell by id). */
export const SECRETS_KEY = 'work:secrets';
export const useSecrets = () => useWorkV1(SECRETS_KEY, (client) => Secret.list({ client }));

/** The move from a laptop that made it (its `arrived.carried`); null once the move itself has gone. */
export const useMove = (moveId: string | null) => useWorkV1(moveId ? `work:move:${moveId}` : null, (client) => readMove(client, moveId!));

/** A conversation's tool servers as its harness last saw them. */
export const useToolServers = (agentId: string, conversation: string | null) =>
    useWorkV1(conversation ? key(agentId, `tools:${conversation}`) : null, (client) => agent(client, agentId).conversation(conversation!).toolServers());
/** Reads a conversation's tool servers again; with none named, every conversation's of the agent. */
export const rereadToolServers = (agentId: string, conversation: string | null) => invalidateV1(key(agentId, `tools:${conversation ?? ''}`));

/** The MCP servers it has as tools, each a step of its automation and as it stands; for a conversation, each as that
 *  conversation's harness last said it (read again with the conversation's tool servers). */
export const useAgentToolServers = (agentId: string, conversation: string | null = null) =>
    useWorkV1(key(agentId, `tools:${conversation ?? ''}:servers`), (client) => agent(client, agentId).toolServers({ conversation: conversation ?? undefined }));

/** What it may do with each app it reaches, app by app (its Tools tab). */
export const toolAccessKey = (agentId: string) => key(agentId, 'access');
export const useToolAccess = (agentId: string) => useWorkV1(toolAccessKey(agentId), (client) => agent(client, agentId).toolAccess());

export const rereadAgent = (agentId: string) => invalidateV1(key(agentId, ''));

/** Reads the agent again when the backend says it moved: its turn, place, pause or definition (a rename), a conversation's tool
 *  servers, a machine or sandbox of the account changing. Its skills and memories follow their own frames. */
export function useAgentProfileFrames(agentId: string): void {
    // A turn or step of its: what it did and what will wake it next. Tool servers move with a turn's MCP gate or a reconnect.
    useWorkFrames('platform:agent', (frame) => {
        if (frame.agent_id !== agentId) return;
        if (frame.change === 'definition') return rereadAgent(agentId);
        if (frame.change === 'tool_servers') return rereadToolServers(agentId, frame.conversation ?? null);
        invalidateV1(key(agentId, 'turns'));
        invalidateV1(key(agentId, 'wakeups'));
    });
    useWorkFrames('platform:coding_agent', (frame) => {
        if (!frame.agent_id || frame.agent_id === agentId) rereadAgent(agentId);
    });
    useWorkFrames('platform:resource', (frame) => {
        if (frame.kind === 'machine' || frame.kind === 'sandbox') invalidateV1(key(agentId, 'sandbox'));
        // An account connected, reconnected or removed is an app its Tools tab shows.
        if (frame.kind === 'connection') invalidateV1(toolAccessKey(agentId));
    });
}
