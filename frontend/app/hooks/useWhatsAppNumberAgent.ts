// A linked WhatsApp number's agent (whatsapp:agent:*): whether this account may put one on it, the agent that answers
// it already, and making it on the owner's yes. Linking a number makes nothing on its own; the Connect dialog's last
// step and the number's page under Connections both offer it through this, so they say the same.
import { useCallback, useEffect, useRef, useState } from 'react';
import { navigateToTab } from '~/lib/navigation';
import { sendEventAsync } from '~/lib/socket-sender';
import type { WhatsAppAgentCreateResponse, WhatsAppAgentStatusResponse, WhatsAppNumberAgent } from '~/types/socket-events.generated';

export type { WhatsAppNumberAgent };

type Ask = { event_name: 'whatsapp:agent:status' | 'whatsapp:agent:create'; credential_id: string };
/** How the asks travel: the app's socket, or a lab's stand-in. */
export type NumberAgentTransport = (ask: Ask) => Promise<WhatsAppAgentStatusResponse | WhatsAppAgentCreateResponse | null>;

// Making an agent builds its channel too: past the socket's usual wait.
const CREATE_TIMEOUT_MS = 60_000;
const overSocket: NumberAgentTransport = (ask) =>
    sendEventAsync<WhatsAppAgentStatusResponse | WhatsAppAgentCreateResponse>(ask, undefined, ask.event_name === 'whatsapp:agent:create' ? CREATE_TIMEOUT_MS : undefined);

/** `offer`: no agent answers it and one may be made (`creating`, `failed` while it's made); `answered`: one does
 *  (`made` when this yes made it); `unavailable`: nothing to offer here (no agents on this account, or no number). */
export type NumberAgentState =
    | { phase: 'loading' }
    | { phase: 'unavailable' }
    | { phase: 'offer' | 'creating' | 'failed' }
    | { phase: 'answered'; agent: WhatsAppNumberAgent; made: boolean };

export function useWhatsAppNumberAgent(credentialId: string | undefined, transport: NumberAgentTransport = overSocket) {
    const [state, setState] = useState<NumberAgentState>({ phase: credentialId ? 'loading' : 'unavailable' });
    const send = useRef(transport);
    send.current = transport;

    useEffect(() => {
        if (!credentialId) return;
        let live = true;
        setState({ phase: 'loading' });
        send.current({ event_name: 'whatsapp:agent:status', credential_id: credentialId })
            .then((answer) => {
                if (!live) return;
                const status = answer as WhatsAppAgentStatusResponse | null;
                if (status?.agent) setState({ phase: 'answered', agent: status.agent, made: false });
                else setState({ phase: status?.success && status.available ? 'offer' : 'unavailable' });
            })
            .catch(() => live && setState({ phase: 'unavailable' }));
        return () => {
            live = false;
        };
    }, [credentialId]);

    /** The number's agent, made (or the one that answers it already); null when it couldn't be made. */
    const create = useCallback(async (): Promise<{ agent: WhatsAppNumberAgent; made: boolean } | null> => {
        if (!credentialId) return null;
        setState({ phase: 'creating' });
        const answer = (await send.current({ event_name: 'whatsapp:agent:create', credential_id: credentialId }).catch(() => null)) as WhatsAppAgentCreateResponse | null;
        if (!answer?.success || !answer.agent) {
            setState({ phase: 'failed' });
            return null;
        }
        const made = { agent: answer.agent, made: !!answer.created };
        setState({ phase: 'answered', ...made });
        return made;
    }, [credentialId]);

    return { state, create };
}

/** Work, on the agent's own channel. */
export function openAgentChannel(channelId: string): void {
    navigateToTab('work', { show: 'home', channel: channelId, thread: null });
}
