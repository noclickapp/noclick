// A page NoClick made for the owner to pay on, as a link to it: funds or a plan (account_payment_links_create), or a
// phone number's purchase page, where the person picks it and gives what its country asks. NoClick's reply points at
// the card below its words, so the card is always there; paying happens on NoClick's own page. A payment link is an
// ask's row (`PaymentAsk`), the same in the chat (here and the host's card) and under an agent's message in a channel.
import { ArrowUpRight, Phone, Wallet } from 'lucide-react';
import { num, str, type CoordinatorToolCall } from '@/lib/toolCalls';
import { AskCard, AskMark, AskRow, PILL_PRIMARY, Receipt } from '@/ui/chat/primitives';
import { cn } from '@/ui/utils';
import { paymentLinkOf, phonePurchasePageOf } from './cardMatchers';
import { useCoordinatorJob } from './toolCardRegistry';

function PayOnNoClick({ href, label }: { href: string; label: string }) {
    return (
        <a href={href} target="_blank" rel="noopener noreferrer" className={cn(PILL_PRIMARY, 'h-7')} data-testid="money-link">
            {label}
            <ArrowUpRight className="h-3.5 w-3.5" />
        </a>
    );
}

/** "$25", "$12.99". */
const dollars = (amount: number) => `$${amount % 1 ? amount.toFixed(2) : amount}`;
const PERIOD: Record<string, string> = { yearly: ' a year', monthly: ' a month' };

/** A link that pays for the account (funds, or a plan), as one ask's row: what it buys, its price, and Pay, which
 *  opens checkout for this account with no sign-in. Paid, or closed unpaid (`state`: its operation's, `succeeded`
 *  once paid), it's one line. */
export function PaymentAsk({ label, priceUsd, billingPeriod, url, state }: { label: string; priceUsd?: number | null; billingPeriod?: string | null; url: string; state?: string | null }) {
    const what = label.charAt(0).toUpperCase() + label.slice(1);
    if (state === 'succeeded') return <Receipt>Paid · {what}</Receipt>;
    if (state) return <Receipt tone="info">The link for {label} closed unpaid. Ask NoClick for a new one.</Receipt>;
    const price = typeof priceUsd === 'number' ? dollars(priceUsd) : null;
    return (
        <AskCard testId="payment-ask">
            <AskRow
                lead={
                    <AskMark>
                        <Wallet />
                    </AskMark>
                }
                title={what}
                detail={`${price ? `${price}${PERIOD[billingPeriod ?? ''] ?? ''} · ` : ''}Opens checkout for this account`}
                action={
                    <a href={url} target="_blank" rel="noopener noreferrer" className={PILL_PRIMARY} data-testid="money-link">
                        {price ? `Pay ${price}` : 'Pay'}
                        <ArrowUpRight className="h-3.5 w-3.5" />
                    </a>
                }
            />
        </AskCard>
    );
}

/** Funds for the balance, or a plan, paid on NoClick's page: followed through its operation, as the thread does. */
export function PaymentLinkCard({ call }: { call: CoordinatorToolCall }) {
    const link = paymentLinkOf(call);
    const url = str(link, 'url');
    const { job } = useCoordinatorJob(str(call.result, 'job_id') ?? str(link, 'operation_id'));
    if (!url) return null;
    const status = str(job, 'status');
    const state = status === 'completed' || status === 'succeeded' ? 'succeeded' : status === 'failed' || status === 'cancelled' || status === 'expired' ? status : null;
    const what = str(link, 'label') ?? (str(link, 'kind') === 'plan' ? 'a plan' : 'funds');
    return <PaymentAsk label={what} priceUsd={num(link, 'price_usd')} billingPeriod={str(link, 'billing_period')} url={url} state={state} />;
}

/** A phone number to pick and buy on its purchase page. */
export function NumberPurchaseLinkCard({ call }: { call: CoordinatorToolCall }) {
    const page = phonePurchasePageOf(call);
    if (!page) return null;
    return (
        <Receipt tone="info" lead={<Phone className="h-4 w-4 shrink-0 text-foreground/60" />} action={<PayOnNoClick href={page} label="Choose on NoClick" />}>
            A phone number, picked and bought on its purchase page
        </Receipt>
    );
}
