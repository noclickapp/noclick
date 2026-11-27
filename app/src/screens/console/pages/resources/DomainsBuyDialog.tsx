// Buying a domain: search a name, pick an offer and a term (the TLD's minimum to its
// maximum), set who it's registered to (with when they accepted the registration
// agreement, and, for a name with a trademark claims notice, that they saw it) and a
// ceiling on the price, then follow the purchase (approval when a policy holds it,
// registering, configuring DNS, active). It's always charged to your account: a user's
// domain is registered to them with the details entered here, and one the account buys
// for itself uses the account's default registrant or details entered here. The
// registrant form and the progress steps are shared with transferring a domain in.
import { useEffect, useState, type ReactNode } from 'react';
import { toast } from 'sonner';
import { HAIRLINE } from '@/ui/primitives';
import { EMPTY_REGISTRANT, REGISTRANT_FIELDS, registrantFrom, type RegistrantDraft } from '@/lib/domainRegistrant';
import { cn } from '@/ui/utils';
import { Checkbox } from '@/ui/checkbox';
import { FieldSelect } from '@/ui/FieldSelect';
import { Domain, type DomainContact, type DomainOffer, type DomainPurchase } from 'noclick';
import { formatMoneyFull } from '@/screens/console/lib/format';
import type { StatusLook } from '@/screens/console/lib/status';
import { useConsole } from '@/screens/console/hooks/useConsole';
import { BACKSTOP_POLL_MS } from '@/sdk/staleReads';
import { invalidateV1, useV1 } from '@/sdk/useV1';
import { useOwnerAccepts } from '@/sdk/client';
import { ConsoleButton } from '../../ui/Button';
import { ConsoleDialog } from '../../ui/ConsoleDialog';
import { ErrorPanel } from '../../ui/ErrorPanel';
import { Money } from '../../ui/Money';
import { Segmented } from '../../ui/Segmented';
import { StatusPill } from '../../ui/StatusPill';
import { UserField } from '../../ui/UserField';
import { INPUT, LabeledInput } from './shared';
import { BADGE, Notice, dayLabel, everyLabel, yearsLabel } from './DomainsParts';

/** The lab has no relay, so no frame says a purchase moved: it reads its fixture's progress this often. */
const LAB_PROGRESS_POLL_MS = 1000;

/** Who it's registered to: details entered now, or the account's default registrant. */
type Who = 'now' | 'account';

/** The terms the offer's TLD registers for, from its minimum to its maximum. */
function termsOf(offer: DomainOffer): number[] {
    const min = offer.minYears ?? 1;
    return Array.from({ length: (offer.maxYears ?? min) - min + 1 }, (_, i) => min + i);
}

/** What `years` costs now: `priceUsd` buys the minimum term, and a longer one is estimated from its renewals. */
function totalFor(offer: DomainOffer, years: number): number | null {
    if (offer.priceUsd == null) return null;
    const min = offer.minYears ?? 1;
    return Math.round((offer.priceUsd + ((offer.renewalUsd ?? offer.priceUsd) * (years - min)) / min) * 100) / 100;
}

export interface Step {
    status: string;
    label: string;
    detail: string | null;
}

/** Only a purchase your policy holds waits on this first. */
const APPROVAL: Step = { status: 'awaiting_human', label: 'Awaiting approval', detail: "Your policy holds purchases for a person to approve; it's charged once they do." };
const BUY_STEPS: readonly Step[] = [
    { status: 'registering', label: 'Registering', detail: "With the registry, in the registrant's name; charged to your account once it confirms." },
    { status: 'pending_dns', label: 'Configuring DNS', detail: 'The bare name and www, ready for an app or an inbox.' },
    { status: 'active', label: 'Active', detail: null },
];

function stepIndex(steps: readonly Step[], status: string | undefined): number {
    if (status === 'active' || status === 'registrant_unverified') return steps.length;
    const i = steps.findIndex((s) => s.status === status);
    return i < 0 ? 0 : i;
}

function stepLook(label: string, at: number, i: number, waiting: boolean): StatusLook {
    if (i < at) return { label, glyph: 'check', tone: 'ink' };
    if (i === at) return { label, glyph: waiting ? 'waiting' : 'filled', tone: 'ink' };
    return { label, glyph: 'hollow', tone: 'muted' };
}

/**
 * A purchase (or a transfer in) after it's placed: its steps and the outcome. `label` names the
 * steps' list; `failed` says what a failure means.
 */
