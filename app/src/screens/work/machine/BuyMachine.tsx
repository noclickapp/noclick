// Buying an always-on machine, the one dialog Runs in opens from New agent and from a conversation (and Resources'
// Machines will): size first, each worth buying "from" its best price anywhere and a sold-out one greyed; then where
// it runs, cheapest picked, a region where that size is sold out saying so; then a quote that names the host, and Buy.
// The purchase is pinned to the quoted host, region and price: if that host has run out since, nothing is charged and
// the same popup quotes again in place, the new price over the old, with Buy held a moment so a double click never
// agrees to a price the person hasn't read. The picker itself never names a host. Opened from Resources' Machines with
// no agent, it rents one for the account: the confirm spells out the month, the day and who runs it, and an account
// whose company NoClick hasn't approved yet sends it with the rental, which starts once it's approved.
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Check, Globe, Server } from 'lucide-react';
import { Machine, NoClickError, NotAvailable, PriceExceeded, type MachineSizeName, type RegionName } from 'noclick';
import { getMachineAccess, requestMachineAccess } from '@/sdk/owner';
import { invalidateV1 } from '@/sdk/useV1';
import { REGION_NAMES, REGION_PLACES } from '@/lib/regionNames';
import { BUTTON_GHOST, BUTTON_PRIMARY, BUTTON_SECONDARY } from '@/ui/buttons';
import { ShellDialog } from '@/ui/ShellDialog';
import { cn } from '@/ui/utils';
import { useWorkV1 } from '../agents/reads';
import { useWorkClient } from '../client';
import { BackLink, slideIn } from './BackLink';
import { useMachineFrames } from './frames';
import { HOST_NAMES, machineNameFor, regionChoices, requote, sizeChoices, type Quote, type RegionChoice, type Requote, type SizeChoice } from './offers';
import { perDay, priceLine } from './machineView';
import { MACHINES_KEY, rereadMachine, useMachines, useMachineSizes, VETTING_KEY } from './reads';
import { Steps, type Step } from './Steps';
import { VettingCard, vettingReady, type VettingDraft } from './VettingCard';
import { useOwnerOnly } from '@/screens/console/ownerOnly';
import { OwnerOnlyNote } from '@/screens/console/ui/OwnerOnlyNote';

/** How long Buy waits after a price shows or changes before it takes a press. */
export const HOLD_MS = 1200;

export const SIZE_NAMES: Record<MachineSizeName, string> = { small: 'Small', medium: 'Medium', large: 'Large', xlarge: 'XLarge' };
const regionName = (r: RegionName) => REGION_NAMES[r] ?? r;
const usd = (n: number) => `$${n.toFixed(2)}`;
const spec = (s: { cpu: number; memoryGb: number }) => `${s.cpu} vCPU · ${s.memoryGb} GB`;
const atOnce = (n: number) => `about ${n} ${n === 1 ? 'agent' : 'agents'} at once`;

export interface BuyMachineProps {
    /** The agent it's for: it names the machine and the steps. `made`: it exists and moves there; else it's a draft.
     *  Without one it's the account's, rented from Resources' Machines. */
    agent?: { name: string; made: boolean };
    /** Once bought: move the agent there, or pick it for the draft. */
    onBought: (machine: Machine) => void;
    onClose: () => void;
    /** Back to where it was opened from (Add a machine's choice), from the sizes. */
    back?: { label: string; onBack: () => void };
    /** Once it runs: open its page. */
    onOpen?: (machine: Machine) => void;
}

type Page = 'sizes' | 'where' | 'confirm';
/** Where the confirm stands: quoted, quoted again after a refusal, buying, bought (then starting), or refused with
 *  nothing like it left to buy. */
type Phase = 'quote' | 'requoted' | 'buying' | 'bought' | 'refused' | 'sent';
/** What a refused purchase says, in the platform's own words. */
type Said = { message: string; nextStep: string | null };

