// The Cards panel's dialogs: issue a card, edit its limits and merchants, and
// reveal its number behind a confirm that says the reveal is audited. A reveal is
// a link to the page where the card issuer's own element shows the number: the
// console never holds the number itself.
import { useState, type ReactNode } from 'react';
import { ArrowUpRight, Eye } from 'lucide-react';
import { toast } from 'sonner';
import { HAIRLINE } from '@/ui/primitives';
import { cn } from '@/ui/utils';
import { Card, type CardDetails, type CardInterval } from 'noclick';
import { useConsole } from '@/screens/console/hooks/useConsole';
import { invalidateV1 } from '@/sdk/useV1';
import { ConsoleButton } from '../../ui/Button';
import { ConsoleDialog } from '../../ui/ConsoleDialog';
import { CopyButton } from '../../ui/CopyButton';
import { ErrorPanel } from '../../ui/ErrorPanel';
import { UserField } from '../../ui/UserField';
import { useAgentNames } from '../lookups';
import { ActsFor, INPUT, LabeledInput } from './shared';

/** The merchant categories the console offers; a card may hold others, set from code. */
export const MERCHANT_CATEGORIES = ['office_supplies', 'software', 'travel', 'advertising', 'electronics', 'shipping'] as const;

export function merchantLabel(category: string): string {
    const text = category.replace(/_/g, ' ');
    return text.charAt(0).toUpperCase() + text.slice(1);
}

const WHOLE_USD = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });
const CENTS_USD = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2 });

/** `$1,500`, `$86.40`: whole dollars without cents. */
export function dollars(usd: number): string {
    return Number.isInteger(usd) ? WHOLE_USD.format(usd) : CENTS_USD.format(usd);
}

const PER: Record<CardInterval, string> = { transaction: 'a charge', day: 'a day', month: 'a month', all_time: 'in all' };

/** `$1,500 a month`, `$200 a charge`. */
export function limitLine(limitUsd: number | null, interval: CardInterval | null): string {
    return limitUsd == null ? 'No limit' : `${dollars(limitUsd)} ${PER[interval ?? 'month']}`;
}

const positive = (text: string) => text.trim() !== '' && Number(text) > 0;

function LimitFields({ limit, onLimit, interval, onInterval }: { limit: string; onLimit: (v: string) => void; interval: CardInterval; onInterval: (v: CardInterval) => void }) {
    return (
        <div className="grid grid-cols-[1fr_9rem] gap-3">
            <LabeledInput label="Limit (USD)" id="card-limit">
                <input id="card-limit" inputMode="decimal" className={INPUT} value={limit} onChange={(e) => onLimit(e.target.value)} placeholder="1500" />
            </LabeledInput>
            <LabeledInput label="Per" id="card-interval">
                <select id="card-interval" className={INPUT} value={interval} onChange={(e) => onInterval(e.target.value as CardInterval)}>
                    <option value="transaction">Charge</option>
                    <option value="day">Day</option>
                    <option value="month">Month</option>
                    <option value="all_time">All time</option>
                </select>
            </LabeledInput>
        </div>
    );
}

function MerchantPicker({ value, onChange }: { value: string[]; onChange: (next: string[]) => void }) {
    const offered = [...MERCHANT_CATEGORIES, ...value.filter((m) => !(MERCHANT_CATEGORIES as readonly string[]).includes(m))];
    return (
        <div className="flex flex-col gap-1.5">
            <span className="text-[12px] font-medium text-muted-foreground">Merchants</span>
            <div role="group" aria-label="Merchants" className="flex flex-wrap gap-1">
                {offered.map((m) => {
                    const on = value.includes(m);
                    return (
                        <button
                            key={m}
                            type="button"
                            aria-pressed={on}
                            onClick={() => onChange(on ? value.filter((x) => x !== m) : [...value, m])}
                            className={cn(
                                'h-7 rounded-md px-2.5 text-[12px] font-medium transition-colors',
                                on ? 'bg-foreground/[0.1] text-foreground' : 'bg-foreground/[0.03] text-muted-foreground hover:text-foreground'
                            )}
                        >
                            {merchantLabel(m)}
                        </button>
                    );
                })}
            </div>
            <span className="text-[12px] text-muted-foreground">{value.length ? 'Charges anywhere else are declined.' : 'None picked: it pays any merchant.'}</span>
        </div>
    );
}

