// One of your agents as a picker lists it, in two lines: its name with its model in brackets and its harness's mark,
// then its job (an automation's agent: the automation it's in). NoClick's own wears its mark, with what it does here.
import { NodeMark } from '@/ui/primitives';
import type { AccountMenuUser } from '@/ui/accountParts';
import { MemberAvatar } from './avatars';
import { hueFor } from './model';
import type { AgentChoice } from './types';

export function AgentChoiceRow({ agent, user }: { agent: AgentChoice; user?: AccountMenuUser }) {
    const line = agent.source === 'automation' ? `Agent in ${agent.workflowName}` : agent.role;
    return (
        <>
            <MemberAvatar member={{ id: agent.id, kind: 'agent', name: agent.name, hue: hueFor(agent.id), ...(agent.noclick ? { noclick: true } : {}) }} user={user} size={28} />
            <span className="min-w-0 flex-1">
                <span className="flex min-w-0 items-center gap-1.5">
                    <span className="truncate text-[14px] font-medium text-foreground">
                        {agent.name}
                        {agent.modelLine && <span className="font-normal text-muted-foreground"> ({agent.modelLine})</span>}
                    </span>
                    {!agent.noclick && agent.markType && <NodeMark type={agent.markType} size="xs" />}
                </span>
                {line && <span className="block truncate text-xs text-muted-foreground">{line}</span>}
            </span>
        </>
    );
}