export function BuyMachine({ agent, onBought, onClose, back: backTo, onOpen }: BuyMachineProps) {
    const client = useWorkClient();
    const sizes = useMachineSizes();
    const machines = useMachines();
    // The account's own rental waits on NoClick's company check, sent with it when it hasn't been yet.
    const access = useWorkV1(agent ? null : VETTING_KEY, (c) => getMachineAccess(c));
    const vetting = access.data && access.data.status !== 'approved' ? access.data : null;
    // The company check is sent by the account's owner, signed in; a key renting waits on one already sent.
    const asks = useOwnerOnly()('machineAccess');
    const [draft, setDraft] = useState<VettingDraft | null>(null);
    const company: VettingDraft = draft ?? { company_name: vetting?.company_name ?? '', website: vetting?.website ?? '', country: vetting?.country ?? '', use_case: vetting?.use_case ?? '' };
    const [page, setPage] = useState<Page>('sizes');
    const [back, setBack] = useState(false);
    const [picked, setPicked] = useState<MachineSizeName | null>(null);
    const [region, setRegion] = useState<RegionName | null>(null);
    const [quote, setQuote] = useState<Quote | null>(null);
    const [phase, setPhase] = useState<Phase>('quote');
    // After a refusal: the offer that sold out, the price shown before this one, what's offered beside it, and what
    // changed (or that the person chose another).
    const [soldOut, setSoldOut] = useState<Quote | null>(null);
    const [shown, setShown] = useState<number | null>(null);
    const [others, setOthers] = useState<Quote[]>([]);
    const [why, setWhy] = useState<Requote['changed'] | 'chose'>('host');
    const [said, setSaid] = useState<Said | null>(null);
    const [bought, setBought] = useState<Machine | null>(null);
    const held = useHold();

    const listed = sizes.data ?? [];
    const choices = sizeChoices(listed);
    const buyable = choices.filter((c) => c.from !== null);
    const size = buyable.find((c) => c.size.name === picked)?.size ?? buyable[0]?.size ?? null;
    const regions = size ? regionChoices(size, listed) : [];
    const there = regions.find((r) => r.quote && r.region === region)?.quote ?? regions.find((r) => r.quote)?.quote ?? null;

    const go = (to: Page, backwards = false) => {
        setBack(backwards);
        setPage(to);
    };
    const toWhere = () => {
        if (!size) return;
        setRegion(regions.find((r) => r.quote)?.region ?? null);
        go('where');
    };
    const toConfirm = () => {
        if (!there) return;
        setQuote(there);
        setPhase('quote');
        setSoldOut(null);
        setSaid(null);
        held.start();
        go('confirm');
    };

    const buy = async () => {
        if (!quote || held.on || phase === 'buying') return;
        const before = phase;
        setPhase('buying');
        setSaid(null);
        let machine: Machine;
        try {
            if (vetting && (vetting.status === 'not_submitted' || vetting.status === 'rejected')) {
                await requestMachineAccess(client, { ...company, country: company.country.trim().toUpperCase(), accept_usage_policy: true });
                invalidateV1(VETTING_KEY);
                invalidateV1('resources:machines/vetting');
            }
            const name = machineNameFor(agent?.name ?? regionName(quote.region), (machines.data ?? []).map((m) => m.name));
            machine = await Machine.create(name, { client, size: quote.size, region: quote.region, host: quote.host, maxMonthlyUsd: quote.usd });
        } catch (error) {
            const stock = error instanceof NotAvailable || error instanceof PriceExceeded;
            const again = stock ? await Machine.sizes({ client, includeDominated: true }).catch(() => null) : null;
            const still = again?.some((s) => s.name === quote.size && !s.dominatedBy && s.regions.some((r) => r.region === quote.region && r.host === quote.host && r.monthlyUsd === quote.usd && !r.dominatedBy));
            if (!again || still) {
                // Not a change the listing shows: the refusal in its own words, and Buy again.
                setPhase(before === 'requoted' ? 'requoted' : 'quote');
                setSaid({ message: error instanceof Error ? error.message : String(error), nextStep: error instanceof NoClickError ? error.nextStep : null });
                return;
            }
            sizes.mutate(again);
            const next = requote(quote, again);
            setSoldOut(quote);
            if (!next) return setPhase('refused');
            setShown(quote.usd);
            setQuote(next.quote);
            setOthers(next.alternatives);
            setWhy(next.changed);
            setPhase('requoted');
            held.start();
            return;
        }
        invalidateV1(MACHINES_KEY);
        rereadMachine(machine.id);
        setBought(machine);
        // Held until NoClick approves the company: nothing is charged before it starts.
        setPhase(machine.raw.status === 'awaiting_approval' ? 'sent' : 'bought');
        onBought(machine);
    };
    const choose = (other: Quote) => {
        if (!quote) return;
        setShown(quote.usd);
        setOthers([quote, ...others.filter((o) => o !== other)]);
        setQuote(other);
        setWhy('chose');
        held.start();
    };

    // Bought, it's watched until it runs.
    const boughtKey = bought ? `machines/${bought.id}:bought` : null;
    const read = useWorkV1(boughtKey, (c) => Machine.get(bought!.id, { client: c }));
    useMachineFrames(bought?.id ?? null, boughtKey);
    const machine = read.data ?? bought;

    let body: ReactNode;
    let title: ReactNode;
    let description: ReactNode;
    let mark: ReactNode = <Server className="h-5 w-5" strokeWidth={1.75} />;
    let footer: ReactNode;
    const cancel = (
        <button type="button" onClick={onClose} className={BUTTON_GHOST}>
            Cancel
        </button>
    );
    if (page === 'sizes') {
        title = agent ? `A machine for ${agent.name}` : 'Rent a machine';
        description = agent ? `Always on, at a monthly price. ${agent.name} ${agent.made ? 'moves to it on its next turn' : 'runs on it once it’s made'}.` : 'Sold at cost and always on. Agents you put on it work there.';
        body = (
            <>
                {backTo && <BackLink label={backTo.label} onClick={backTo.onBack} />}
                <SizeList state={sizes} choices={choices} value={size?.name ?? null} onPick={setPicked} />
            </>
        );
        footer = (
            <>
                {cancel}
                <button type="button" disabled={!size} onClick={toWhere} className={BUTTON_PRIMARY}>
                    Choose where
                </button>
            </>
        );
    } else if (page === 'where' && size) {
        mark = <Globe className="h-5 w-5" strokeWidth={1.75} />;
        title = `Where ${SIZE_NAMES[size.name]} runs`;
        description = 'Cheapest first. A machine stays in its region.';
        body = (
            <>
                <BackLink label="Sizes" onClick={() => go('sizes', true)} />
                <RegionList regions={regions} value={there?.region ?? null} onPick={setRegion} />
            </>
        );
        footer = (
            <>
                {cancel}
                <button type="button" disabled={!there} onClick={toConfirm} className={BUTTON_PRIMARY}>
                    Continue{there ? ` · ${usd(there.usd)} a month` : ''}
                </button>
            </>
        );
    } else if (phase === 'refused' && soldOut) {
        title = `${SIZE_NAMES[soldOut.size]} sold out in ${regionName(soldOut.region)}`;
        description = `${HOST_NAMES[soldOut.host]} ran out as you pressed Buy. Nothing was charged.`;
        body = <p className="pb-2 text-[13.5px] text-muted-foreground">Nothing like it is in stock anywhere right now.</p>;
        footer = (
            <button
                type="button"
                onClick={() => {
                    setPicked(null);
                    go('sizes', true);
                }}
                className={BUTTON_SECONDARY}
            >
                Pick another size
            </button>
        );
    } else if (quote) {
        const s = listed.find((x) => x.name === quote.size);
        const name = SIZE_NAMES[quote.size];
        const where = regionName(quote.region);
        const running = machine?.status === 'running';
        const failed = machine?.status === 'failed';
        const box = machine?.name ?? 'It';
        const requoted = phase === 'requoted';
        const sent = phase === 'sent';
        const sameOffer = !!soldOut && soldOut.size === quote.size && soldOut.region === quote.region;
        // Bought for the account (Resources' Machines): rented, and named for where it runs.
        const rent = !agent;
        const named = machine?.name ?? machineNameFor(regionName(quote.region), (machines.data ?? []).map((m) => m.name));
        const companyName = company.company_name.trim() || 'your company';
        title = running
            ? `${box} is running`
            : sent
              ? 'Sent to NoClick'
              : phase === 'bought'
                ? `${rent ? 'Renting' : 'Bought'} ${name} in ${where}`
                : requoted
                  ? sameOffer
                      ? 'The price changed'
                      : `What you can ${rent ? 'rent' : 'buy'} changed`
                  : `${rent ? 'Rent' : 'Buy'} ${name} in ${where}?`;
        description = running
            ? agent
                ? `${agent.name} ${agent.made ? 'moves to it on its next turn' : 'runs on it once it’s made'}.`
                : 'Its row is in Machines. Open it to move agents there.'
            : sent
              ? `${named} starts once ${companyName} is approved. Nothing is charged until then.`
              : phase === 'bought'
                ? `It starts in about ${rent ? 3 : 2} minutes. You can close this.`
                : requoted
                  ? `Nothing was charged. ${rent ? 'Rent' : 'Buy'} at the new price, or pick another.`
                  : rent
                    ? `${usd(quote.usd)} a month, ${perDay(quote.usd)}.`
                    : `${usd(quote.usd)} a month, charged a thirtieth each day it’s kept.`;
        if (running || sent) mark = <Check className="h-5 w-5" strokeWidth={2} />;
        const steps: Step[] = [
            {
                id: 'what',
                title: `${name} in ${where}`,
                status: 'done',
                body: <p className="mt-1 text-[12.5px] text-muted-foreground">{[s && (rent ? `${s.cpu} vCPU · ${s.memoryGb} GB memory` : spec(s)), `${quote.diskGb} GB disk`, `${rent ? 'run by' : 'on'} ${HOST_NAMES[quote.host]}`].filter(Boolean).join(' · ')}</p>,
            },
            {
                id: 'price',
                title:
                    phase === 'buying' ? (
                        `${rent ? 'Renting' : 'Buying'} at ${usd(quote.usd)} a month`
                    ) : requoted && shown !== null ? (
                        <>
                            <span className="mr-1 font-normal text-muted-foreground line-through decoration-[1.5px]" data-testid="was-price">
                                {usd(shown)}
                            </span>
                            <Changed key={`${quote.size}:${quote.region}:${quote.usd}`}>{usd(quote.usd)}</Changed> a month
                        </>
                    ) : (
                        `${usd(quote.usd)} a month${phase === 'bought' && !rent ? ', bought' : ''}`
                    ),
                status: phase === 'buying' ? 'busy' : phase === 'bought' || sent ? 'done' : 'now',
                body: (
                    <>
                        <p className="mt-1 text-[12.5px] leading-snug text-muted-foreground">
                            {requoted && soldOut
                                ? whyText(why, quote, soldOut)
                                : rent
                                  ? priceLine(quote.usd)
                                  : phase === 'bought'
                                    ? 'A thirtieth of it each day until you delete it.'
                                    : 'A thirtieth of it each day, from the day it starts until you delete it. If it can’t start at this price, nothing is charged and you’re asked again.'}
                        </p>
                        {requoted && others.length > 0 && (
                            <div className="mt-2 grid justify-items-start gap-1">
                                {others.map((o) => (
                                    <button key={`${o.size}:${o.region}`} type="button" onClick={() => choose(o)} className="text-left text-[12.5px] text-foreground underline decoration-foreground/30 underline-offset-[3px] transition-colors hover:decoration-foreground">
                                        Or {SIZE_NAMES[o.size]}
                                        {o.region !== quote.region ? ` in ${regionName(o.region)}` : ''} for {usd(o.usd)} a month
                                    </button>
                                ))}
                            </div>
                        )}
                        {said && (
                            <p role="alert" className="mt-2 text-[12.5px] leading-snug text-red-600 dark:text-red-400">
                                {said.message}
                                {said.nextStep ? ` ${said.nextStep}` : ''}
                            </p>
                        )}
                    </>
                ),
            },
            ...(vetting && rent
                ? [
                      {
                          id: 'vetting',
                          title: sent ? 'Sent to NoClick' : `NoClick checks ${companyName} first`,
                          status: sent ? 'done' : 'now',
                          body: (
                              <div className="mt-1.5 grid gap-2">
                                  {!sent && !asks && vetting.status !== 'pending' && <OwnerOnlyNote what="machineAccess" />}
                                  {!sent && (asks || vetting.status === 'pending') && <VettingCard value={company} onChange={setDraft} editable={asks && vetting.status !== 'pending'} />}
                                  {!sent && vetting.status === 'rejected' && vetting.reason && <p className="text-[12.5px] leading-snug text-muted-foreground">Last time NoClick said: {vetting.reason}</p>}
                                  {!sent && vetting.status !== 'pending' && <p className="text-[12.5px] leading-snug text-muted-foreground">Sending this accepts the machines usage policy: no crypto mining, network scanning or bulk email.</p>}
                                  <p className="text-[12.5px] leading-snug text-muted-foreground">Once, before your first machine, so machines aren’t used for spam or mining. Usually within a day. Nothing is charged until it starts.</p>
                              </div>
                          ),
                      } satisfies Step,
                  ]
                : []),
            {
                id: 'start',
                title: running
                    ? `${box} is running`
                    : failed
                      ? `${box} couldn’t start`
                      : phase === 'bought'
                        ? `Starting ${box}`
                        : !agent
                          ? vetting
                              ? 'It starts the moment it’s approved'
                              : 'It starts in about 3 minutes'
                          : `It starts, then ${agent.name} ${agent.made ? 'moves to it' : 'runs on it'}`,
                status: running ? 'done' : failed ? 'error' : phase === 'bought' ? 'busy' : 'wait',
                body: (
                    <p className="mt-1 text-[12.5px] text-muted-foreground">
                        {failed
                            ? (machine?.statusReason ?? 'Its page says why.')
                            : !agent
                              ? running
                                  ? 'Move agents to it from its page, or from an agent’s Runs in.'
                                  : `Named ${named}; rename it on its page. Agents move to it when you say.`
                              : running
                                ? `${agent.name}’s ${agent.made ? 'next' : 'first'} turn runs there.`
                                : `About 2 minutes. ${agent.name}’s ${agent.made ? 'next' : 'first'} turn runs there.`}
                    </p>
                ),
            },
        ];
        body = <Steps steps={steps} />;
        const ready = !vetting || !rent || vetting.status === 'pending' || (asks && vettingReady(company));
        footer =
            running || failed ? (
                <>
                    {running && onOpen && machine && (
                        <button type="button" onClick={() => onOpen(machine)} className={BUTTON_GHOST}>
                            Open {box}
                        </button>
                    )}
                    <button type="button" onClick={onClose} className={BUTTON_PRIMARY}>
                        Done
                    </button>
                </>
            ) : sent ? (
                <button type="button" onClick={onClose} className={BUTTON_PRIMARY}>
                    Done
                </button>
            ) : phase === 'bought' ? (
                <button type="button" onClick={onClose} className={BUTTON_GHOST}>
                    Close; it carries on
                </button>
            ) : (
                <>
                    <button
                        type="button"
                        disabled={phase === 'buying'}
                        onClick={() => {
                            setPicked(quote.size);
                            setRegion(quote.region);
                            go('where', true);
                        }}
                        className={BUTTON_GHOST}
                    >
                        Back
                    </button>
                    <BuyButton held={held.on} blocked={!ready} round={held.round} busy={phase === 'buying'} onClick={() => void buy()}>
                        {phase === 'buying'
                            ? rent
                                ? vetting
                                    ? 'Sending'
                                    : 'Renting'
                                : 'Buying'
                            : rent
                              ? vetting
                                  ? vetting.status === 'pending'
                                      ? 'Rent; it starts when approved'
                                      : 'Send and start when approved'
                                  : `Rent for ${usd(quote.usd)} a month`
                              : `Buy for ${usd(quote.usd)} a month`}
                    </BuyButton>
                </>
            );
    }

    return (
        <ShellDialog
            open
            onOpenChange={(open) => !open && onClose()}
            dismissible={phase !== 'buying'}
            title={title}
            description={description}
            mark={mark}
            footer={footer}
            testId="buy-machine"
        >
            <div key={`${page}:${phase === 'refused'}`} className={cn('pb-2', slideIn(back))}>
                {body}
            </div>
        </ShellDialog>
    );
}

