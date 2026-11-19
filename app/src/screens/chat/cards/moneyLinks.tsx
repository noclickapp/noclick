// A page NoClick made for the owner to pay on, as a link to it: funds or a plan (account_payment_links_create), or a
// phone number's purchase page, where the person picks it and gives what its country asks. NoClick's reply points at
// the card below its words, so the card is always there; paying happens on NoClick's own page.
import { ArrowUpRight, CreditCard, Phone } from 'lucide-react';
import { num, str, type CoordinatorToolCall } from '@/lib/toolCalls';
import { formatMoney } from '@/screens/console/lib/format';
import { PILL_PRIMARY, Receipt } from '@/ui/chat/primitives';
import { cn } from '@/ui/utils';
import { paymentLinkOf, phonePurchasePageOf } from './cardMatchers';

function PayOnNoClick({ href, label }: { href: string; label: string }) {
    return (
        <a href={href} target="_blank" rel="noopener noreferrer" className={cn(PILL_PRIMARY, 'h-7')} data-testid="money-link">
            {label}
            <ArrowUpRight className="h-3.5 w-3.5" />
        </a>
    );
}

/** Funds for the balance, or a plan, paid on NoClick's page. */
export function PaymentLinkCard({ call }: { call: CoordinatorToolCall }) {
    const link = paymentLinkOf(call);
    const url = str(link, 'url');
    if (!url) return null;
    const price = num(link, 'price_usd');
    const what = str(link, 'label') ?? (str(link, 'kind') === 'plan' ? 'A plan' : 'Funds');
    return (
        <Receipt tone="info" lead={<CreditCard className="h-4 w-4 shrink-0 text-foreground/60" />} action={<PayOnNoClick href={url} label="Pay on NoClick" />}>
            {price !== undefined ? `${what} · ${formatMoney(price)}` : what}
        </Receipt>
    );
}

/** A phone number to pick and buy on its purchase page. */
export function NumberPurchaseLinkCard({ call }: { call: CoordinatorToolCall }) {
    const page = phonePurchasePageOf(call);
    if (!page) return null;
    return (
        <Receipt tone="info" lead={<Phone className="h-4 w-4 shrink-0 text-foreground/60" />} action={<PayOnNoClick href={page} label="Choose on NoClick" />}>
            A phone number, picked and bought on its page
        </Receipt>
    );
}
