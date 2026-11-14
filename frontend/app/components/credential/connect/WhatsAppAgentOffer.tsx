// The Connect dialog's last step for a WhatsApp number linked for the account itself (Connections, Settings, the
// palette): under the connected verdict it offers the number an agent, since linking makes none on its own. Create
// makes it with its own channel and opens Work there; a number an agent already answers shows that one instead.
import { useState } from 'react';
import { AlertCircle, Loader2 } from 'lucide-react';
import { BUTTON_GHOST, BUTTON_PRIMARY } from '~/components/shell/buttons';
import { MemberAvatar } from '~/components/shell/channels/avatars';
import type { MascotState } from '~/components/shell/channels/mascot/AgentMascot';
import { hueFor } from '~/components/shell/channels/model';
import { openAgentChannel, useWhatsAppNumberAgent, type NumberAgentTransport, type WhatsAppNumberAgent } from '~/hooks/useWhatsAppNumberAgent';
import { cn } from '~/lib/utils';

// The name the template's agent takes on a first number, before it has an id of its own.
const NEW_AGENT = { id: 'whatsapp-agent', name: 'WhatsApp' };
const WIDE = 'h-10 w-full justify-center';

/** The would-be agent's face beside what it says (the offer, or the agent that answers the number), wearing where it
 *  stands: waiting on a yes, at work while it's made, failed when it couldn't be. */
export function NumberAgentLine({ agent, title, line, state = 'waiting' }: { agent?: WhatsAppNumberAgent; title: string; line: string; state?: MascotState }) {
    const id = agent?.agent_id ?? NEW_AGENT.id;
    return (
        <div className="flex items-start gap-3.5">
            <MemberAvatar member={{ id, kind: 'agent', name: agent?.name ?? NEW_AGENT.name, agentId: agent?.agent_id, hue: hueFor(id) }} size={48} state={state} />
            <div className="min-w-0 pt-0.5">
                <p className="text-[14px] font-semibold text-foreground">{title}</p>
                <p className="mt-0.5 text-[13.5px] leading-relaxed text-muted-foreground">{line}</p>
            </div>
        </div>
    );
}

export function WhatsAppAgentOffer({ credentialId, onDone, transport }: { credentialId: string; onDone: () => void; transport?: NumberAgentTransport }) {
    const { state, create } = useWhatsAppNumberAgent(credentialId, transport);
    const [skipped, setSkipped] = useState(false);
    const done = (
        <button type="button" onClick={onDone} className={cn(BUTTON_PRIMARY, WIDE)}>
            Done
        </button>
    );

    if (state.phase === 'unavailable') return done;
    if (state.phase === 'loading') {
        return (
            <div className="space-y-6" aria-busy>
                <div className="flex items-start gap-3.5">
                    <span className="h-12 w-12 shrink-0 animate-pulse rounded-full bg-foreground/[0.06]" />
                    <span className="mt-1.5 block flex-1 space-y-2">
                        <span className="block h-3.5 w-1/2 animate-pulse rounded-full bg-foreground/[0.06]" />
                        <span className="block h-3 w-4/5 animate-pulse rounded-full bg-foreground/[0.06]" />
                    </span>
                </div>
                {done}
            </div>
        );
    }
    if (state.phase === 'answered') {
        const { agent } = state;
        const channelId = agent.channel_id;
        return (
            <div className="space-y-6">
                <NumberAgentLine agent={agent} title={`${agent.name} answers this number`} line="It was linked before, so it picks up where it left off. No second agent." />
                <div className="flex flex-wrap gap-2">
                    {channelId && (
                        <button
                            type="button"
                            onClick={() => {
                                openAgentChannel(channelId);
                                onDone();
                            }}
                            className={cn(BUTTON_PRIMARY, 'h-10 flex-1 justify-center')}
                        >
                            Open its channel
                        </button>
                    )}
                    <button type="button" onClick={onDone} className={cn(channelId ? BUTTON_GHOST : BUTTON_PRIMARY, 'h-10 justify-center', !channelId && 'w-full')}>
                        Done
                    </button>
                </div>
            </div>
        );
    }
    if (skipped) {
        return (
            <div className="space-y-6">
                <p className="text-[13.5px] leading-relaxed text-muted-foreground">No agent on it. You can add one later from the number in Connections.</p>
                {done}
            </div>
        );
    }

    const busy = state.phase === 'creating';
    const failed = state.phase === 'failed';
    const make = async () => {
        const made = await create();
        // A yes that made it opens its channel, where it asks whom to answer; one already there stays shown here.
        if (made?.made && made.agent.channel_id) {
            openAgentChannel(made.agent.channel_id);
            onDone();
        }
    };
    return (
        <div className="space-y-6" data-testid="whatsapp-agent-offer">
            <div className="space-y-3">
                <NumberAgentLine
                    title="Put an agent on this number?"
                    line="It answers your WhatsApp messages for you and lives in its own channel, where you tell it what to do."
                    state={busy ? 'working' : failed ? 'failed' : 'waiting'}
                />
                {failed && (
                    <p role="alert" className="flex items-start gap-2 text-[13.5px] text-red-600 dark:text-red-400">
                        <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                        Couldn’t create the agent. Your number is still connected.
                    </p>
                )}
            </div>
            <div className="flex flex-wrap gap-2">
                <button type="button" onClick={() => void make()} disabled={busy} className={cn(BUTTON_PRIMARY, 'h-10 flex-1 justify-center disabled:opacity-80')}>
                    {busy && <Loader2 className="h-4 w-4 animate-spin" />}
                    {busy ? 'Creating' : failed ? 'Try again' : 'Create agent'}
                </button>
                <button type="button" onClick={() => setSkipped(true)} disabled={busy} className={cn(BUTTON_GHOST, 'h-10 justify-center')}>
                    Not now
                </button>
            </div>
        </div>
    );
}