export function PurchaseProgress({
    purchase,
    name,
    steps: tail = BUY_STEPS,
    label = 'Purchase progress',
    failed = `Registering ${name} failed, and nothing was charged.`,
}: {
    purchase: DomainPurchase;
    name: string;
    steps?: readonly Step[];
    label?: string;
    failed?: string;
}) {
    const { client, lab } = useConsole();
    const [finished, setFinished] = useState(false);
    // A platform:resource frame re-reads it as it moves (ConsoleProviders); the backstop only while frames are missed.
    const domain = useV1(purchase.domainId ? `domains/${purchase.domainId}` : null, () => Domain.get(purchase.domainId!, { client }), {
        pollMs: !finished && lab ? LAB_PROGRESS_POLL_MS : undefined,
        backstopMs: finished ? undefined : BACKSTOP_POLL_MS,
    });
    const status = domain.data?.status ?? purchase.status;
    const steps = purchase.status === 'awaiting_human' ? [APPROVAL, ...tail] : tail;
    const at = status === 'failed' ? -1 : stepIndex(steps, status);
    const ended = at === steps.length || status === 'failed';
    useEffect(() => {
        if (!ended) return;
        setFinished(true);
        invalidateV1('domains?');
        invalidateV1('account');
    }, [ended]);
    return (
        <div className="flex flex-col gap-4">
            <ol aria-label={label} className="m-0 flex list-none flex-col gap-3 p-0">
                {steps.map((step, i) => (
                    <li key={step.status} className="flex flex-col gap-0.5">
                        <StatusPill look={stepLook(step.label, at, i, step === APPROVAL)} />
                        {i === at && step.detail && <span className="pl-[18px] text-[12px] text-muted-foreground">{step.detail}</span>}
                    </li>
                ))}
            </ol>
            {status === 'failed' && <ErrorPanel error={new Error(failed)} />}
            {at === steps.length && domain.data && (
                <p className="m-0 text-[13px] text-muted-foreground">
                    {name} is registered until {dayLabel(domain.data.expiresAt)}.
                    {domain.data.status === 'registrant_unverified' && domain.data.registrantEmail
                        ? ` ${domain.data.registrantEmail} has been emailed a link to confirm the registrant's address; the domain works meanwhile.`
                        : null}
                </p>
            )}
            {domain.error !== undefined && <ErrorPanel error={domain.error} onRetry={() => void domain.refresh()} />}
        </div>
    );
}

/**
 * Who a domain is registered to, for buying or transferring one in: details entered here, with when
 * they accepted the registration agreement, or for the account's own domain its default registrant.
 * `registrant` is undefined when the default is used; `ready` once there's someone to register it to
 * who has accepted the agreement.
 */
