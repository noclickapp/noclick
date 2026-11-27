// Cards: virtual cards with limits, for agents that buy things. Designed, not
// built yet: shown only in the lab.
// The banner is where card issuing stands until it's active, then the card
// balance; the drawer (`?card=`) shows the limits and merchants (edited in one
// dialog), recent charges (a held one links to its approval), reveals the number
// behind an audited confirm, and freezes, unfreezes or closes the card. A card
// NoClick froze for a balance below zero links to funding instead of unfreezing.
import { useEffect, useState } from 'react';
import { Snowflake } from 'lucide-react';
import { Link } from 'react-router';
import { toast } from 'sonner';
import { cn } from '@/ui/utils';
import { Card, type CardTransaction } from 'noclick';
import { NEW_SNIPPETS } from '@/screens/console/lib/snippets';
import type { StatusLook } from '@/screens/console/lib/status';
import { defaultWriteUser, userLabel } from '@/screens/console/lib/userFilter';
import { useConsole, useConsoleHref } from '@/screens/console/hooks/useConsole';
import { usePaged } from '@/sdk/usePaged';
import { invalidateV1, useV1 } from '@/sdk/useV1';
import { useSearchParam } from '@/screens/console/hooks/useQueryState';
import { recordRecent } from '@/screens/console/hooks/useRecent';
import { NewInCode } from '../../NewInCode';
import { CapMeter } from '../../ui/CapMeter';
import { ConsoleButton, consoleButtonClass } from '../../ui/Button';
import { DataTable, type Column } from '../../ui/DataTable';
import { Drawer } from '../../ui/Drawer';
import { EmptyCode } from '../../ui/EmptyCode';
import { ErrorPanel } from '../../ui/ErrorPanel';
import { Money } from '../../ui/Money';
import { OwnerOnlyNote } from '../../ui/OwnerOnlyNote';
import { StatusPill } from '../../ui/StatusPill';
import { TimeCell } from '../../ui/TimeCell';
import { useOwnerOnly } from '../../ownerOnly';
import { useAgentNames } from '../lookups';
import { EditLimits, limitLine, merchantLabel, RevealDetails, dollars } from './CardsDialogs';
import { FundingBanner } from './CardsFunding';
import { CARD_PAGES, CardProgramGate } from './CardsOnboarding';
import { ConfirmAction, errorText, Field, PanelToolbar, Section, type PanelProps } from './shared';

/** How many recent charges the drawer shows. */
const RECENT_CHARGES = 10;

/** Frozen by NoClick while the card balance is below zero, not by you: it pays again once funded. */
const frozenForBalance = (card: Card) => card.status === 'frozen' && card.statusReason === 'negative_balance';

export function cardStatus(card: Card): StatusLook {
    switch (card.status) {
        case 'active':
            return { label: 'Active', glyph: 'filled', tone: 'ink' };
        case 'frozen':
            return { label: 'Frozen', reason: frozenForBalance(card) ? 'balance' : null, glyph: 'hollow', tone: 'ink' };
        case 'closed':
            return { label: 'Closed', glyph: 'muted', tone: 'muted' };
        default:
            return { label: card.status, glyph: 'hollow', tone: 'muted' };
    }
}

const DECLINE_REASONS: Readonly<Record<string, string>> = {
    over_limit: 'over limit',
    merchant_not_allowed: 'merchant',
    amount_mismatch: 'wrong amount',
    frozen: 'frozen',
    insufficient_funds: 'balance',
    not_approved: 'not approved',
    approval_expired: 'no answer',
    awaiting_approval: 'awaiting approval',
    card_closed: 'card closed',
    card_expired: 'card expired',
    invalid_cvc: 'wrong CVC',
    invalid_expiry: 'wrong expiry',
    '3ds_failed': '3D Secure',
    issuer_declined: 'issuer',
};

export function chargeStatus(charge: CardTransaction): StatusLook {
    switch (charge.status) {
        case 'approved':
            return { label: 'Approved', glyph: 'check', tone: 'ink' };
        case 'settled':
            return { label: 'Settled', glyph: 'check', tone: 'ink' };
        case 'reversed':
            return { label: 'Reversed', glyph: 'muted', tone: 'muted' };
        case 'declined':
            return { label: 'Declined', reason: charge.declineReason ? (DECLINE_REASONS[charge.declineReason] ?? charge.declineReason) : null, glyph: 'cross', tone: 'failure' };
        case 'pending_approval':
            return { label: 'Pending approval', glyph: 'waiting', tone: 'ink' };
        default:
            return { label: charge.status ?? 'Unknown', glyph: 'hollow', tone: 'muted' };
    }
}

