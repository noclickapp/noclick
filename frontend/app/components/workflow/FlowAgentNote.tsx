// In the canvas's place when the workflow opened is an agent's own flow (an old link to it, an Open on one of its
// runs): your own agent opens where the deployment keeps agents (Work) the moment the note shows; one that isn't yours
// to open just says whose flow it is.
import { useEffect } from 'react';
import { BUTTON_PRIMARY } from '~/components/shell/buttons';
import { agentOpenerFor } from '~/lib/workflowAgents';
import type { WorkflowAgentRef } from '~/types/socket-events.generated';

export function FlowAgentNote({ agent }: { agent: WorkflowAgentRef }) {
    const open = agentOpenerFor(agent);
    useEffect(() => {
        agentOpenerFor(agent)?.();
    }, [agent]);
    return (
        <div className="absolute inset-0 z-20 flex items-center justify-center bg-background" data-testid="flow-agent-note">
            <div className="flex max-w-sm flex-col items-center gap-4 px-6 text-center">
                <p className="text-[15px] text-foreground">This is {agent.name}’s own flow.</p>
                {open ? (
                    <button type="button" className={BUTTON_PRIMARY} onClick={open}>
                        Open {agent.name}
                    </button>
                ) : (
                    <p className="text-[13.5px] text-muted-foreground">It belongs to {agent.name}, which only its own account opens.</p>
                )}
            </div>
        </div>
    );
}