function ThresholdField({ value, onChange }: { value: string; onChange: (v: string) => void }) {
    return (
        <div className="flex flex-col gap-1.5">
            <LabeledInput label="Ask a person above (USD, optional)" id="card-threshold">
                <input id="card-threshold" inputMode="decimal" className={INPUT} value={value} onChange={(e) => onChange(e.target.value)} placeholder="Never ask" />
            </LabeledInput>
            <span className="text-[12px] text-muted-foreground">
                The charge waits while the checkout is open, which suits a person at hand. For an approval that takes hours, approve the purchase in your books first and let the card pay after.
            </span>
        </div>
    );
}

/** A fresh number for every checkout, each taking one charge (designed). */
function SingleUseField({ value, onChange }: { value: boolean; onChange: (v: boolean) => void }) {
    return (
        <label className="flex items-start gap-2 text-[13px]">
            <input type="checkbox" className="mt-0.5" checked={value} onChange={(e) => onChange(e.target.checked)} />
            <span>
                Single use
                <span className="block text-[12px] text-muted-foreground">Every checkout gets a fresh number that takes one charge, all within the limit.</span>
            </span>
        </label>
    );
}

export function NewCard({ defaultUser }: { defaultUser: string | null }) {
    const { client } = useConsole();
    const agents = useAgentNames();
    const [open, setOpen] = useState(false);
    const [user, setUser] = useState<string | null>(defaultUser);
    const [name, setName] = useState('');
    const [limit, setLimit] = useState('');
    const [period, setPeriod] = useState<CardInterval>('month');
    const [merchants, setMerchants] = useState<string[]>([]);
    const [agent, setAgent] = useState('');
    const [threshold, setThreshold] = useState('');
    const [singleUse, setSingleUse] = useState(false);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>(undefined);
    // An agent pays with a card of its own user, or an account card.
    const eligible = [...agents.values()].filter((a) => a.userId === null || a.userId === user);
    const valid = name.trim() !== '' && positive(limit) && (threshold.trim() === '' || positive(threshold));
    const reset = () => {
        setUser(defaultUser);
        setName('');
        setLimit('');
        setPeriod('month');
        setMerchants([]);
        setAgent('');
        setThreshold('');
        setSingleUse(false);
        setError(undefined);
    };
    const issue = async () => {
        setBusy(true);
        setError(undefined);
        try {
            const card = await Card.create(name.trim(), {
                client,
                user,
                limitUsd: Number(limit),
                interval: period,
                merchants: merchants.length ? merchants : undefined,
                agent: agent || undefined,
                requireApprovalAboveUsd: threshold.trim() ? Number(threshold) : undefined,
                singleUse: singleUse || undefined,
            });
            setOpen(false);
            invalidateV1('cards');
            invalidateV1('account');
            toast(`Issued ${card.name} (•••• ${card.last4})`);
        } catch (e) {
            setError(e);
        } finally {
            setBusy(false);
        }
    };
    return (
        <>
            <ConsoleButton
                variant="primary"
                onClick={() => {
                    reset();
                    setOpen(true);
                }}
            >
                New card
            </ConsoleButton>
            <ConsoleDialog
                open={open}
                onOpenChange={setOpen}
                title="Issue a card"
                description="A virtual card that spends your card balance, within the limit you set."
                footer={
                    <ConsoleButton variant="primary" disabled={busy || !valid} onClick={() => void issue()}>
                        {busy ? 'Issuing…' : 'Issue card'}
                    </ConsoleButton>
                }
            >
                <div className="flex flex-col gap-3">
                    <UserField
                        value={user}
                        onChange={(next) => {
                            setUser(next);
                            if (agent && ![...agents.values()].some((a) => a.id === agent && (a.userId === null || a.userId === next))) setAgent('');
                        }}
                    />
                    <LabeledInput label="Name" id="card-name">
                        <input id="card-name" className={INPUT} value={name} onChange={(e) => setName(e.target.value)} placeholder="Office supplies" />
                    </LabeledInput>
                    <LimitFields limit={limit} onLimit={setLimit} interval={period} onInterval={setPeriod} />
                    <MerchantPicker value={merchants} onChange={setMerchants} />
                    <LabeledInput label="Agent that pays with it" id="card-agent">
                        <select id="card-agent" className={INPUT} value={agent} onChange={(e) => setAgent(e.target.value)}>
                            <option value="">No agent</option>
                            {eligible.map((a) => (
                                <option key={a.id} value={a.id}>
                                    {a.name}
                                </option>
                            ))}
                        </select>
                    </LabeledInput>
                    <ThresholdField value={threshold} onChange={setThreshold} />
                    <SingleUseField value={singleUse} onChange={setSingleUse} />
                    {error !== undefined && <ErrorPanel error={error} />}
                </div>
            </ConsoleDialog>
        </>
    );
}

