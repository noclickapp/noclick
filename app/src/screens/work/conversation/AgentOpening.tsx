// An agent's screen in the moment before Work knows which session it's in (it reads that as the agent opens): its
// face, its session's name, the thread's loading lines and its box, laid out as AgentConversation lays them, so a tap
// shows the agent at once and the conversation takes the same place once its session is read.
import { ChevronDown, MoreHorizontal } from 'lucide-react';
import type { ChannelMember } from '@/screens/channels/types';
import { useInPhoneShell } from '@/ui/phoneBar';
import { cn } from '@/ui/utils';
import { AgentRing } from '../agents/AgentRing';
import { nameOf, useAgentFaces, useAgents, useSpaceNoClicks } from '../agents/reads';
import { Composer } from './Composer';
import { CONVERSATION_CSS, ICON_BUTTON, LANE } from './styles';

const NOTHING = async () => false;

export function AgentOpening({ agentId }: { agentId: string }) {
    const inPhone = useInPhoneShell();
    const faces = useAgentFaces();
    const { data: agents } = useAgents();
    const noclicks = useSpaceNoClicks();
    const listed = agents?.find((a) => a.id === agentId);
    const name = listed ? nameOf(listed, noclicks) : '';
    const face: ChannelMember = faces.get(agentId) ?? { id: agentId, kind: 'agent', name, agentId };
    return (
        <div className="relative flex min-h-0 min-w-0 flex-1 bg-background" data-testid="agent-opening" aria-busy>
            <style>{CONVERSATION_CSS}</style>
            <div className="flex min-h-0 min-w-0 flex-1 flex-col">
                <header className="flex h-12 shrink-0 items-center gap-2 pl-4 pr-3">
                    <span className="-ml-1.5 flex min-w-0 shrink-0 items-center gap-2 px-1.5 py-1 max-md:py-2">
                        <AgentRing member={face} status="idle" size={24} />
                        {!inPhone && <span className="shrink-0 text-sm font-medium">{face.name}</span>}
                    </span>
                    <span className="flex min-w-0 items-center gap-1 px-1.5 py-1 text-sm text-muted-foreground max-md:py-2.5">
                        {!inPhone && (
                            <span aria-hidden className="text-muted-foreground/50">
                                /
                            </span>
                        )}
                        <span className="truncate">This session</span>
                        <ChevronDown className="h-3.5 w-3.5 shrink-0" strokeWidth={2} />
                    </span>
                    <span aria-hidden className={cn(ICON_BUTTON, 'ml-auto opacity-50 max-md:h-10 max-md:w-10')}>
                        <MoreHorizontal className="h-4 w-4" />
                    </span>
                </header>
                <div className="relative min-h-0 flex-1 overflow-y-auto scrollbar-subtle">
                    <div className={cn(LANE, 'flex min-h-full flex-col justify-end px-5 pb-2')}>
                        <div className="space-y-2 py-10" aria-label="Loading the session">
                            <div className="h-2.5 w-2/5 animate-pulse rounded-full bg-foreground/[0.06]" />
                            <div className="h-2.5 w-3/5 animate-pulse rounded-full bg-foreground/[0.06]" />
                            <div className="h-2.5 w-1/3 animate-pulse rounded-full bg-foreground/[0.06]" />
                        </div>
                    </div>
                </div>
                {/* Its box as it will look, but nothing to type into yet: words typed here would go when the session's box
                    takes its place. */}
                <div inert aria-hidden className="contents">
                    <Composer
                        agentName={face.name || 'it'}
                        harnessLabel="Its harness"
                        working={false}
                        ready={false}
                        commands={null}
                        queued={[]}
                        requests={[]}
                        subagents={[]}
                        onShowSubagents={() => undefined}
                        model={null}
                        onControl={() => undefined}
                        drawer={null}
                        // The row under the box (its account, where it runs, its budget) takes this height, so the box
                        // stays put when it comes.
                        footer={<div className="h-7" />}
                        onSend={NOTHING}
                        onStop={() => undefined}
                        onUnqueue={async () => null}
                        onAnswer={() => undefined}
                        upload={() => Promise.reject(new Error('Its session is still opening.'))}
                    />
                </div>
            </div>
        </div>
    );
}