const brandLabel = (brand: string | null) => (brand ? brand.charAt(0).toUpperCase() + brand.slice(1) : 'Card');
const expiry = (card: Card) => `${String(card.expMonth ?? '').padStart(2, '0')}/${String(card.expYear ?? '').slice(-2)}`;

/** Spend against the limit; a per-charge limit has no running total to fill, so it shows the month's spend. */
function Spent({ card, className }: { card: Card; className?: string }) {
    if (card.interval === 'transaction') {
        return (
            <span className={cn('inline-flex items-baseline gap-1.5 whitespace-nowrap', className)}>
                <Money usd={card.spentUsd} />
                <span className="text-[12px] text-muted-foreground">this month</span>
            </span>
        );
    }
    return <CapMeter spent={card.spentUsd} cap={card.limitUsd} className={className} />;
}

function ChargeRow({ charge }: { charge: CardTransaction }) {
    const href = useConsoleHref();
    const held = charge.status === 'pending_approval';
    return (
        <li className={cn('flex flex-col gap-1 px-3 py-2 text-[13px]')}>
            <div className="flex items-center gap-3">
                <TimeCell value={charge.at} className="hidden w-16 shrink-0 text-muted-foreground sm:block" />
                <span className="min-w-0 flex-1 truncate" title={charge.merchantCategory ? merchantLabel(charge.merchantCategory) : undefined}>
                    {charge.merchant ?? 'Unknown merchant'}
                </span>
                <StatusPill look={chargeStatus(charge)} />
                <Money usd={charge.amountUsd} className="w-20 shrink-0 text-right" />
            </div>
            {held && (
                <p className="m-0 text-[12px] text-muted-foreground sm:pl-[4.75rem]">
                    Held for a person: if they approve within 30 minutes, the merchant&apos;s retry goes through.{' '}
                    {charge.approvalId && (
                        <Link to={href('logs', { op: charge.approvalId })} className="font-medium text-foreground underline-offset-2 hover:underline">
                            Review approval
                        </Link>
                    )}
                </p>
            )}
        </li>
    );
}

function RecentCharges({ card }: { card: Card }) {
    const charges = useV1(`cards/${card.id}/transactions`, () => card.transactions({ limit: RECENT_CHARGES }));
    return (
        <Section title="Recent charges">
            {charges.error !== undefined && !charges.data ? (
                <ErrorPanel error={charges.error} onRetry={() => void charges.refresh()} />
            ) : !charges.data ? (
                <div aria-busy className="h-24 animate-pulse rounded-lg bg-foreground/[0.04]" />
            ) : charges.data.length ? (
                <ul aria-label="Recent charges" className={'m-0 -mx-3 list-none p-0'}>
                    {charges.data.map((c) => (
                        <ChargeRow key={c.id ?? String(c.at)} charge={c} />
                    ))}
                </ul>
            ) : (
                <p className="m-0 text-[13px] text-muted-foreground">No charges yet.</p>
            )}
        </Section>
    );
}

function FreezeToggle({ card, onChanged }: { card: Card; onChanged: () => void }) {
    const [busy, setBusy] = useState(false);
    const frozen = card.status === 'frozen';
    const run = async () => {
        setBusy(true);
        try {
            await (frozen ? card.unfreeze() : card.freeze());
            onChanged();
            toast(frozen ? `${card.name} can pay again` : `Froze ${card.name}: every charge is declined until you unfreeze it`);
        } catch (e) {
            toast.error(errorText(e));
        } finally {
            setBusy(false);
        }
    };
    return (
        <ConsoleButton disabled={busy} icon={<Snowflake className="h-3.5 w-3.5" />} onClick={() => void run()}>
            {frozen ? 'Unfreeze' : 'Freeze'}
        </ConsoleButton>
    );
}