/** Why the quote changed, in two sentences: what happened to the one quoted, then what this one is. */
function whyText(why: Requote['changed'] | 'chose', q: Quote, soldOut: Quote): string {
    const was = `${HOST_NAMES[soldOut.host]}’s ${SIZE_NAMES[soldOut.size]}`;
    const where = regionName(soldOut.region);
    if (why === 'price') return `The price of ${was} in ${where} changed as you pressed Buy, so nothing was charged. This is its price now.`;
    const name = SIZE_NAMES[q.size];
    const then = {
        chose: `You chose ${name}${q.region !== soldOut.region ? ` in ${regionName(q.region)}` : ''} instead.`,
        host: `${HOST_NAMES[q.host]} has one there at this price, with a ${q.diskGb} GB disk.`,
        region: `${regionName(q.region)} has the next cheapest ${name}, at this price.`,
        size: `${name} is now the cheapest machine with at least that much room.`,
    }[why];
    return `${was} sold out in ${where} as you pressed Buy, so nothing was charged. ${then}`;
}

/** Buy, held after a price shows or changes: it takes no press until the sweep across it ends. */
function useHold() {
    const [on, setOn] = useState(false);
    // Each hold its own sweep, a new price during one included.
    const [round, setRound] = useState(0);
    const timer = useRef<number | undefined>(undefined);
    useEffect(() => () => window.clearTimeout(timer.current), []);
    return {
        on,
        round,
        start: () => {
            window.clearTimeout(timer.current);
            setOn(true);
            setRound((n) => n + 1);
            timer.current = window.setTimeout(() => setOn(false), HOLD_MS);
        },
    };
}

