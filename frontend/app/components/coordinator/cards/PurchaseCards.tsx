// Buying in the chat: a phone number the coordinator asked you to pick (request_phone_number), bought right here
// through the same signed-in, CSRF-protected purchase operations its review page uses, a quoted price confirmed in the row
// before anything is charged; a payment link it made (purchase_link); and a request a plan or top-up stands in the
// way of, with the links that pay for it.
import { useEffect, useState } from 'react';
import { useFetcher } from 'react-router';
import { ArrowUpRight, Phone } from 'lucide-react';
import { BuyAside, PayCard, type PayLink } from '~/components/coordinator/inline/commerce';
import { GlyphTile, InlineCard, PILL_QUIET, Receipt, Row, Rows, Status } from '~/components/coordinator/inline/primitives';
import { capabilityLabels, formatNumber, placeOf } from '~/components/phone/numberDisplay';
import { countryName } from '~/components/ui/country-picker';
import { useCoordinatorJob } from '~/hooks/useCoordinatorJobs';
import { TYPE_LABELS, usePhoneNumberPurchase, usePurchaseLinkTransport, type PhonePurchaseQuote } from '~/hooks/usePhoneNumberPurchase';
import { failed, list, num, str, type CoordinatorToolCall, type JsonObject } from '~/lib/coordinatorToolCalls';
import { formatUsd } from '~/lib/money';
import { navigateToTab } from '~/lib/navigation';
import { cn } from '~/lib/utils';
import { purchaseToken } from './purchaseLink';

export { isPhonePurchaseLink } from './purchaseLink';

const SHOWN = 4;

function sentence(text: string): string {
    return text.charAt(0).toUpperCase() + text.slice(1);
}

function usd(amount: number): string {
    return `$${amount % 1 ? amount.toFixed(2) : amount}`;
}

// ── A phone number to pick ───────────────────────────────────────────────────

interface PurchaseView {
    status: string;
    purpose?: string | null;
    phone_number?: string | null;
    error?: string | null;
    quote?: PhonePurchaseQuote | null;
}

function NumberPicker({ token, purpose, view, csrfToken, onDone }: { token: string; purpose: string; view: PurchaseView; csrfToken: string; onDone: (state: PurchaseView) => void }) {
    const send = usePurchaseLinkTransport(token, csrfToken);
    // One search when the card opens, in the owner's country; "More numbers" is the full page, with every filter.
    const purchase = usePhoneNumberPurchase({
        sendEvent: send,
        firstPage: SHOWN,
        confirmation: { initialQuote: view.quote, onState: (next) => onDone({ ...view, ...next }) },
        onCredentialCreated: (_id, phone_number) => onDone({ ...view, status: 'fulfilled', phone_number, error: null }),
    });
    const { quote, buying, filters } = purchase;
    const page = `/credential/purchase/${token}`;
    return (
        <InlineCard
            lead={
                <GlyphTile>
                    <Phone className="h-4 w-4" />
                </GlyphTile>
            }
            title="Pick a phone number"
            meta={`For ${purpose.replace(/\.$/, '')}.${filters ? ` ${countryName(filters.country)}, ${TYPE_LABELS[filters.numberType].toLowerCase()}, each at its own price.` : ''}`}
            actions={
                <a href={page} target="_blank" rel="noopener noreferrer" className={PILL_QUIET}>
                    More numbers
                    <ArrowUpRight className="h-3.5 w-3.5" />
                </a>
            }
        >
            {purchase.notSold && filters ? (
                <p className="text-[13.5px] text-muted-foreground">Numbers aren’t sold in {countryName(filters.country)} yet. Choose another country under More numbers.</p>
            ) : purchase.numbers === null ? (
                <Status state="working">Finding numbers</Status>
            ) : purchase.numbers.length === 0 ? (
                <p className="text-[13.5px] text-muted-foreground">No numbers are free right now. Try More numbers to search another place or kind.</p>
            ) : (
                <Rows className="-my-1">
                    {purchase.numbers.slice(0, SHOWN).map((n) => {
                        const quoted = quote?.phone_number === n.phone_number;
                        const chosen = quoted || (buying === n.phone_number && !quote);
                        const priced = quoted ? quote : n;
                        // A country that asks a step can't be bought; one that asks for an address or documents takes them on the page.
                        const elsewhere =
                            n.requirements.needs === 'steps' ? (
                                <span className="text-[12.5px] text-amber-700 dark:text-amber-400">Can’t buy here yet</span>
                            ) : n.requirements.needs === 'address' || n.requirements.needs === 'documents' ? (
                                <a href={page} target="_blank" rel="noopener noreferrer" className={PILL_QUIET}>
                                    {n.requirements.needs === 'documents' ? 'Add documents' : 'Add address'}
                                    <ArrowUpRight className="h-3.5 w-3.5" />
                                </a>
                            ) : null;
                        return (
                            <Row
                                key={n.phone_number}
                                title={<span className="tabular-nums">{formatNumber(n.phone_number)}</span>}
                                detail={[placeOf(n), ...capabilityLabels(n.capabilities)].join(' · ')}
                                aside={
                                    elsewhere ?? (
                                        <BuyAside
                                            price={chosen && !quoted ? undefined : formatUsd(priced.monthly_credits)}
                                            once={priced.upfront_credits > 0 ? formatUsd(priced.upfront_credits) : null}
                                            unit="month"
                                            chosen={chosen}
                                            buying={quoted && buying === n.phone_number}
                                            disabled={purchase.busy}
                                            onChoose={() => void purchase.buy(n)}
                                            onCancel={() => purchase.setQuote(null)}
                                            onConfirm={() => void purchase.confirm()}
                                        />
                                    )
                                }
                            />
                        );
                    })}
                </Rows>
            )}
            {purchase.error && <p className="mt-2 text-[13px] text-red-600 dark:text-red-400">{purchase.error.text}</p>}
        </InlineCard>
    );
}

