// Buying a domain by hand, as a page one level under Domains: search a name,
// see which endings are free and what each costs, then check out one: its
// price and term, who it's registered to (the account's registrant on file,
// or details entered here with the registration agreement accepted), a
// trademark notice when the name has one, and one button with the price on
// it. Nothing is charged before that button, and nothing above its price.
// Once it's bought, an account with websites may put one there, or not yet.
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react';
import { Link } from 'react-router';
import { toast } from 'sonner';
import { ExternalLink, Globe, Loader2, Search } from 'lucide-react';
import { Checkbox } from '~/components/ui/checkbox';
import { Skeleton } from '~/components/ui/skeleton';
import { EMPTY_REGISTRANT, REGISTRANT_FIELDS, registrantFrom, withKnown, type RegistrantDraft } from '~/lib/domainRegistrant';
import {
    parseDomainQuery,
    useDomainPurchase,
    type DomainCheckout,
    type DomainOffer,
    type DomainPurchaseDetails,
    type DomainPurchaseError,
    type DomainRegistrar,
    type DomainSearch,
} from '~/hooks/useDomainPurchase';
import { formatDollars } from '~/lib/money';
import { cn } from '~/lib/utils';
import { BUTTON_PRIMARY, BUTTON_SECONDARY } from '../buttons';
import { FIELD, FIELD_LABEL, QUIET_LINK } from '../fields';
import { PageFrame } from '../PageFrame';
import { usePlatformResources } from './platform';
import { Section, Surface } from './ui';
import { UseBoughtDomain } from './UseForWebsite';

/** "a year", "2 years". */
const term = (years: number) => (years === 1 ? 'a year' : `${years} years`);

/** What an offer costs, in a few words: "$12.99 a year", "$140.00 for 2 years". */
export function offerPrice(offer: Pick<DomainOffer, 'priceUsd' | 'years'>): string {
    return offer.years === 1 ? `${formatDollars(offer.priceUsd)} a year` : `${formatDollars(offer.priceUsd)} for ${offer.years} years`;
}

function DomainRow({ offer, busy, onBuy }: { offer: DomainOffer; busy: boolean; onBuy: () => void }) {
    return (
        <div className="flex items-center gap-3.5 px-4 py-3.5 sm:px-5" data-testid="available-domain">
            <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-foreground/[0.05]">
                <Globe className="h-[18px] w-[18px] text-foreground/75" strokeWidth={1.75} />
            </span>
            <div className="min-w-0 flex-1">
                <p className="truncate text-[15px] font-medium text-foreground">{offer.domain}</p>
                <p className="mt-0.5 truncate text-[12.5px] text-muted-foreground">
                    {[offerPrice(offer), offer.premium && 'Premium', offer.claimsNotice && 'Trademark notice', offer.close && 'A close name'].filter(Boolean).join(' · ')}
                </p>
            </div>
            <button type="button" onClick={onBuy} disabled={busy} className={cn(BUTTON_SECONDARY, 'h-8 px-3.5 text-[13px]')}>
                Buy
            </button>
        </div>
    );
}

/** Why the domain asked for isn't in the list, when it isn't. */
function AskedLine({ asked, owned, onOpen }: { asked: DomainSearch['asked']; owned: boolean; onOpen: (domain: string) => void }) {
    if (asked.status === 'available' && !owned) return null;
    return (
        <p className="mb-3 text-[13.5px] text-muted-foreground" data-testid="asked-domain">
            <span className="text-foreground">{asked.domain}</span>{' '}
            {owned ? (
                <>
                    is already yours.
                    <button type="button" onClick={() => onOpen(asked.domain)} className="ml-1.5 font-medium text-foreground underline underline-offset-4">
                        Open it
                    </button>
                </>
            ) : asked.status === 'taken' ? (
                'is taken.'
            ) : (
                'isn’t available.'
            )}
        </p>
    );
}

function ErrorLine({ error }: { error: DomainPurchaseError }) {
    return (
        <p role="alert" className="mb-3 text-[13.5px] text-red-600 dark:text-red-400">
            {error.text}
            {error.kind === 'credits' && (
                <Link to="/dashboard?action=topup" className="ml-1.5 font-medium text-foreground underline underline-offset-4">
                    Top up
                </Link>
            )}
        </p>
    );
}

function Agreed({ id, checked, onChange, children }: { id: string; checked: boolean; onChange: (checked: boolean) => void; children: ReactNode }) {
    return (
        <div className="flex items-start gap-2.5">
            <Checkbox id={id} checked={checked} onCheckedChange={(v) => onChange(v === true)} className="mt-0.5 rounded-[5px]" />
            <label htmlFor={id} className="text-[13.5px] leading-snug text-foreground">
                {children}
            </label>
        </div>
    );
}