function CardDrawer({ cardId, row, onClose }: { cardId: string | null; row?: Card; onClose: () => void }) {
    const { client } = useConsole();
    const agents = useAgentNames();
    const href = useConsoleHref();
    const ownerCan = useOwnerOnly();
    const fetched = useV1(cardId && !row ? `cards/${cardId}` : null, () => Card.get(cardId!, { client }));
    // Actions change the card in place: keep that object over a refetched row, and re-render.
    const [updated, setUpdated] = useState<Card | null>(null);
    const [, setVersion] = useState(0);
    const card = (updated?.id === cardId ? updated : null) ?? row ?? fetched.data;
    const changed = () => {
        if (card) setUpdated(card);
        setVersion((v) => v + 1);
        invalidateV1('cards');
    };
    useEffect(() => {
        if (card) recordRecent({ type: 'card', id: card.id, label: `${card.name} card`, path: 'resources/cards', params: { card: card.id } });
    }, [card?.id]); // eslint-disable-line react-hooks/exhaustive-deps
    const open = card !== undefined && card.status !== 'closed';
    return (
        <Drawer
            open={cardId !== null}
            onOpenChange={(o) => !o && onClose()}
            kind="card"
            title={card?.name}
            id={cardId ?? undefined}
            status={card ? <StatusPill look={cardStatus(card)} /> : undefined}
            footer={
                open ? (
                    <>
                        {frozenForBalance(card) ? (
                            <Link to={href(CARD_PAGES.funding)} className={consoleButtonClass('soft')}>
                                Fund your cards
                            </Link>
                        ) : (
                            <FreezeToggle card={card} onChanged={changed} />
                        )}
                        <ConfirmAction
                            label="Close card"
                            title={`Close ${card.name}?`}
                            description="It declines every charge from now on, and its number is never reissued. Its charges stay listed."
                            confirmLabel="Close card"
                            onConfirm={async () => {
                                await card.close();
                                changed();
                                invalidateV1('account');
                            }}
                        />
                    </>
                ) : undefined
            }
        >
            {!card && fetched.error !== undefined && <ErrorPanel error={fetched.error} onRetry={() => void fetched.refresh()} />}
            {card && (
                <div className="flex flex-col gap-5">
                    {frozenForBalance(card) && (
                        <p className="m-0 flex items-start gap-2 text-[13px] text-muted-foreground">
                            <Snowflake aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0 text-foreground" />
                            <span>
                                <span className="font-medium text-foreground">Frozen: card balance below zero.</span> NoClick froze every card; this one pays again once the balance is funded.
                            </span>
                        </p>
                    )}
                    <dl className="m-0">
                        <Field label="Card">
                            <span className="font-mono text-[12px]">
                                {brandLabel(card.brand)} •••• {card.last4}
                            </span>
                            <span className="text-muted-foreground"> · expires {expiry(card)}</span>
                        </Field>
                        <Field label="User">{userLabel(card.userId)}</Field>
                        <Field label="Agent">
                            {card.agentId ? (
                                <Link to={href(`agents/${card.agentId}`)} className="underline-offset-2 hover:underline">
                                    {agents.get(card.agentId)?.name ?? card.agentId}
                                </Link>
                            ) : (
                                <span className="text-muted-foreground">No agent: your code pays with it</span>
                            )}
                        </Field>
                        <Field label="Issued">
                            <TimeCell value={card.createdAt} tier="absolute" />
                        </Field>
                    </dl>
                    <Section title="Limits">
                        <dl className="m-0">
                            <Field label="Limit">{limitLine(card.limitUsd, card.interval)}</Field>
                            <Field label={card.interval === 'transaction' ? 'Spent' : 'Spent so far'}>
                                <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
                                    <Spent card={card} className="min-w-[10rem]" />
                                    {card.resetsAt && (
                                        <span className="text-[12px] text-muted-foreground">
                                            Starts over <TimeCell value={card.resetsAt} />
                                        </span>
                                    )}
                                </span>
                            </Field>
                            <Field label="Merchants">
                                {card.merchants?.length ? (
                                    <span role="list" aria-label="Merchants" className="flex flex-wrap gap-1">
                                        {card.merchants.map((m) => (
                                            <span key={m} role="listitem" className="rounded bg-foreground/[0.06] px-1.5 py-[1px] text-[12px]">
                                                {merchantLabel(m)}
                                            </span>
                                        ))}
                                    </span>
                                ) : (
                                    <span className="text-muted-foreground">Any merchant</span>
                                )}
                            </Field>
                            <Field label="Numbers">
                                {card.singleUse ? 'A fresh number for every checkout, each taking one charge' : <span className="text-muted-foreground">One number, reused</span>}
                            </Field>
                            <Field label="Approval">
                                {card.requireApprovalAboveUsd != null ? (
                                    `Charges over ${dollars(card.requireApprovalAboveUsd)} wait for a person`
                                ) : (
                                    <span className="text-muted-foreground">Never asks</span>
                                )}
                            </Field>
                        </dl>
                        {open && (
                            <div className="mt-2">
                                <EditLimits card={card} onSaved={changed} />
                            </div>
                        )}
                    </Section>
                    <RecentCharges card={card} />
                    {open && (
                        <Section title="Card number">
                            {ownerCan('cardReveal') ? (
                                <>
                                    <p className="m-0 mb-2 text-[12px] text-muted-foreground">
                                        Agents pay without ever seeing the number. Reveal it only to pay with the card yourself; each reveal is audited.
                                    </p>
                                    <RevealDetails card={card} />
                                </>
                            ) : (
                                <OwnerOnlyNote what="cardReveal" />
                            )}
                        </Section>
                    )}
                </div>
            )}
        </Drawer>
    );
}