export function PhoneNumberCard({ call }: { call: CoordinatorToolCall }) {
    const token = purchaseToken(call);
    const path = token ? `/credential/purchase/${token}` : '';
    const page = useFetcher<{ purchase: PurchaseView; csrfToken: string }>();
    const [state, setState] = useState<PurchaseView | null>(null);
    const { load } = page;
    useEffect(() => {
        if (path) void load(path);
    }, [load, path]);
    if (!path || failed(call.result)) return null;
    const view = state ?? page.data?.purchase;
    if (!view || !page.data) return <Status state="working">Getting numbers ready</Status>;
    const purpose = view.purpose || str(call.args, 'purpose') || 'your agents';
    if (view.status === 'fulfilled') {
        return (
            <Receipt
                action={
                    <button type="button" className={cn(PILL_QUIET, 'h-7')} onClick={() => navigateToTab('resources', { kind: 'numbers' })}>
                        Numbers
                    </button>
                }
            >
                {view.phone_number ? formatNumber(view.phone_number) : 'Your number'} is yours · it takes calls
            </Receipt>
        );
    }
    if (view.status === 'provisioning') return <Status state="working">{view.error || 'Setting up your number'}</Status>;
    if (view.status !== 'pending') return <Receipt tone="info">This number request {view.status === 'expired' ? 'expired' : 'is closed'}. Ask NoClick for a new one.</Receipt>;
    return <NumberPicker token={token!} purpose={purpose} view={view} csrfToken={page.data.csrfToken} onDone={setState} />;
}

// ── A payment link ───────────────────────────────────────────────────────────

/** How often a link's price is charged; a one-time payment (funds) has no period. */
function period(billing: string | undefined): string {
    return billing === 'yearly' ? ' a year' : billing === 'monthly' ? ' a month' : '';
}

export function PaymentCard({ call }: { call: CoordinatorToolCall }) {
    const jobId = str(call.result, 'job_id');
    const { job } = useCoordinatorJob(jobId);
    const url = str(call.result, 'url');
    const label = str(call.result, 'label');
    const price = num(call.result, 'price_usd');
    if (!url || !label || failed(call.result)) return null;
    const status = str(job, 'status');
    if (status === 'completed') return <Receipt>Paid · {label}</Receipt>;
    if (status === 'failed' || status === 'cancelled') return <Receipt tone="info">The link for {label} closed unpaid. Ask NoClick for a new one.</Receipt>;
    const billing = str(call.result, 'billing_period');
    return (
        <PayCard
            title={sentence(label)}
            meta={`${price !== undefined ? `${usd(price)}${period(billing)} · ` : ''}Opens checkout for this account, no sign-in needed.`}
            links={[{ label: price !== undefined ? `Pay ${usd(price)}` : 'Pay', href: url }]}
        />
    );
}

// ── What stands in the way ───────────────────────────────────────────────────

const PER: Record<string, string> = { yearly: '/yr', monthly: '/mo' };

/** A refused call that offers the way past it: the plan or funds links the refusal minted. */
export function refusalLinks(call: CoordinatorToolCall): PayLink[] {
    if (!failed(call.result)) return [];
    return list(call.result, 'purchase_links').flatMap((l) => {
        const link = l as JsonObject;
        const href = str(link, 'url');
        const label = str(link, 'label');
        const price = num(link, 'price_usd');
        const per = PER[str(link, 'billing_period') ?? ''] ?? '';
        return href && label ? [{ href, label: `${sentence(label.replace(/^(the|a) /, ''))}${price !== undefined ? ` · ${usd(price)}${per}` : ''}` }] : [];
    });
}

export function RefusalCard({ call, links }: { call: CoordinatorToolCall; links: PayLink[] }) {
    const kind = str(call.result, 'kind');
    return (
        <PayCard
            title={str(call.result, 'error') || 'This needs a bigger plan'}
            meta={kind === 'credits' ? 'Adding funds covers it. Each link opens checkout for this account.' : 'Each link opens checkout for this account, no sign-in needed.'}
            links={links}
        />
    );
}