/** One offer, before it's bought: its price, who it's registered to and, for a name with one, its trademark notice. */
function Checkout({
    offer,
    checkout,
    buying,
    error,
    onBuy,
    onBack,
}: {
    offer: DomainOffer;
    checkout: DomainCheckout | null;
    buying: boolean;
    error: DomainPurchaseError | null;
    onBuy: (details: DomainPurchaseDetails) => void;
    onBack: () => void;
}) {
    const [other, setOther] = useState(false);
    const [draft, setDraft] = useState<RegistrantDraft>(EMPTY_REGISTRANT);
    // What NoClick knows of the owner (name, email, number) starts the details, whenever the checkout lands.
    const known = checkout?.known;
    useEffect(() => {
        if (known) setDraft((d) => withKnown(d, known));
    }, [known]);
    // When the box was ticked: the registrant's acceptance of the agreement, sent with their details.
    const [acceptedAt, setAcceptedAt] = useState<Date | null>(null);
    const [claims, setClaims] = useState(false);
    const onFile = !other ? (checkout?.onFile ?? null) : null;
    const contact = registrantFrom(draft);
    const registrantReady = onFile !== null || (contact !== null && acceptedAt !== null);
    const ready = !!checkout && registrantReady && (!offer.claimsNotice || claims);
    const price = formatDollars(offer.priceUsd);
    const renews = offer.renewalUsd != null ? `It renews at ${formatDollars(offer.renewalUsd)} ${offer.years === 1 ? 'a year' : `every ${offer.years} years`} until you turn renewal off.` : null;

    const submit = (e: FormEvent) => {
        e.preventDefault();
        if (!ready) return;
        onBuy({ registrant: onFile ? undefined : { ...contact!, agreementAcceptedAt: acceptedAt! }, acceptClaims: claims });
    };

    return (
        <form onSubmit={submit} className="max-w-2xl" aria-label={`Buy ${offer.domain}`}>
            <div>
                <p className="text-[30px] font-semibold tabular-nums tracking-[-0.02em] text-foreground">{price}</p>
                <p className="mt-1 text-[14px] leading-relaxed text-muted-foreground">
                    For {term(offer.years)}, charged once the registry confirms it, and never more than this. {renews}
                    {offer.premium && ' A premium name: its registry prices it above the usual rate.'}
                </p>
            </div>

            <Section title="Registered to">
                {!checkout ? (
                    !error && (
                        <div aria-busy className="space-y-2">
                            <Skeleton className="h-4 w-2/3" />
                            <Skeleton className="h-4 w-1/3" />
                        </div>
                    )
                ) : onFile ? (
                    <p className="text-[14px] leading-relaxed text-foreground" data-testid="registrant-on-file">
                        {onFile.organization ?? onFile.name} ({onFile.email}), your account’s registrant.{' '}
                        <button type="button" onClick={() => setOther(true)} className={cn(QUIET_LINK, 'inline underline underline-offset-4')}>
                            Use other details
                        </button>
                    </p>
                ) : (
                    <div className="space-y-5">
                        <div className="grid gap-x-4 gap-y-4 sm:grid-cols-2">
                            {REGISTRANT_FIELDS.map((f) => (
                                <div key={f.key} className={f.wide ? 'sm:col-span-2' : undefined}>
                                    <label htmlFor={`registrant-${f.key}`} className={FIELD_LABEL}>
                                        {f.label}
                                    </label>
                                    <input
                                        id={`registrant-${f.key}`}
                                        className={FIELD}
                                        value={draft[f.key]}
                                        placeholder={f.placeholder}
                                        autoComplete={f.autoComplete}
                                        onChange={(e) => setDraft((d) => ({ ...d, [f.key]: e.target.value }))}
                                    />
                                </div>
                            ))}
                        </div>
                        <p className="text-[13px] leading-relaxed text-muted-foreground">
                            The person or company the domain belongs to. ICANN requires real details and emails a link to confirm the address; privacy protection keeps them
                            off the public record.
                            {checkout.onFile && (
                                <>
                                    {' '}
                                    <button type="button" onClick={() => setOther(false)} className={cn(QUIET_LINK, 'inline underline underline-offset-4')}>
                                        Use your account’s registrant
                                    </button>
                                </>
                            )}
                        </p>
                        <Agreed id="registrant-agreement" checked={acceptedAt !== null} onChange={(on) => setAcceptedAt(on ? new Date() : null)}>
                            I accept the{' '}
                            <a href={checkout.agreementUrl} target="_blank" rel="noreferrer" className="font-medium underline underline-offset-4">
                                domain registration agreement
                                <ExternalLink className="ml-0.5 inline h-3 w-3 align-baseline" />
                            </a>
                        </Agreed>
                    </div>
                )}
            </Section>

            {offer.claimsNotice && (
                <Section title="Trademark notice">
                    <p className="mb-3 text-[13.5px] text-muted-foreground">This name matches a registered trademark. Read the notice before buying it.</p>
                    <div className="max-h-56 overflow-y-auto whitespace-pre-wrap rounded-xl bg-foreground/[0.04] px-4 py-3 text-[13px] leading-relaxed text-foreground/85">{offer.claimsNotice}</div>
                    <div className="mt-3">
                        <Agreed id="claims-notice" checked={claims} onChange={setClaims}>
                            I’ve read the notice and still want {offer.domain}
                        </Agreed>
                    </div>
                </Section>
            )}

            <div className="mt-10">
                {error && <ErrorLine error={error} />}
                <div className="flex flex-wrap items-center gap-2">
                    <button type="submit" disabled={!ready || buying} className={BUTTON_PRIMARY}>
                        {buying && <Loader2 className="h-4 w-4 animate-spin" />}
                        Buy for {price}
                    </button>
                    <button type="button" onClick={onBack} disabled={buying} className={BUTTON_SECONDARY}>
                        Back
                    </button>
                </div>
            </div>
        </form>
    );
}

