// What an agent's turn left waiting on a person, under its message in a channel (the message's asks): the chat's own
// asks, drawn the same. Accounts to connect over their links, which anyone in the channel may connect (as the link
// allows), each folding to who connected it and which account once NoClick says so; a call held for the owner's OK,
// answered here by the owner alone (everyone else sees it waiting on them); a link that pays for the account.
import { useSlot } from '@/slots';
import type { TurnAsk } from '@/lib/turnAsks';
import type { ChannelMessage } from '@/screens/channels/types';
import { CONNECT_LINK } from '../slots';
import type { ConnectedAccount } from './inline/setup';
import { PaymentAsk } from './moneyLinks';
import { ApprovalAsk, type ApprovalTold } from './PlatformCards';
import type { ConnectAsk } from './toolCardRegistry';

type Of<K extends TurnAsk['kind']> = Extract<TurnAsk, { kind: K }>;

/** Someone the channel named, as a line says them: you, after the channel's reading (`seenBy`), else their name. */
const said = (by: { type: string; id: string | null; name: string }) => (by.type === 'account' && !by.id ? 'You' : by.name);

export function ChannelAsks({ message, answersApprovals, onConnected }: { message: ChannelMessage; answersApprovals: boolean; onConnected: (askId: string) => void }) {
    const { Rows } = useSlot(CONNECT_LINK);
    const all = message.turnAsks?.asks ?? [];
    const connects = all.filter((a): a is Of<'connect'> => a.kind === 'connect');
    const startedAt = Date.parse(message.at) || 0;
    const asks: ConnectAsk[] = connects.map((a) => ({ id: a.id, credentialType: a.credentialType, url: a.url, message: a.reason ?? undefined, startedAt, operationId: a.id }));
    const landed: Record<string, ConnectedAccount> = Object.fromEntries(
        connects.filter((a) => a.state === 'succeeded').map((a) => [a.id, { name: a.label, account: a.account ?? undefined, by: a.by ? said(a.by) : undefined }])
    );
    if (!all.length) return null;
    return (
        <div className="mt-2 flex max-w-[560px] flex-col gap-2" data-testid="channel-asks">
            {asks.length > 0 && <Rows asks={asks} landed={landed} connectedBy="You" onConnected={onConnected} />}
            {all.map((ask) =>
                ask.kind === 'approval' ? (
                    <ApprovalAsk
                        key={ask.id}
                        approvalId={ask.approvalId}
                        told={{ action: ask.summary, price: ask.price as ApprovalTold['price'], impact: null, status: 'pending', terms: [] }}
                        heldOperationId={ask.id}
                        mayAnswer={answersApprovals}
                        settled={ask.state}
                    />
                ) : ask.kind === 'payment' ? (
                    <PaymentAsk key={ask.id} label={ask.label} priceUsd={ask.priceUsd} billingPeriod={ask.billingPeriod} url={ask.url} state={ask.state} />
                ) : null
            )}
        </div>
    );
}
