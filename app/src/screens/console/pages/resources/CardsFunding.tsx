// The company's card balance, one implementation for the Cards panel's banner
// and the funding page (`/resources/cards/funding`): what cards can spend, the
// freeze a balance below zero puts on every card, and the bank details that
// fund it.
import type { ReactNode } from 'react';
import { Link } from 'react-router';
import { Snowflake } from 'lucide-react';
import { SURFACE } from '@/ui/primitives';
import { cn } from '@/ui/utils';
import { Card, type CardBankTransfer, type CardFunding } from 'noclick';
import { formatTimeTooltip } from '@/screens/console/lib/format';
import { useConsole, useConsoleHref } from '@/screens/console/hooks/useConsole';
import { useV1, type V1State } from '@/sdk/useV1';
import { consoleButtonClass } from '../../ui/Button';
import { CopyButton } from '../../ui/CopyButton';
import { Money } from '../../ui/Money';
import { PageSection } from '../../ui/PageHeader';
import { CARD_PAGES, CardProgramGate, RetryLine } from './CardsOnboarding';
import { Field } from './shared';

const NETWORKS: Readonly<Record<string, string>> = { ach: 'ACH', wire: 'Wire' };

function useCardFunding(): V1State<CardFunding> {
    const { client } = useConsole();
    return useV1('cards/funding', () => Card.funding({ client }));
}

/** NoClick froze every card when the balance went below zero (each reads `status_reason: negative_balance`). */
function FrozenWarning({ since }: { since: Date }) {
    return (
        <p role="alert" className="m-0 flex items-start gap-2 rounded-xl border border-red-600/40 px-4 py-3 text-[13px] text-red-600 dark:border-red-400/40 dark:text-red-400">
            <Snowflake aria-hidden className="mt-0.5 h-4 w-4 shrink-0" />
            <span>
                Your card balance is below zero, so NoClick froze your cards on{' '}
                <time dateTime={since.toISOString()} title={formatTimeTooltip(since)}>
                    {since.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}
                </time>
                . They pay again once it&apos;s funded.
            </span>
        </p>
    );
}

/** The balance, what pending charges hold and what's left, with the freeze above it when there is one. */
function FundingSummary({ funding, action }: { funding: V1State<CardFunding>; action?: ReactNode }) {
    if (funding.error !== undefined && !funding.data) {
        return (
            <RetryLine label="Card balance" onRetry={() => void funding.refresh()}>
                {"Couldn't read the card balance."}
            </RetryLine>
        );
    }
    const f = funding.data;
    return (
        <div className="mb-3 flex flex-col gap-3">
            {f?.frozenSince && <FrozenWarning since={f.frozenSince} />}
            <section aria-label="Card balance" className={cn(SURFACE, 'flex flex-wrap items-center gap-x-6 gap-y-3 px-4 py-3')}>
                <div className="flex min-w-0 flex-col">
                    <span className="text-[12px] text-muted-foreground">Card balance</span>
                    {f ? <Money usd={f.balanceUsd} className="text-[18px] font-semibold text-foreground" /> : <span aria-busy className="mt-1 h-6 w-24 animate-pulse rounded bg-foreground/[0.06]" />}
                </div>
                {f && (
                    <dl className="m-0 flex gap-6">
                        <div className="flex flex-col">
                            <dt className="text-[12px] text-muted-foreground">Pending</dt>
                            <dd className="m-0 text-[13px]">
                                <Money usd={f.pendingUsd} />
                            </dd>
                        </div>
                        <div className="flex flex-col">
                            <dt className="text-[12px] text-muted-foreground">Available</dt>
                            <dd className="m-0 text-[13px]">
                                <Money usd={f.availableUsd} />
                            </dd>
                        </div>
                    </dl>
                )}
                <p className="m-0 min-w-[12rem] flex-1 text-[12px] text-muted-foreground">
                    Your company&apos;s own balance at the card issuer: every card spends from it, and what cards pay isn&apos;t charged to your NoClick account. A charge it can&apos;t cover is declined.
                </p>
                {action}
            </section>
        </div>
    );
}

/** The Cards panel's banner: the balance, and the way to fund it. */
export function FundingBanner() {
    const href = useConsoleHref();
    return (
        <FundingSummary
            funding={useCardFunding()}
            action={
                <Link to={href(CARD_PAGES.funding)} className={consoleButtonClass('soft')}>
                    Fund your cards
                </Link>
            }
        />
    );
}

/** Where the company sends money: the account to send it to, copyable. */
function BankTransfer({ transfer }: { transfer: CardBankTransfer }) {
    const rows: [string, string | null][] = [
        ['Bank', transfer.bankName],
        ['Routing number', transfer.routingNumber],
        ['Account number', transfer.accountNumber],
    ];
    return (
        <dl aria-label="Bank details" className="m-0">
            {rows.map(([label, value]) => (
                <Field key={label} label={label}>
                    <span className={cn('inline-flex items-center gap-1', label !== 'Bank' && 'font-mono')}>
                        {value}
                        {value && label !== 'Bank' ? <CopyButton value={value} label={`Copy ${label.toLowerCase()}`} /> : null}
                    </span>
                </Field>
            ))}
            <Field label="Send by">{transfer.networks.map((n) => NETWORKS[n] ?? n).join(' or ')}</Field>
        </dl>
    );
}

function Funding() {
    const funding = useCardFunding();
    const transfer = funding.data?.bankTransfer;
    return (
        <>
            <FundingSummary funding={funding} />
            {transfer && (
                <PageSection
                    title="Bank transfer"
                    className="mt-8"
                    note="Send money from your company's bank account to this one. A wire lands the same day; ACH takes a few business days. What cards pay comes from this balance, not your NoClick account."
                >
                    <BankTransfer transfer={transfer} />
                </PageSection>
            )}
        </>
    );
}

/** `/resources/cards/funding`: the balance and how to fund it, once card issuing is active. */
export function CardsFundingPage() {
    return (
        <CardProgramGate>
            <Funding />
        </CardProgramGate>
    );
}