export function useRegistrant(active: boolean, user: string | null): { registrant: DomainContact | undefined; ready: boolean; reset: () => void; fields: ReactNode } {
    const { client, now } = useConsole();
    // A key NoClick gave this app never accepts terms for a person: the account's owner does, approving the call.
    const ownerAccepts = useOwnerAccepts();
    const [who, setWho] = useState<Who>('now');
    const [contact, setContact] = useState<RegistrantDraft>(EMPTY_REGISTRANT);
    // When the box was ticked: the registrant's acceptance of the agreement, sent with their details.
    const [acceptedAt, setAcceptedAt] = useState<Date | null>(null);
    const agreement = useV1(active ? 'domains/agreement' : null, () => Domain.agreement({ client }));
    // An account purchase that names no registrant uses the default (with none, the API refuses it); a
    // user's domain is registered to them, so it always takes their details.
    const accountDefault = useV1(active && user === null ? 'domains/registrant' : null, () => Domain.defaultRegistrant({ client }));
    const hasDefault = user === null && !!accountDefault.data;
    const choice: Who = who === 'account' && hasDefault ? 'account' : 'now';
    const whoOptions: { value: Who; label: string }[] = hasDefault
        ? [
              { value: 'account', label: "Your account's registrant" },
              { value: 'now', label: 'Enter their details' },
          ]
        : [];
    const registrant = choice === 'now' ? registrantFrom(contact) : null;
    const fields = (
        <div className="flex flex-col gap-2">
            <span className="text-[12px] font-medium text-muted-foreground">Registrant</span>
            {whoOptions.length > 0 && <Segmented label="Registrant" options={whoOptions} value={choice} onChange={(v) => setWho(v)} className="self-start" />}
            {user === null && accountDefault.data === null && (
                <p className="m-0 text-[12px] text-muted-foreground">
                    Buying for your account often? Set its registrant once with{' '}
                    <span className="font-mono text-foreground/85">noclick.Domain.set_default_registrant(...)</span> and your account&apos;s purchases need no details.
                </p>
            )}
            {choice === 'account' && accountDefault.data ? (
                <p className="m-0 text-[13px] text-muted-foreground">
                    Registered to <span className="text-foreground">{accountDefault.data.organization ?? accountDefault.data.name}</span> ({accountDefault.data.email}), your
                    account&apos;s default registrant, and charged to your account.{' '}
                    {accountDefault.data.agreementAcceptedAt
                        ? `They accepted the registration agreement on ${dayLabel(accountDefault.data.agreementAcceptedAt)}.`
                        : "It records no acceptance of the registration agreement, so the API refuses purchases with it until it's set again with agreement_accepted_at."}
                </p>
            ) : (
                <div className="grid gap-3 sm:grid-cols-2">
                    {REGISTRANT_FIELDS.map((f) => (
                        <div key={f.key} className={f.wide ? 'sm:col-span-2' : undefined}>
                            <LabeledInput label={f.label} id={`registrant-${f.key}`}>
                                <input
                                    id={`registrant-${f.key}`}
                                    className={INPUT}
                                    value={contact[f.key]}
                                    placeholder={f.placeholder}
                                    onChange={(e) => setContact((c) => ({ ...c, [f.key]: e.target.value }))}
                                />
                            </LabeledInput>
                        </div>
                    ))}
                    <p className="m-0 text-[12px] text-muted-foreground sm:col-span-2">
                        {user !== null ? "A user's domain is registered to them, so these are their details. " : 'The person the domain belongs to. '}
                        ICANN requires real details and emails them to confirm; privacy protection keeps them off the public record.
                    </p>
                    {ownerAccepts ? (
                        <p className="m-0 text-[13px] sm:col-span-2" data-testid="owner-accepts-agreement">
                            The account&apos;s owner accepts{' '}
                            {agreement.data ? (
                                <a href={agreement.data.url} target="_blank" rel="noreferrer" className="text-foreground underline underline-offset-2">
                                    the registration agreement
                                </a>
                            ) : (
                                'the registration agreement'
                            )}{' '}
                            for them when they approve it.
                        </p>
                    ) : (
                        <div className="flex flex-col gap-1 sm:col-span-2">
                            <label className="flex items-start gap-2.5 text-[13px]">
                                <Checkbox className="mt-0.5" checked={acceptedAt !== null} onCheckedChange={(on) => setAcceptedAt(on === true ? new Date(now()) : null)} />
                                <span>They accepted the domain registration agreement</span>
                            </label>
                            <p className="m-0 pl-[26px] text-[12px] text-muted-foreground">
                                Show them{' '}
                                {agreement.data ? (
                                    <a href={agreement.data.url} target="_blank" rel="noreferrer" className="text-foreground underline underline-offset-2">
                                        the registration agreement
                                    </a>
                                ) : (
                                    'the registration agreement'
                                )}{' '}
                                first: it names the registrar, and carries the fees and ICANN&apos;s registrant rights. Ticking this records when they accepted it, and
                                nothing is registered without it.
                            </p>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
    return {
        registrant: registrant && ownerAccepts ? registrant : registrant && acceptedAt ? { ...registrant, agreementAcceptedAt: acceptedAt } : undefined,
        ready: choice === 'account' ? !!accountDefault.data?.agreementAcceptedAt : registrant !== null && (ownerAccepts || acceptedAt !== null),
        reset: () => {
            setWho('now');
            setContact(EMPTY_REGISTRANT);
            setAcceptedAt(null);
        },
        fields,
    };
}

export function BuyDomainDialog({ defaultUser, onOpenDomain }: { defaultUser: string | null; onOpenDomain: (id: string) => void }) {
    const { client } = useConsole();
    const [open, setOpen] = useState(false);
    const [query, setQuery] = useState('');
    const [offers, setOffers] = useState<DomainOffer[] | null>(null);
    const [picked, setPicked] = useState<DomainOffer | null>(null);
    const [user, setUser] = useState<string | null>(defaultUser);
    const [years, setYears] = useState(1);
    const [max, setMax] = useState('');
    // The registrant saw the offer's trademark claims notice and still wants the name.
    const [acceptClaims, setAcceptClaims] = useState(false);
    const [purchase, setPurchase] = useState<DomainPurchase | null>(null);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>(undefined);
    const reg = useRegistrant(open && !!picked, user);
    const ownerAccepts = useOwnerAccepts();

    const start = () => {
        setQuery('');
        setOffers(null);
        setPicked(null);
        setUser(defaultUser);
        setYears(1);
        reg.reset();
        setPurchase(null);
        setError(undefined);
        setOpen(true);
    };
    const pick = (offer: DomainOffer | null) => {
        const term = offer?.minYears ?? 1;
        setPicked(offer);
        setYears(term);
        setAcceptClaims(false);
        setError(undefined);
        const total = offer ? totalFor(offer, term) : null;
        setMax(total != null ? String(total) : '');
    };
    const search = async () => {
        setBusy(true);
        setError(undefined);
        try {
            setOffers(await Domain.search(query.trim(), { client, user: null }));
        } catch (e) {
            setError(e);
        } finally {
            setBusy(false);
        }
    };
    const maxValid = max.trim() !== '' && Number(max) > 0;
    const buy = async () => {
        if (!picked) return;
        setBusy(true);
        setError(undefined);
        try {
            setPurchase(await Domain.buy(picked, { client, user, years, maxPriceUsd: Number(max), registrant: reg.registrant, acceptClaims: !ownerAccepts && acceptClaims }));
            invalidateV1('domains?');
        } catch (e) {
            setError(e);
        } finally {
            setBusy(false);
        }
    };
    const total = picked ? totalFor(picked, years) : null;
    const minYears = picked?.minYears ?? 1;
    const claimsPending = !!picked?.claimsNotice && !ownerAccepts && !acceptClaims;

    const title = purchase ? `Buying ${picked?.name}` : picked ? `Buy ${picked.name}` : 'Buy a domain';
    const description = purchase
        ? "Registered in the person's name."
        : picked
          ? "Charged to your account, whoever it's for."
          : "Search for a name. Prices are for each name's shortest term, in US dollars.";
    const footer = purchase ? (
        <>
            {purchase.domainId && (
                <ConsoleButton
                    variant="ghost"
                    onClick={() => {
                        setOpen(false);
                        onOpenDomain(purchase.domainId!);
                    }}
                >
                    View domain
                </ConsoleButton>
            )}
            <ConsoleButton
                variant="primary"
                onClick={() => {
                    setOpen(false);
                    toast(`Buying ${picked?.name}`);
                }}
            >
                Done
            </ConsoleButton>
        </>
    ) : picked ? (
        <>
            <ConsoleButton variant="ghost" onClick={() => pick(null)}>
                Back
            </ConsoleButton>
            <ConsoleButton variant="primary" disabled={busy || !maxValid || !reg.ready || claimsPending} onClick={() => void buy()}>
                {busy ? 'Buying…' : 'Buy domain'}
            </ConsoleButton>
        </>
    ) : (
        <ConsoleButton variant="primary" disabled={busy || !query.trim()} onClick={() => void search()}>
            {busy ? 'Searching…' : 'Search'}
        </ConsoleButton>
    );

    return (
        <>
            <ConsoleButton variant="primary" onClick={start}>
                Buy a domain
            </ConsoleButton>
            <ConsoleDialog open={open} onOpenChange={setOpen} size={picked && !purchase ? 'lg' : 'md'} title={title} description={description} footer={footer}>
                {purchase && picked ? (
                    <PurchaseProgress purchase={purchase} name={picked.name} />
                ) : picked ? (
                    <div className="flex flex-col gap-4">
                        <div className="grid gap-3 sm:grid-cols-2">
                            <UserField value={user} onChange={setUser} />
                            <LabeledInput label="Years" id="domain-years">
                                <FieldSelect
                                    id="domain-years"
                                    value={String(years)}
                                    onValueChange={(v) => {
                                        const next = Number(v);
                                        setYears(next);
                                        const t = totalFor(picked, next);
                                        setMax(t != null ? String(t) : '');
                                    }}
                                    options={termsOf(picked).map((y) => ({ value: String(y), label: y === 1 ? '1 year' : `${y} years` }))}
                                />
                            </LabeledInput>
                        </div>
                        <div className="flex flex-col gap-1.5">
                            <LabeledInput label="Most you'll pay now (USD)" id="domain-max">
                                <input id="domain-max" inputMode="decimal" className={cn(INPUT, 'sm:w-48')} value={max} onChange={(e) => setMax(e.target.value)} />
                            </LabeledInput>
                            <p className="m-0 text-[12px] text-muted-foreground">
                                {total != null &&
                                    (years === minYears ? (
                                        <>
                                            {formatMoneyFull(total)} now for {yearsLabel(years)},{' '}
                                        </>
                                    ) : (
                                        <>
                                            About {formatMoneyFull(total)} now for {yearsLabel(years)} (an estimate from the renewal price),{' '}
                                        </>
                                    ))}
                                then <Money usd={picked.renewalUsd} full /> {everyLabel(minYears)}.{' '}
                                The purchase is refused if it costs more than your ceiling. NoClick checks your account can pay before registering and charges it when
                                the registry confirms; a registration that fails is never charged.
                            </p>
                        </div>
                        {picked.claimsNotice && (
                            <Notice title="Trademark claims notice">
                                <p className="m-0 mb-1">Show the registrant this notice before buying: the name matches a registered trademark.</p>
                                <p className={cn('m-0 max-h-48 overflow-y-auto whitespace-pre-wrap rounded-md border bg-foreground/[0.03] p-2 text-[12px]', HAIRLINE)}>
                                    {picked.claimsNotice}
                                </p>
                                {ownerAccepts && <p className="m-0 mt-2 text-[13px] text-foreground">The account&apos;s owner reads it and accepts it when they approve the purchase.</p>}
                            </Notice>
                        )}
                        {picked.claimsNotice && !ownerAccepts && (
                            <label className="flex items-start gap-2.5 text-[13px] text-foreground">
                                <Checkbox className="mt-0.5" checked={acceptClaims} onCheckedChange={(on) => setAcceptClaims(on === true)} />
                                <span>They&apos;ve seen this notice and still want the name</span>
                            </label>
                        )}
                        {reg.fields}
                        {error !== undefined && <ErrorPanel error={error} />}
                    </div>
                ) : (
                    <div className="flex flex-col gap-3">
                        <form
                            onSubmit={(e) => {
                                e.preventDefault();
                                if (query.trim()) void search();
                            }}
                        >
                            <LabeledInput label="Name or word" id="domain-query">
                                <input id="domain-query" className={INPUT} value={query} onChange={(e) => setQuery(e.target.value)} placeholder="acmebooking" />
                            </LabeledInput>
                        </form>
                        {offers && !offers.length && <p className="m-0 text-[13px] text-muted-foreground">No names match. Try another word.</p>}
                        {offers && offers.length > 0 && (
                            <ul aria-label="Domains for sale" className={cn('m-0 list-none rounded-lg border p-0', HAIRLINE)}>
                                {offers.map((o) => (
                                    <li key={o.name}>
                                        <button
                                            type="button"
                                            disabled={!o.available}
                                            onClick={() => pick(o)}
                                            className="flex w-full items-center gap-3 px-3 py-2 text-left text-[13px] transition-colors hover:bg-foreground/[0.04] disabled:cursor-default disabled:hover:bg-transparent"
                                        >
                                            <span className={cn('min-w-0 flex-1 truncate font-mono text-[12px]', !o.available && 'text-muted-foreground line-through decoration-foreground/30')}>
                                                {o.name}
                                            </span>
                                            {o.premium && <span className={BADGE}>Premium</span>}
                                            {o.claimsNotice && <span className={BADGE}>Trademark</span>}
                                            {o.available ? (
                                                <span className="flex shrink-0 flex-col items-end leading-tight">
                                                    <Money usd={o.priceUsd} className="text-foreground" />
                                                    <span className="text-[12px] text-muted-foreground">
                                                        {o.minYears !== null && o.minYears > 1 && `${o.minYears} yrs, `}then <Money usd={o.renewalUsd} />
                                                        {o.minYears !== null && o.minYears > 1 ? `/${o.minYears} yrs` : '/yr'}
                                                    </span>
                                                </span>
                                            ) : (
                                                <span className="shrink-0 text-[12px] text-muted-foreground">Taken</span>
                                            )}
                                        </button>
                                    </li>
                                ))}
                            </ul>
                        )}
                        {error !== undefined && <ErrorPanel error={error} />}
                    </div>
                )}
            </ConsoleDialog>
        </>
    );
}