function BuyButton({ held, blocked = false, round, busy, onClick, children }: { held: boolean; blocked?: boolean; round: number; busy: boolean; onClick: () => void; children: ReactNode }) {
    const sweep = useRef<HTMLSpanElement>(null);
    useEffect(() => {
        const el = sweep.current;
        if (!held || !el || typeof el.animate !== 'function' || window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return;
        const run = el.animate([{ transform: 'scaleX(1)' }, { transform: 'scaleX(0)' }], { duration: HOLD_MS, easing: 'linear', fill: 'forwards' });
        run.finished.catch(() => undefined);
        return () => run.cancel();
    }, [held, round]);
    return (
        <button type="button" disabled={held || blocked || busy} aria-busy={busy || undefined} data-held={held || undefined} onClick={onClick} className={cn(BUTTON_PRIMARY, 'relative overflow-hidden', held && 'disabled:opacity-100')}>
            {held && <span ref={sweep} aria-hidden className="pointer-events-none absolute inset-0 origin-right bg-background/30" />}
            {busy && <span aria-hidden className="relative h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-r-transparent [animation-duration:1.1s]" />}
            <span className="relative">{children}</span>
        </button>
    );
}

/** A price that just changed, lit for a moment. */
function Changed({ children }: { children: ReactNode }) {
    const el = useRef<HTMLSpanElement>(null);
    useEffect(() => {
        const node = el.current;
        if (!node || typeof node.animate !== 'function' || window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return;
        node.animate([{ backgroundColor: 'hsl(var(--foreground) / 0.12)' }, { backgroundColor: 'hsl(var(--foreground) / 0.12)', offset: 0.3 }, { backgroundColor: 'transparent' }], { duration: 1600, easing: 'ease-out' }).finished.catch(() => undefined);
    }, []);
    return (
        <span ref={el} data-testid="new-price" className="-mx-1 inline-block rounded-full px-1">
            {children}
        </span>
    );
}

function SizeList({ state, choices, value, onPick }: { state: ReturnType<typeof useMachineSizes>; choices: SizeChoice[]; value: MachineSizeName | null; onPick: (size: MachineSizeName) => void }) {
    if (!state.data) {
        return state.error !== undefined ? (
            <div role="status" className="flex flex-wrap items-center gap-2">
                <span className="text-[13.5px] text-foreground">Couldn’t read what’s in stock: {state.error instanceof Error ? state.error.message : String(state.error)}</span>
                <button type="button" onClick={() => void state.refresh()} className={cn(BUTTON_SECONDARY, 'h-8 px-3.5 text-[13px]')}>
                    Try again
                </button>
            </div>
        ) : (
            <p className="text-[13.5px] text-muted-foreground">Reading what’s in stock…</p>
        );
    }
    if (!choices.length) return <p className="text-[13.5px] text-muted-foreground">Nothing is in stock right now.</p>;
    return (
        <div role="radiogroup" aria-label="Size" className="grid gap-1.5">
            {choices.map(({ size, from, varies }) => (
                <ChoiceRow
                    key={size.name}
                    checked={value === size.name}
                    disabled={from === null}
                    onPick={() => onPick(size.name)}
                    title={SIZE_NAMES[size.name]}
                    spec={`${spec(size)} · ${atOnce(size.workingConversations)}`}
                    under={from === null ? 'None anywhere right now.' : undefined}
                    price={from === null ? null : { usd: from, from: varies }}
                />
            ))}
        </div>
    );
}

function RegionList({ regions, value, onPick }: { regions: RegionChoice[]; value: RegionName | null; onPick: (region: RegionName) => void }) {
    return (
        <div role="radiogroup" aria-label="Where it runs" className="grid gap-1.5">
            {regions.map((r) => (
                <ChoiceRow
                    key={r.region}
                    checked={value === r.region}
                    disabled={!r.quote}
                    onPick={() => onPick(r.region)}
                    title={regionName(r.region)}
                    spec={r.quote ? `${r.diskGb} GB disk · ${REGION_PLACES[r.region] ?? r.region}` : (REGION_PLACES[r.region] ?? r.region)}
                    price={r.quote ? { usd: r.quote.usd, from: false } : null}
                    soldOut="Sold out here"
                />
            ))}
        </div>
    );
}

/** One size or region: a radio dot, its name and what it is, and its price (or, sold out, greyed and saying so). */
function ChoiceRow({
    checked,
    disabled,
    onPick,
    title,
    spec: line,
    under,
    price,
    soldOut = 'Sold out',
}: {
    checked: boolean;
    disabled: boolean;
    onPick: () => void;
    title: string;
    spec: string;
    under?: string;
    price: { usd: number; from: boolean } | null;
    soldOut?: string;
}) {
    return (
        <button
            type="button"
            role="radio"
            aria-checked={checked && !disabled}
            aria-disabled={disabled || undefined}
            onClick={() => !disabled && onPick()}
            className={cn(
                'flex w-full items-start gap-3 rounded-[20px] px-3.5 py-3 text-left ring-1 ring-inset transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                checked && !disabled ? 'bg-foreground/[0.05] ring-[1.5px] ring-foreground/60' : 'ring-border dark:ring-foreground/[0.1]',
                disabled ? 'cursor-default' : !checked && 'hover:bg-foreground/[0.03]'
            )}
        >
            <span className={cn('mt-0.5 grid h-4 w-4 shrink-0 place-items-center rounded-full ring-[1.5px] ring-inset', checked && !disabled ? 'ring-foreground' : 'ring-foreground/30', disabled && 'opacity-40')}>
                {checked && !disabled && <span className="h-2 w-2 rounded-full bg-foreground" />}
            </span>
            <span className="grid min-w-0 flex-1 gap-px">
                <span className={cn('text-[14px] font-medium leading-snug', disabled ? 'text-muted-foreground' : 'text-foreground')}>{title}</span>
                <span className={cn('text-[12.5px] leading-snug', disabled ? 'text-muted-foreground/70' : 'text-muted-foreground')}>{line}</span>
                {under && <span className="mt-0.5 text-[12.5px] leading-snug text-muted-foreground">{under}</span>}
            </span>
            {price ? (
                <span className="shrink-0 text-right text-[14px] font-medium tabular-nums text-foreground">
                    {price.from && <span className="block text-[11.5px] font-normal text-muted-foreground">From</span>}
                    {usd(price.usd)}
                    <span className="text-[12.5px] font-normal text-muted-foreground">/mo</span>
                </span>
            ) : (
                <span className="shrink-0 rounded-full px-2 py-px text-[12px] text-muted-foreground ring-1 ring-inset ring-border dark:ring-foreground/[0.12]">{soldOut}</span>
            )}
        </button>
    );
}