export function EditLimits({ card, onSaved }: { card: Card; onSaved: () => void }) {
    const [open, setOpen] = useState(false);
    const [limit, setLimit] = useState('');
    const [period, setPeriod] = useState<CardInterval>('month');
    const [merchants, setMerchants] = useState<string[]>([]);
    const [threshold, setThreshold] = useState('');
    const [singleUse, setSingleUse] = useState(false);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>(undefined);
    const start = () => {
        setLimit(card.limitUsd == null ? '' : String(card.limitUsd));
        setPeriod(card.interval ?? 'month');
        setMerchants(card.merchants ?? []);
        setThreshold(card.requireApprovalAboveUsd == null ? '' : String(card.requireApprovalAboveUsd));
        setSingleUse(card.singleUse);
        setError(undefined);
        setOpen(true);
    };
    const save = async () => {
        setBusy(true);
        setError(undefined);
        try {
            await card.update({
                limitUsd: Number(limit),
                interval: period,
                merchants: merchants.length ? merchants : null,
                requireApprovalAboveUsd: threshold.trim() ? Number(threshold) : null,
                ...(singleUse !== card.singleUse ? { singleUse } : {}),
            });
            setOpen(false);
            onSaved();
            toast(`Updated ${card.name}`);
        } catch (e) {
            setError(e);
        } finally {
            setBusy(false);
        }
    };
    return (
        <>
            <ConsoleButton size="sm" onClick={start}>
                Edit limits
            </ConsoleButton>
            <ConsoleDialog
                open={open}
                onOpenChange={setOpen}
                title={`Edit ${card.name}`}
                description="Changes apply from the next charge."
                footer={
                    <ConsoleButton variant="primary" disabled={busy || !positive(limit) || (threshold.trim() !== '' && !positive(threshold))} onClick={() => void save()}>
                        {busy ? 'Saving…' : 'Save'}
                    </ConsoleButton>
                }
            >
                <div className="flex flex-col gap-3">
                    <ActsFor userId={card.userId} />
                    <LimitFields limit={limit} onLimit={setLimit} interval={period} onInterval={setPeriod} />
                    <MerchantPicker value={merchants} onChange={setMerchants} />
                    <ThresholdField value={threshold} onChange={setThreshold} />
                    <SingleUseField value={singleUse} onChange={setSingleUse} />
                    {error !== undefined && <ErrorPanel error={error} />}
                </div>
            </ConsoleDialog>
        </>
    );
}

