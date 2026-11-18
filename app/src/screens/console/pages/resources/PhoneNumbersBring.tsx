// Bringing a number from elsewhere into the Phone numbers page: connect one you keep with your
// own phone provider (pick its connection, then one of its numbers). In the lab (designed):
// port numbers in from their carrier (the account's details, then the holder signs one letter for
// all of them), and the port requests, each with what it waits on, a retry for a rejected one and
// cancel until it's scheduled.
import { useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { toast } from 'sonner';
import { HAIRLINE, SURFACE } from '@/ui/primitives';
import { cn } from '@/ui/utils';
import { Connection, PhoneNumber, PortRequest, type ConnectableNumber, type PortDetails, type StreetAddress } from 'noclick';
import type { StatusLook } from '@/screens/console/lib/status';
import { userLabel } from '@/screens/console/lib/userFilter';
import { useConsole } from '@/screens/console/hooks/useConsole';
import { invalidateV1, useV1 } from '@/sdk/useV1';
import { ConsoleButton } from '../../ui/Button';
import { ConsoleDialog } from '../../ui/ConsoleDialog';
import { ErrorPanel } from '../../ui/ErrorPanel';
import { StatusPill } from '../../ui/StatusPill';
import { TimeCell } from '../../ui/TimeCell';
import { UserField } from '../../ui/UserField';
import { useAgentNames } from '../lookups';
import { ConfirmAction, errorText, INPUT, LabeledInput } from './shared';
import { BADGE, LinkBox, Notice, dayLabel } from './DomainsParts';

/** The phone provider integration whose connections can route a number's calls today. */
const PROVIDER = 'twilio';

/** Where a number came from, as the table and the drawer say it. */
export function numberSource(number: PhoneNumber): string {
    if (number.source === 'connected') return 'Connected';
    if (number.source === 'ported') return 'Ported';
    return 'Bought';
}

const NEEDS_ACCOUNT_SECRET =
    "Connect it with the account's own SID and auth token, not an API key: NoClick checks the provider's signed calls with the account's secret.";

export function ConnectNumberDialog({ defaultUser, onOpenNumber }: { defaultUser: string | null; onOpenNumber: (id: string) => void }) {
    const { client } = useConsole();
    const [open, setOpen] = useState(false);
    const [user, setUser] = useState<string | null>(defaultUser);
    const [connection, setConnection] = useState('');
    const [picked, setPicked] = useState<ConnectableNumber | null>(null);
    const [name, setName] = useState('');
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>(undefined);
    const connections = useV1(open ? `connections?integration=${PROVIDER}&user=${user ?? ''}` : null, () => Connection.list({ client, user, integration: PROVIDER }));
    // The only connection there is needs no choosing.
    const chosen = connection || (connections.data?.length === 1 ? connections.data[0].name : '');
    const numbers = useV1(open && chosen ? `phone_numbers/connectable?user=${user ?? ''}&connection=${chosen}` : null, () => PhoneNumber.connectable(chosen, { client, user }));
    const agents = useAgentNames();
    const start = () => {
        setUser(defaultUser);
        setConnection('');
        setPicked(null);
        setName('');
        setError(undefined);
        setOpen(true);
    };
    const connect = async () => {
        if (!picked) return;
        setBusy(true);
        setError(undefined);
        try {
            const number = await PhoneNumber.connect(picked, { client, user, connection: chosen, name: name.trim() || undefined });
            setOpen(false);
            invalidateV1('phone_numbers');
            invalidateV1('account');
            toast(`Connected ${number.number}`);
            onOpenNumber(number.id);
        } catch (e) {
            setError(e);
        } finally {
            setBusy(false);
        }
    };
    return (
        <>
            <ConsoleButton onClick={start}>Connect a number</ConsoleButton>
            <ConsoleDialog
                open={open}
                onOpenChange={setOpen}
                title={picked ? `Connect ${picked.number}` : 'Connect a number'}
                description={picked ? 'It stays in your phone provider account, which bills it and its minutes.' : 'A number you keep with your own phone provider.'}
                footer={
                    picked ? (
                        <>
                            <ConsoleButton variant="ghost" onClick={() => setPicked(null)}>
                                Back
                            </ConsoleButton>
                            <ConsoleButton variant="primary" disabled={busy} onClick={() => void connect()}>
                                {busy ? 'Connecting…' : 'Connect number'}
                            </ConsoleButton>
                        </>
                    ) : undefined
                }
            >
                {picked ? (
                    <div className="flex flex-col gap-3">
                        <LabeledInput label="Name (optional, what your code calls it)" id="connect-number-name">
                            <input id="connect-number-name" className={cn(INPUT, 'font-mono')} value={name} onChange={(e) => setName(e.target.value)} placeholder="main-line" />
                        </LabeledInput>
                        <p className="m-0 text-[12px] text-muted-foreground">
                            {picked.routedElsewhere ? 'Its calls go somewhere else today, and stay there until an agent answers it. ' : ''}
                            NoClick remembers where its calls went; disconnecting puts that back. Your provider bills the number and its minutes;
                            NoClick bills only what it adds: the agent&apos;s time on calls.
                        </p>
                        {error !== undefined && <ErrorPanel error={error} />}
                    </div>
                ) : (
                    <div className="flex flex-col gap-3">
                        <UserField
                            value={user}
                            onChange={(next) => {
                                setUser(next);
                                setConnection('');
                            }}
                        />
                        {connections.error !== undefined ? (
                            <ErrorPanel error={connections.error} onRetry={() => void connections.refresh()} />
                        ) : connections.data && !connections.data.length ? (
                            <Notice title={`No phone provider connection ${user ? `for ${user}` : 'on your account'}`}>
                                Connect your phone provider account in Connections first. {NEEDS_ACCOUNT_SECRET}
                            </Notice>
                        ) : (
                            connections.data && (
                                <LabeledInput label="Phone provider connection" id="connect-number-connection">
                                    <select id="connect-number-connection" className={INPUT} value={chosen} onChange={(e) => setConnection(e.target.value)}>
                                        <option value="" disabled>
                                            Choose a connection
                                        </option>
                                        {connections.data.map((c) => (
                                            <option key={c.id} value={c.name}>
                                                {c.account ? `${c.name} · ${c.account}` : c.name}
                                            </option>
                                        ))}
                                    </select>
                                </LabeledInput>
                            )
                        )}
                        {numbers.error !== undefined && <ErrorPanel error={numbers.error} />}
                        {numbers.data && (
                            <ul aria-label="Numbers in this account" className={cn('m-0 list-none rounded-lg border p-0', HAIRLINE)}>
                                {numbers.data.map((n) => (
                                    <li key={n.number} className={cn('border-b last:border-b-0', HAIRLINE)}>
                                        {n.phoneNumberId ? (
                                            // Already one of your numbers: a number rings one agent, so it isn't offered again.
                                            <div className="flex w-full items-center gap-3 px-3 py-2 text-[13px]">
                                                <span className="font-mono text-[12px] text-muted-foreground">{n.number}</span>
                                                <span className="flex-1 truncate text-muted-foreground">
                                                    Already connected{n.agentId ? `, answered by ${agents.get(n.agentId)?.name ?? n.agentId}` : ''}
                                                </span>
                                                <ConsoleButton
                                                    variant="ghost"
                                                    onClick={() => {
                                                        setOpen(false);
                                                        onOpenNumber(n.phoneNumberId as string);
                                                    }}
                                                >
                                                    Open
                                                </ConsoleButton>
                                            </div>
                                        ) : (
                                            <button
                                                type="button"
                                                onClick={() => setPicked(n)}
                                                className="flex w-full items-center gap-3 px-3 py-2 text-left text-[13px] transition-colors hover:bg-foreground/[0.04]"
                                            >
                                                <span className="font-mono text-[12px]">{n.number}</span>
                                                <span className="flex-1 truncate text-muted-foreground">{n.label}</span>
                                                {n.routedElsewhere && <span className={BADGE}>Calls go elsewhere today</span>}
                                            </button>
                                        )}
                                    </li>
                                ))}
                            </ul>
                        )}
                    </div>
                )}
            </ConsoleDialog>
        </>
    );
}

type AddressDraft = { street: string; city: string; region: string; postalCode: string };

const EMPTY_ADDRESS: AddressDraft = { street: '', city: '', region: '', postalCode: '' };

/** The address once every part is filled; undefined while any is blank. */
function serviceAddress(draft: AddressDraft): StreetAddress | undefined {
    const [street, city, region, postalCode] = [draft.street.trim(), draft.city.trim(), draft.region.trim().toUpperCase(), draft.postalCode.trim()];
    return street && city && region && postalCode ? { street, city, region, postalCode } : undefined;
}

/** The service address as the carrier's bill shows it, part by part. */
function AddressFields({ idPrefix, value, onChange }: { idPrefix: string; value: AddressDraft; onChange: (next: AddressDraft) => void }) {
    const set = (key: keyof AddressDraft) => (e: { target: { value: string } }) => onChange({ ...value, [key]: e.target.value });
    return (
        <fieldset className="m-0 grid grid-cols-[1fr_4.5rem_6rem] gap-2 border-0 p-0 sm:col-span-2">
            <legend className="mb-1 p-0 text-[12px] text-muted-foreground">Service address</legend>
            <div className="col-span-3">
                <LabeledInput label="Street" id={`${idPrefix}-street`}>
                    <input id={`${idPrefix}-street`} className={INPUT} value={value.street} onChange={set('street')} placeholder="1 Ferry Building" />
                </LabeledInput>
            </div>
            <LabeledInput label="City" id={`${idPrefix}-city`}>
                <input id={`${idPrefix}-city`} className={INPUT} value={value.city} onChange={set('city')} placeholder="San Francisco" />
            </LabeledInput>
            <LabeledInput label="State" id={`${idPrefix}-region`}>
                <input id={`${idPrefix}-region`} className={cn(INPUT, 'uppercase')} maxLength={2} value={value.region} onChange={set('region')} placeholder="CA" />
            </LabeledInput>
            <LabeledInput label="ZIP" id={`${idPrefix}-zip`}>
                <input id={`${idPrefix}-zip`} inputMode="numeric" maxLength={5} className={INPUT} value={value.postalCode} onChange={set('postalCode')} placeholder="94111" />
            </LabeledInput>
        </fieldset>
    );
}

/** The numbers typed in one field, separated by commas or spaces. */
const parseNumbers = (text: string) => text.split(/[\s,]+/).filter(Boolean);

/** The numbers a port moves, for its title and messages. */
const portLabel = (port: PortRequest) => port.numbers.map((n) => n.number).join(', ') || (port.number ?? '');

type PortDraft = { numbers: string; holder: string; accountName: string; accountNumber: string; billingNumber: string; pin: string; max: string; name: string };

const EMPTY_PORT: PortDraft = { numbers: '', holder: '', accountName: '', accountNumber: '', billingNumber: '', pin: '', max: '', name: '' };

/** Port numbers in: one, or several on one account at their carrier, on one letter of authorization. */
export function PortNumberDialog({ defaultUser }: { defaultUser: string | null }) {
    const { client } = useConsole();
    const [open, setOpen] = useState(false);
    const [user, setUser] = useState<string | null>(defaultUser);
    const [draft, setDraft] = useState<PortDraft>(EMPTY_PORT);
    const [address, setAddress] = useState<AddressDraft>(EMPTY_ADDRESS);
    const [port, setPort] = useState<PortRequest | null>(null);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>(undefined);
    const set = (key: keyof PortDraft) => (e: { target: { value: string } }) => setDraft((d) => ({ ...d, [key]: e.target.value }));
    const start = () => {
        setUser(defaultUser);
        setDraft(EMPTY_PORT);
        setAddress(EMPTY_ADDRESS);
        setPort(null);
        setError(undefined);
        setOpen(true);
    };
    const numbers = parseNumbers(draft.numbers);
    const fullAddress = serviceAddress(address);
    const ready = !!(numbers.length && draft.holder.trim() && draft.accountName.trim() && fullAddress && draft.accountNumber.trim() && Number(draft.max) > 0);
    const submit = async () => {
        if (!fullAddress) return;
        setBusy(true);
        setError(undefined);
        try {
            setPort(
                await PhoneNumber.portIn(numbers, {
                    client,
                    user,
                    accountHolder: draft.holder.trim(),
                    accountName: draft.accountName.trim(),
                    serviceAddress: fullAddress,
                    accountNumber: draft.accountNumber.trim(),
                    billingNumber: draft.billingNumber.trim() || undefined,
                    pin: draft.pin.trim() || undefined,
                    maxMonthlyUsd: Number(draft.max),
                    name: (numbers.length === 1 && draft.name.trim()) || undefined,
                })
            );
            invalidateV1('operations');
        } catch (e) {
            setError(e);
        } finally {
            setBusy(false);
        }
    };
    return (
        <>
            <ConsoleButton onClick={start}>Port a number</ConsoleButton>
            <ConsoleDialog
                open={open}
                onOpenChange={setOpen}
                size={port ? 'md' : 'lg'}
                title={port ? `Porting ${portLabel(port)}` : 'Port a number'}
                description={
                    port
                        ? undefined
                        : 'Move US numbers to NoClick from their current carrier: one, or several on one account there. They keep working there until they move.'
                }
                footer={
                    port ? (
                        <ConsoleButton variant="primary" onClick={() => setOpen(false)}>
                            Done
                        </ConsoleButton>
                    ) : (
                        <ConsoleButton variant="primary" disabled={busy || !ready} onClick={() => void submit()}>
                            {busy ? 'Starting…' : 'Start port'}
                        </ConsoleButton>
                    )
                }
            >
                {port ? (
                    <div className="flex flex-col gap-3">
                        <Notice title={`Waiting for ${draft.holder.trim()} to sign`}>
                            <p className="m-0 mb-2">NoClick emailed them the letter of authorization. Once they sign, it goes to the carrier, which schedules the move.</p>
                            {port.signUrl && <LinkBox url={port.signUrl} label="signing link" />}
                        </Notice>
                        <p className="m-0 text-[12px] text-muted-foreground">
                            Then each is a NoClick number, billed monthly like a bought one. Follow the port under Ports.
                        </p>
                    </div>
                ) : (
                    <div className="grid gap-3 sm:grid-cols-2">
                        <LabeledInput label="Numbers" id="port-numbers">
                            <input id="port-numbers" className={cn(INPUT, 'font-mono')} value={draft.numbers} onChange={set('numbers')} placeholder="+14155550123, +14155550124" />
                        </LabeledInput>
                        <UserField value={user} onChange={setUser} />
                        <LabeledInput label="Account holder's email" id="port-holder">
                            <input id="port-holder" className={INPUT} value={draft.holder} onChange={set('holder')} placeholder="dana@harbordental.test" />
                        </LabeledInput>
                        <LabeledInput label="Account name" id="port-account-name">
                            <input id="port-account-name" className={INPUT} value={draft.accountName} onChange={set('accountName')} placeholder="Harbor Dental LLC" />
                        </LabeledInput>
                        <AddressFields idPrefix="port-address" value={address} onChange={setAddress} />
                        <LabeledInput label="Account number" id="port-account">
                            <input id="port-account" className={cn(INPUT, 'font-mono')} value={draft.accountNumber} onChange={set('accountNumber')} />
                        </LabeledInput>
                        <LabeledInput label="Billing number (optional)" id="port-billing">
                            <input id="port-billing" className={cn(INPUT, 'font-mono')} value={draft.billingNumber} onChange={set('billingNumber')} placeholder="The first number" />
                        </LabeledInput>
                        <LabeledInput label="PIN (optional)" id="port-pin">
                            <input id="port-pin" type="password" autoComplete="off" className={cn(INPUT, 'font-mono')} value={draft.pin} onChange={set('pin')} />
                        </LabeledInput>
                        <LabeledInput label="Most you'll pay a month (USD)" id="port-max">
                            <input id="port-max" inputMode="decimal" className={INPUT} value={draft.max} onChange={set('max')} placeholder="5" />
                        </LabeledInput>
                        {numbers.length <= 1 && (
                            <LabeledInput label="Name (optional, what your code calls it)" id="port-name">
                                <input id="port-name" className={cn(INPUT, 'font-mono')} value={draft.name} onChange={set('name')} placeholder="front-desk" />
                            </LabeledInput>
                        )}
                        <p className="m-0 text-[12px] text-muted-foreground sm:col-span-2">
                            The account as the current carrier has it, from a recent bill: its name (often the business, not the signer), service address and number. A mismatch
                            is the usual reason a port is rejected. The account holder signs a letter of authorization on a NoClick page; the monthly ceiling is per number. A
                            number you connected through your phone provider is disconnected first.
                        </p>
                        {error !== undefined && <ErrorPanel error={error} className="sm:col-span-2" />}
                    </div>
                )}
            </ConsoleDialog>
        </>
    );
}

function portLook(port: PortRequest): StatusLook {
    switch (port.status) {
        case 'awaiting_human':
            return { label: 'Awaiting signature', glyph: 'waiting', tone: 'ink' };
        case 'running':
            return port.step === 'scheduled'
                ? { label: 'Scheduled', reason: dayLabel(port.portAt), glyph: 'filled', tone: 'ink' }
                : { label: 'Submitted', glyph: 'filled', tone: 'ink' };
        case 'succeeded':
            return { label: 'Ported', glyph: 'check', tone: 'ink' };
        case 'failed':
            return { label: 'Rejected', glyph: 'cross', tone: 'failure' };
        case 'canceled':
            return { label: 'Canceled', glyph: 'muted', tone: 'muted' };
        default:
            return { label: port.status, glyph: 'hollow', tone: 'muted' };
    }
}

/** A rejected port sent again; a detail left blank keeps what it had. */
function RetryPort({ port }: { port: PortRequest }) {
    const [draft, setDraft] = useState({ holder: '', accountName: '', accountNumber: '', billingNumber: '', pin: '' });
    const [address, setAddress] = useState<AddressDraft>(EMPTY_ADDRESS);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const set = (key: keyof typeof draft) => (e: { target: { value: string } }) => setDraft((d) => ({ ...d, [key]: e.target.value }));
    const fullAddress = serviceAddress(address);
    // A corrected address replaces the whole one, so it goes only once every part is filled.
    const partialAddress = !fullAddress && Object.values(address).some((v) => v.trim());
    const corrected = Object.values(draft).some((v) => v.trim()) || !!fullAddress;
    const retry = async () => {
        setBusy(true);
        setError(null);
        const corrections: Partial<PortDetails> = {
            accountHolder: draft.holder.trim() || undefined,
            accountName: draft.accountName.trim() || undefined,
            serviceAddress: fullAddress,
            accountNumber: draft.accountNumber.trim() || undefined,
            billingNumber: draft.billingNumber.trim() || undefined,
            pin: draft.pin.trim() || undefined,
        };
        try {
            await port.retry(corrections);
            invalidateV1('operations');
            toast(`Sent the port of ${portLabel(port)} again`);
        } catch (e) {
            setError(errorText(e));
        } finally {
            setBusy(false);
        }
    };
    return (
        <form
            className="grid gap-2 sm:grid-cols-2"
            onSubmit={(e) => {
                e.preventDefault();
                void retry();
            }}
        >
            <LabeledInput label="Account number" id={`retry-account-${port.id}`}>
                <input id={`retry-account-${port.id}`} className={cn(INPUT, 'font-mono')} value={draft.accountNumber} onChange={set('accountNumber')} />
            </LabeledInput>
            <LabeledInput label="PIN" id={`retry-pin-${port.id}`}>
                <input id={`retry-pin-${port.id}`} type="password" autoComplete="off" className={cn(INPUT, 'font-mono')} value={draft.pin} onChange={set('pin')} />
            </LabeledInput>
            <LabeledInput label="Account name" id={`retry-account-name-${port.id}`}>
                <input id={`retry-account-name-${port.id}`} className={INPUT} value={draft.accountName} onChange={set('accountName')} />
            </LabeledInput>
            <LabeledInput label="Billing number" id={`retry-billing-${port.id}`}>
                <input id={`retry-billing-${port.id}`} className={cn(INPUT, 'font-mono')} value={draft.billingNumber} onChange={set('billingNumber')} />
            </LabeledInput>
            <AddressFields idPrefix={`retry-address-${port.id}`} value={address} onChange={setAddress} />
            <LabeledInput label="Account holder's email" id={`retry-holder-${port.id}`}>
                <input id={`retry-holder-${port.id}`} className={INPUT} value={draft.holder} onChange={set('holder')} />
            </LabeledInput>
            <div className="flex flex-wrap items-center gap-2 sm:col-span-2">
                <ConsoleButton type="submit" size="sm" disabled={busy || !corrected || partialAddress}>
                    {busy ? 'Sending…' : 'Send again'}
                </ConsoleButton>
                <span className="text-[12px] text-muted-foreground">
                    {partialAddress
                        ? 'A corrected service address needs its street, city, state and ZIP.'
                        : 'Blank details keep what they had. A corrected name, address, account or billing number is signed again.'}
                </span>
            </div>
            {error && <p className="m-0 text-[12px] text-red-600 dark:text-red-400 sm:col-span-2">{error}</p>}
        </form>
    );
}

function PortRow({ port, onOpenNumber }: { port: PortRequest; onOpenNumber: (id: string) => void }) {
    const [open, setOpen] = useState(port.status === 'awaiting_human' || port.status === 'failed');
    const cancelable = port.status === 'awaiting_human' || (port.status === 'running' && port.step !== 'scheduled');
    const ported = (port.result as { phone_numbers?: { id: string; number: string }[] } | null)?.phone_numbers ?? [];
    const several = port.numbers.length > 1;
    return (
        <li className={cn('border-b last:border-b-0', HAIRLINE)}>
            <button
                type="button"
                aria-expanded={open}
                onClick={() => setOpen((o) => !o)}
                className="flex w-full items-center gap-3 px-3 py-2 text-left text-[13px] transition-colors hover:bg-foreground/[0.03]"
            >
                {open ? <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" /> : <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />}
                <span className="w-32 shrink-0 font-mono text-[12px]">{port.number}</span>
                {several && <span className={BADGE}>+{port.numbers.length - 1} more</span>}
                <StatusPill look={portLook(port)} />
                <span className={cn('ml-auto hidden sm:inline', port.userId ? 'font-mono text-[12px]' : 'text-muted-foreground')}>{userLabel(port.userId)}</span>
                <TimeCell value={port.createdAt} className="w-20 text-right" />
            </button>
            {open && (
                <div className="flex flex-col gap-2 px-3 pb-3 pl-9 text-[13px]">
                    {several && (
                        // A carrier can move the numbers on one letter on different days.
                        <ul aria-label="Numbers on this port" className="m-0 flex list-none flex-col gap-1 p-0">
                            {port.numbers.map((n) => (
                                <li key={n.number} className="flex items-center gap-3 text-[12px]">
                                    <span className="w-32 shrink-0 font-mono">{n.number}</span>
                                    <span className="text-muted-foreground">
                                        {n.status}
                                        {n.portAt ? ` · ${dayLabel(n.portAt)}` : ''}
                                    </span>
                                </li>
                            ))}
                        </ul>
                    )}
                    {port.status === 'awaiting_human' && (
                        <>
                            <p className="m-0 text-muted-foreground">Waiting for the account holder to sign the letter of authorization. NoClick emailed them this link:</p>
                            {port.signUrl && <LinkBox url={port.signUrl} label="signing link" />}
                        </>
                    )}
                    {port.status === 'running' && port.step !== 'scheduled' && (
                        <p className="m-0 text-muted-foreground">With the current carrier, which schedules the move, usually within a few business days.</p>
                    )}
                    {port.step === 'scheduled' && port.status === 'running' && (
                        <p className="m-0 text-muted-foreground">
                            {several ? 'The last moves' : 'Moves'} on {dayLabel(port.portAt)}. {several ? 'They keep' : 'It keeps'} working with the carrier until
                            then, and a scheduled port can&apos;t be canceled.
                        </p>
                    )}
                    {port.status === 'succeeded' && (
                        <p className="m-0 flex flex-wrap items-center gap-2 text-muted-foreground">
                            {ported.length > 1 ? "They're NoClick numbers now" : "It's a NoClick number now"}, billed monthly like a bought one.
                            {ported.map((n) => (
                                <ConsoleButton key={n.id} variant="ghost" size="sm" onClick={() => onOpenNumber(n.id)}>
                                    {ported.length > 1 ? `View ${n.number}` : 'View number'}
                                </ConsoleButton>
                            ))}
                        </p>
                    )}
                    {port.status === 'failed' && port.error && (
                        <>
                            <p className="m-0 text-red-600 dark:text-red-400">{port.error.message}</p>
                            <RetryPort port={port} />
                        </>
                    )}
                    {cancelable && (
                        <div>
                            <ConfirmAction
                                label="Cancel port"
                                title={`Cancel the port of ${portLabel(port)}?`}
                                description={`${several ? 'They stay' : 'It stays'} with the current carrier. You can start a new port later.`}
                                confirmLabel="Cancel port"
                                onConfirm={async () => {
                                    await port.cancel();
                                    invalidateV1('operations');
                                }}
                            />
                        </div>
                    )}
                </div>
            )}
        </li>
    );
}

/** The numbers being ported in, and the recent ones that finished. Nothing shows until there's one. */
export function PortRequests({ user, onOpenNumber }: { user: string; onOpenNumber: (id: string) => void }) {
    const { client } = useConsole();
    const ports = useV1(`operations?kind=phone.port_in&user=${user}`, () => PortRequest.list({ client, userFilter: user, limit: 20 }));
    if (ports.error !== undefined) return <ErrorPanel error={ports.error} onRetry={() => void ports.refresh()} className="mb-3" />;
    if (!ports.data?.length) return null;
    return (
        <section aria-label="Ports" className={cn(SURFACE, 'mb-3 px-4 py-3')}>
            <h3 className="m-0 mb-2 text-[13px] font-medium">Ports</h3>
            <ul aria-label="Port requests" className={cn('m-0 list-none rounded-lg border p-0', HAIRLINE)}>
                {ports.data.map((p) => (
                    <PortRow key={p.id} port={p} onOpenNumber={onOpenNumber} />
                ))}
            </ul>
        </section>
    );
}