export function CardsPanel({ user, setUser }: PanelProps) {
    const { client } = useConsole();
    const agents = useAgentNames();
    const [cardId, setCard] = useSearchParam('card');
    const paged = usePaged(`cards?${user}`, (cursor) => Card.listPage({ client, userFilter: user, cursor, limit: 50 }), (c) => c.id);
    const columns: Column<Card>[] = [
        {
            id: 'card',
            header: 'Card',
            cell: (c) => (
                <span className="flex min-w-0 items-baseline gap-2">
                    <span className="min-w-0 truncate font-medium">{c.name}</span>
                    <span className="hidden shrink-0 font-mono text-[12px] text-muted-foreground sm:inline">•••• {c.last4}</span>
                </span>
            ),
        },
        { id: 'status', header: 'Status', width: '8rem', cell: (c) => <StatusPill look={cardStatus(c)} /> },
        { id: 'limit', header: 'Limit', priority: 2, width: '9rem', cell: (c) => <span className="whitespace-nowrap tabular-nums">{limitLine(c.limitUsd, c.interval)}</span> },
        { id: 'spent', header: 'Spent', align: 'right', width: '9.5rem', cell: (c) => <Spent card={c} className="w-full justify-end" /> },
        {
            id: 'agent',
            header: 'Agent',
            priority: 3,
            width: '8rem',
            cell: (c) => (c.agentId ? <span className="truncate">{agents.get(c.agentId)?.name ?? c.agentId}</span> : <span className="text-muted-foreground">No agent</span>),
        },
        {
            id: 'user',
            header: 'User',
            priority: 2,
            width: '8rem',
            cell: (c) => <span className={c.userId ? 'text-foreground/85' : 'text-muted-foreground'}>{userLabel(c.userId)}</span>,
        },
    ];
    return (
        <>
            <CardProgramGate>
                <FundingBanner />
            </CardProgramGate>
            <PanelToolbar
                user={user}
                setUser={setUser}
                action={<NewInCode kind="card" place={{ user: defaultWriteUser(user) }} />}
            />
            <DataTable
                rowMenu="card"
                label="Cards"
                columns={columns}
                rows={paged.rows}
                getRowId={(c) => c.id}
                loading={paged.loading}
                error={paged.error}
                onRetry={() => void paged.refresh()}
                onRowClick={(c) => setCard(c.id, { push: true })}
                selectedId={cardId}
                nextCursor={paged.nextCursor}
                onLoadMore={() => void paged.loadMore()}
                loadingMore={paged.loadingMore}
                empty={<EmptyCode title="No cards yet." hint="A virtual card with a limit, for an agent that has to buy something." snippet={NEW_SNIPPETS.card({ user: defaultWriteUser(user) })} />}
            />
            <CardDrawer cardId={cardId} row={paged.rows.find((c) => c.id === cardId)} onClose={() => setCard(null)} />
        </>
    );
}
