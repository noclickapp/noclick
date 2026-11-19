// A chat's /loop, the one way every box runs it (Work's conversations and the Chat page): NoClick's own command, run
// at once beside any turn at work, never drawn as a message; what it did said in a toast (the loop it started and how
// it comes round, or how many it stopped). The loop itself then shows in the conversation's Beside, with its Stop.
import { toast } from 'sonner';
import { Operation, type AgentConversation, type AgentReply, type CommandResult } from 'noclick';

/** Runs `/loop <args>` in `conversation` and says what it did. */
export async function runLoop(conversation: AgentConversation, args: string, agentName: string): Promise<void> {
    try {
        toast(loopSaid(await conversation.runCommand('loop', args), agentName));
    } catch (e) {
        toast(e instanceof Error ? e.message : 'The loop didn’t start.');
    }
}

export function loopSaid(answer: CommandResult | Operation<AgentReply>, agentName: string): string {
    const result = (answer instanceof Operation ? {} : answer.result) as { every?: unknown; rounded_from?: unknown; stopped?: unknown };
    if (typeof result.stopped === 'number') return result.stopped === 0 ? 'No loop was running here' : result.stopped === 1 ? 'Stopped the loop' : `Stopped ${result.stopped} loops`;
    if (typeof result.every !== 'string') return `Looping: ${agentName} picks when each run comes`;
    return `Looping ${result.every}${typeof result.rounded_from === 'string' ? `, the nearest a clock keeps to ${result.rounded_from}` : ''}`;
}