function DetailRow({ label, children }: { label: string; children: ReactNode }) {
    return (
        <div className={cn('flex min-h-10 items-center gap-3 px-3 py-2')}>
            <dt className="w-20 shrink-0 text-[12px] text-muted-foreground sm:w-24">{label}</dt>
            <dd className="m-0 flex min-w-0 flex-1 items-center gap-1 text-[13px]">{children}</dd>
        </div>
    );
}

const CLOCK = new Intl.DateTimeFormat('en-US', { hour: 'numeric', minute: '2-digit' });

function Revealed({ details }: { details: CardDetails }) {
    const address = details.billingAddress ? ['line1', 'city', 'state', 'postal_code', 'country'].map((k) => details.billingAddress?.[k]).filter(Boolean).join(', ') : null;
    return (
        <dl aria-label="Card details" className={cn('m-0 rounded-lg border', HAIRLINE)}>
            <DetailRow label="Number">
                <a
                    href={details.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    referrerPolicy="no-referrer"
                    className="inline-flex items-center gap-1 font-medium text-foreground underline-offset-2 hover:underline"
                >
                    Open the card page
                    <ArrowUpRight className="h-3.5 w-3.5" />
                </a>
                <span className="ml-auto whitespace-nowrap font-mono text-[13px] tabular-nums text-muted-foreground">•••• {details.last4}</span>
                <CopyButton value={details.url} label="Copy link" />
            </DetailRow>
            {details.expiresAt && (
                <DetailRow label="Link">
                    <span className="text-muted-foreground">Shows the number until {CLOCK.format(details.expiresAt)}</span>
                </DetailRow>
            )}
            <DetailRow label="Expires">
                <span className="font-mono text-[13px] tabular-nums">
                    {String(details.expMonth ?? '').padStart(2, '0')}/{String(details.expYear ?? '').slice(-2)}
                </span>
            </DetailRow>
            {details.cardholder && <DetailRow label="Cardholder">{details.cardholder}</DetailRow>}
            {address && (
                <DetailRow label="Billing address">
                    <span className="min-w-0 truncate" title={address}>
                        {address}
                    </span>
                </DetailRow>
            )}
        </dl>
    );
}

export function RevealDetails({ card }: { card: Card }) {
    const [open, setOpen] = useState(false);
    const [details, setDetails] = useState<CardDetails | null>(null);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>(undefined);
    // Closing forgets the link: it lives only as long as the dialog.
    const onOpenChange = (next: boolean) => {
        setOpen(next);
        if (!next) {
            setDetails(null);
            setError(undefined);
        }
    };
    const reveal = async () => {
        setBusy(true);
        setError(undefined);
        try {
            setDetails(await card.reveal());
        } catch (e) {
            setError(e);
        } finally {
            setBusy(false);
        }
    };
    return (
        <>
            <ConsoleButton size="sm" icon={<Eye className="h-3.5 w-3.5" />} onClick={() => setOpen(true)}>
                Reveal details
            </ConsoleButton>
            <ConsoleDialog
                open={open}
                onOpenChange={onOpenChange}
                size="sm"
                title={details ? `${card.name} · •••• ${card.last4}` : 'Reveal the card number?'}
                description={
                    details
                        ? "The card issuer shows the number on that page, to whoever has the link, for 10 minutes: share it only with the person who pays."
                        : 'Each reveal is recorded in the audit log, with you and the time. Reveal the number only for a person to pay with: an agent holding the card never needs it.'
                }
                footer={
                    details ? (
                        <ConsoleButton variant="primary" onClick={() => onOpenChange(false)}>
                            Done
                        </ConsoleButton>
                    ) : (
                        <>
                            <ConsoleButton variant="ghost" onClick={() => onOpenChange(false)}>
                                Cancel
                            </ConsoleButton>
                            <ConsoleButton variant="primary" disabled={busy} onClick={() => void reveal()}>
                                {busy ? 'Revealing…' : 'Reveal'}
                            </ConsoleButton>
                        </>
                    )
                }
            >
                {details && <Revealed details={details} />}
                {error !== undefined && <ErrorPanel error={error} />}
            </ConsoleDialog>
        </>
    );
}