/**
 * Searching a name, its free endings and their prices, and checking one out: the page's body and the chat's domain
 * card's. `children` frames it: given the body and the offer being checked out (null while searching) with the way
 * back to the search.
 */
export function DomainFinder({
    registrar,
    seed,
    owned = [],
    limit,
    onBought,
    onOpen,
    children,
}: {
    /** Where searches and purchases go; tests pass their own. */
    registrar: DomainRegistrar;
    /** A name to open on, so it starts with endings to choose from. */
    seed?: string;
    /** The domains already yours, never offered again. */
    owned?: string[];
    /** At most this many offers (a card's room). */
    limit?: number;
    onBought: (domain: string) => void;
    /** Opens a domain that's already yours. */
    onOpen: (domain: string) => void;
    children: (body: ReactNode, picked: DomainOffer | null, unpick: () => void) => ReactNode;
}) {
    const [text, setText] = useState(seed ?? '');
    const input = useRef<HTMLInputElement>(null);
    const purchase = useDomainPurchase({
        registrar,
        onBought: (offer) => {
            toast.success(`Buying ${offer.domain}`, { description: 'It’s yours once the registry confirms, usually within a minute.' });
            onBought(offer.domain);
        },
    });
    const { searched, result, searching, picked, checkout, buying, busy, error, search, pick } = purchase;

    useEffect(() => {
        if (seed) void search(seed);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    const run = (query: string) => void search(query);
    const onSubmit = (e: FormEvent) => {
        e.preventDefault();
        run(text);
    };
    // An ending chip searches the name you're on, with that ending first.
    const pickEnding = (ending: string) => {
        const name = parseDomainQuery(text)?.name ?? searched?.name;
        if (!name) {
            input.current?.focus();
            return;
        }
        setText(`${name}.${ending}`);
        run(`${name}.${ending}`);
    };
    const offers = (result?.offers.filter((o) => !owned.includes(o.domain)) ?? []).slice(0, limit);
    const unpick = () => void pick(null);

    if (picked) {
        return children(
            <Checkout key={picked.domain} offer={picked} checkout={checkout} buying={buying} error={error} onBuy={(details) => void purchase.buy(details)} onBack={unpick} />,
            picked,
            unpick
        );
    }

    return children(
        <>
            {error?.kind === 'unavailable' ? (
                <div className="flex flex-col items-center px-6 py-16 text-center" data-testid="domains-unavailable">
                    <span className="grid h-11 w-11 place-items-center rounded-full bg-foreground/[0.05]">
                        <Globe className="h-5 w-5 text-foreground/70" strokeWidth={1.75} />
                    </span>
                    <p className="mt-4 text-[15px] font-semibold text-foreground">Domains aren’t available here</p>
                    <p className="mt-1 max-w-sm text-balance text-[14px] leading-relaxed text-muted-foreground">{error.text}</p>
                </div>
            ) : (
                <>
                    <form onSubmit={onSubmit} className="flex max-w-xl items-center gap-2">
                        <label className="relative min-w-0 flex-1">
                            <Search className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                            <input
                                ref={input}
                                value={text}
                                onChange={(e) => setText(e.target.value.slice(0, 80))}
                                placeholder="A name or a domain, like acme or acme.ai"
                                aria-label="The domain or name to search for"
                                autoCapitalize="none"
                                autoCorrect="off"
                                spellCheck={false}
                                className="h-10 w-full rounded-full border border-border bg-transparent pl-10 pr-4 text-[14.5px] text-foreground outline-none transition-colors placeholder:text-[hsl(var(--placeholder))] focus:border-foreground/25 dark:border-foreground/[0.1]"
                            />
                        </label>
                        <button type="submit" disabled={busy} className={cn(BUTTON_PRIMARY, 'h-10 px-5')}>
                            {searching && <Loader2 className="h-4 w-4 animate-spin" />}
                            Search
                        </button>
                    </form>
                    <div className="-mx-5 mt-3 flex gap-1.5 overflow-x-auto px-5 scrollbar-hide sm:mx-0 sm:flex-wrap sm:overflow-visible sm:px-0" aria-label="Endings">
                        {registrar.endings.slice(0, 8).map((ending) => {
                            const on = searched?.ending === ending;
                            return (
                                <button
                                    key={ending}
                                    type="button"
                                    disabled={busy}
                                    onClick={() => pickEnding(ending)}
                                    className={cn(
                                        'inline-flex h-8 shrink-0 items-center rounded-full px-3 text-[13px] transition-colors disabled:opacity-60',
                                        on ? 'bg-primary text-primary-foreground' : 'bg-secondary text-foreground/85 hover:bg-accent dark:bg-foreground/[0.06] dark:hover:bg-foreground/[0.1]'
                                    )}
                                >
                                    .{ending}
                                </button>
                            );
                        })}
                    </div>

                    <Section title="Available" meta={offers.length || undefined}>
                        {error && <ErrorLine error={error} />}
                        {result && !searching && <AskedLine asked={result.asked} owned={owned.includes(result.asked.domain)} onOpen={onOpen} />}
                        {searching && result === null ? (
                            <Surface className="divide-y divide-border dark:divide-foreground/[0.06]">
                                {[0, 1, 2, 3].map((i) => (
                                    <div key={i} className="flex items-center gap-3.5 px-4 py-3.5 sm:px-5">
                                        <Skeleton className="h-10 w-10 rounded-xl" />
                                        <div className="flex-1 space-y-1.5">
                                            <Skeleton className="h-3.5 w-36" />
                                            <Skeleton className="h-3 w-24" />
                                        </div>
                                    </div>
                                ))}
                            </Surface>
                        ) : result && offers.length > 0 ? (
                            <Surface className={cn('divide-y divide-border transition-opacity dark:divide-foreground/[0.06]', searching && 'opacity-60')}>
                                {offers.map((offer) => (
                                    <DomainRow key={offer.domain} offer={offer} busy={busy} onBuy={() => void pick(offer)} />
                                ))}
                            </Surface>
                        ) : result ? (
                            <p className="py-10 text-center text-[14px] text-muted-foreground">Nothing is free for “{searched?.name}”. Try another name.</p>
                        ) : (
                            !searching && <p className="py-10 text-center text-[14px] text-muted-foreground">Search a name to see which endings are free.</p>
                        )}
                    </Section>
                </>
            )}
        </>,
        null,
        unpick
    );
}

export function BuyDomainPage({
    registrar,
    seed,
    owned = [],
    onBack,
    onBought,
    onOpen,
}: {
    registrar: DomainRegistrar;
    /** A name to open on (one asked for, else the one your domains already have). */
    seed?: string;
    owned?: string[];
    onBack: () => void;
    onBought: (domain: string) => void;
    onOpen: (domain: string) => void;
}) {
    // A domain bought here is the account's own, which shows only the account's own websites.
    const hasApps = !!usePlatformResources()?.items.apps?.some((app) => !app.owner);
    const [bought, setBought] = useState<string | null>(null);
    if (bought) {
        const done = () => onBought(bought);
        return (
            <PageFrame
                title={`Use ${bought} for a website?`}
                description={`Your website goes live there once ${bought} is registered and set up, usually within a few minutes.`}
                back={{ label: 'Domains', onBack: done }}
            >
                <UseBoughtDomain domain={bought} onDone={done} />
            </PageFrame>
        );
    }
    return (
        <DomainFinder registrar={registrar} seed={seed} owned={owned} onBought={(domain) => (hasApps ? setBought(domain) : onBought(domain))} onOpen={onOpen}>
            {(body, picked, unpick) =>
                picked ? (
                    <PageFrame title={`Buy ${picked.domain}`} back={{ label: 'Buy a domain', onBack: unpick }}>
                        {body}
                    </PageFrame>
                ) : (
                    <PageFrame title="Buy a domain" description="A domain for your websites and your agents’ email, registered in your name. You see the price before anything is charged." back={{ label: 'Domains', onBack }}>
                        {body}
                    </PageFrame>
                )
            }
        </DomainFinder>
    );
}
