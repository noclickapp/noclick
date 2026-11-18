// Phone numbers: numbers your agents answer and call from. Buying is the app's own purchase flow over /v1 (any country
// numbers are sold in, each at its own price, confirmed in its row with what's charged now); the drawer
// (`?number=`) routes inbound calls to an agent, places a call, lists calls
// with their transcripts both ways, and releases the number; a number shows its
// name, its source and recording, and what its answering agent may do
// (transfer the call, answer only your users). Numbers kept with your own phone
// provider are connected (PhoneNumbersBring; Disconnect instead of Release). In
// the lab (designed): texting the caller, and porting numbers in with the port requests (a
// connected number is disconnected first).
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { useNavigate } from 'react-router';
import { toast } from 'sonner';
import { HAIRLINE, SURFACE } from '@/ui/primitives';
import { cn } from '@/ui/utils';
import { PhoneNumber, type AnswerWithOptions, type AvailableNumber, type PhoneCall, type PhoneCallers, type PhoneNumberType } from 'noclick';
import { NumberFinder } from '@/screens/numbers/NumberFinder';
import { addFundsUrl } from '@/screens/console/lib/site';
import { usePhoneNumberPurchase, type NumberHolder, type NumberPurchaseTransport } from '@/screens/numbers/usePhoneNumberPurchase';
import { formatDuration } from '@/screens/console/lib/format';
import { PHONE_NUMBERS_EMPTY } from '@/screens/console/lib/snippets';
import { defaultWriteUser, userLabel } from '@/screens/console/lib/userFilter';
import {
    useAccount,
    useConsole,
    useConsoleHref,
} from '@/screens/console/hooks/useConsole';
import { usePaged } from '@/sdk/usePaged';
import { invalidateV1, useV1 } from '@/sdk/useV1';
import { useSearchParam } from '@/screens/console/hooks/useQueryState';
import { recordRecent } from '@/screens/console/hooks/useRecent';
import { Textarea } from '@/ui/textarea';
import { ConsoleButton } from '../../ui/Button';
import { ConsoleDialog } from '../../ui/ConsoleDialog';
import { DataTable, type Column } from '../../ui/DataTable';
import { Drawer } from '../../ui/Drawer';
import { EmptyCode } from '../../ui/EmptyCode';
import { ErrorPanel } from '../../ui/ErrorPanel';
import { Money } from '../../ui/Money';
import { StatusPill } from '../../ui/StatusPill';
import { UserField } from '../../ui/UserField';
import { TimeCell } from '../../ui/TimeCell';
import { useAgentNames } from '../lookups';
import { ConnectNumberDialog, PortNumberDialog, PortRequests, numberSource } from './PhoneNumbersBring';
import {
    ActsFor,
    ConfirmAction,
    errorText,
    Field,
    INPUT,
    LabeledInput,
    PanelToolbar,
    Section,
    type PanelProps,
} from './shared';

function callLook(status: string | null) {
    if (status === 'completed')
        return {
            label: 'Completed',
            glyph: 'check' as const,
            tone: 'ink' as const,
        };
    if (status === 'not_connected')
        return {
            label: 'Not connected',
            glyph: 'muted' as const,
            tone: 'muted' as const,
        };
    if (status === 'failed')
        return {
            label: 'Failed',
            glyph: 'cross' as const,
            tone: 'failure' as const,
        };
    return {
        label: status ?? 'Unknown',
        glyph: 'filled' as const,
        tone: 'ink' as const,
    };
}

function CallRow({ call }: { call: PhoneCall }) {
    const [open, setOpen] = useState(false);
    // Calls it answered show who called.
    const inbound = call.direction === 'inbound';
    return (
        <li className={cn('border-b last:border-b-0', HAIRLINE)}>
            <button
                type="button"
                aria-expanded={open}
                onClick={() => setOpen((o) => !o)}
                className="flex w-full items-center gap-3 px-3 py-2 text-left text-[13px] transition-colors hover:bg-foreground/[0.03]"
            >
                {open ? (
                    <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
                ) : (
                    <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />
                )}
                <span className="w-8 shrink-0 text-[12px] text-muted-foreground">
                    {inbound ? 'In' : 'Out'}
                </span>
                <span className="w-32 shrink-0 font-mono text-[12px]">
                    {inbound ? call.fromNumber : call.to}
                </span>
                <StatusPill look={callLook(call.status)} />
                <span className="ml-auto tabular-nums text-muted-foreground">
                    {call.seconds != null
                        ? formatDuration(call.seconds * 1000)
                        : '—'}
                </span>
                <Money usd={call.costUsd} className="w-16 text-right" />
            </button>
            {open && (
                <div className="px-3 pb-3 pl-9 text-[13px]">
                    {call.goal && (
                        <p className="m-0 mb-2 text-muted-foreground">
                            Goal: {call.goal}
                        </p>
                    )}
                    {call.error && (
                        <p className="m-0 mb-2 text-red-600 dark:text-red-400">
                            {call.error}
                        </p>
                    )}
                    {(call.userId || call.recordingUrl || call.transfer) && (
                        <p className="m-0 mb-2 flex flex-wrap gap-x-3 text-muted-foreground">
                            {call.userId && (
                                <span>
                                    Ran as <span className="font-mono text-[12px] text-foreground">{call.userId}</span>
                                </span>
                            )}
                            {call.recordingUrl && (
                                <a href={call.recordingUrl} target="_blank" rel="noreferrer" className="text-foreground underline-offset-2 hover:underline">
                                    Recording
                                </a>
                            )}
                            {call.transfer && (
                                <span>
                                    Handed to <span className="font-mono text-[12px] text-foreground">{call.transfer.to}</span>
                                    {call.transfer.status === 'answered' ? '' : ', who didn’t pick up'}
                                </span>
                            )}
                        </p>
                    )}
                    {call.transcript.length ? (
                        <ol
                            aria-label="Transcript"
                            className="m-0 flex list-none flex-col gap-1 p-0"
                        >
                            {call.transcript.map((turn, i) => (
                                <li key={i}>
                                    <span className="font-medium">
                                        {turn.role === 'assistant'
                                            ? 'Agent'
                                            : 'Them'}
                                        :
                                    </span>{' '}
                                    {turn.text}
                                </li>
                            ))}
                        </ol>
                    ) : (
                        <p className="m-0 text-muted-foreground">
                            No transcript.
                        </p>
                    )}
                </div>
            )}
        </li>
    );
}

function PlaceCall({ number }: { number: PhoneNumber }) {
    const href = useConsoleHref();
    const navigate = useNavigate();
    const [to, setTo] = useState('');
    const [goal, setGoal] = useState('');
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const call = async () => {
        setBusy(true);
        setError(null);
        try {
            const op = await number.call(to.trim(), { goal: goal.trim() });
            setTo('');
            setGoal('');
            invalidateV1('operations');
            toast(`Calling ${to.trim()}`, {
                action: {
                    label: 'View operation',
                    onClick: () => navigate(href('logs', { op: op.id })),
                },
            });
        } catch (e) {
            setError(errorText(e));
        } finally {
            setBusy(false);
        }
    };
    return (
        <Section title="Place a call">
            <form
                className="flex flex-col gap-3"
                onSubmit={(e) => {
                    e.preventDefault();
                    void call();
                }}
            >
                <ActsFor userId={number.userId} />
                <LabeledInput label="To" id="call-to">
                    <input
                        id="call-to"
                        className={cn(INPUT, 'font-mono')}
                        value={to}
                        onChange={(e) => setTo(e.target.value)}
                        placeholder="+14155550100"
                    />
                </LabeledInput>
                <LabeledInput label="Goal" id="call-goal">
                    <Textarea
                        id="call-goal"
                        rows={2}
                        value={goal}
                        onChange={(e) => setGoal(e.target.value)}
                        placeholder="Confirm Friday's 3pm booking."
                    />
                </LabeledInput>
                <div className="flex items-center gap-2">
                    <ConsoleButton
                        type="submit"
                        disabled={
                            busy ||
                            !to.trim() ||
                            !goal.trim() ||
                            !number.agentId
                        }
                    >
                        {busy ? 'Calling…' : 'Place call'}
                    </ConsoleButton>
                    {!number.agentId && (
                        <span className="text-[12px] text-muted-foreground">
                            Choose an answering agent first; it makes the call.
                        </span>
                    )}
                    {error && (
                        <span className="text-[12px] text-red-600 dark:text-red-400">
                            {error}
                        </span>
                    )}
                </div>
            </form>
        </Section>
    );
}

function AnswerWith({
    number,
    onChanged,
}: {
    number: PhoneNumber;
    onChanged: (n: PhoneNumber) => void;
}) {
    const { lab } = useConsole();
    const agents = useAgentNames();
    const [agent, setAgent] = useState(number.agentId ?? '');
    // answer_with sets the whole setup, so the form carries every option (texts is designed: lab).
    const [transferTo, setTransferTo] = useState(number.transferTo ?? '');
    const [texts, setTexts] = useState(number.texts);
    const [callers, setCallers] = useState<PhoneCallers>(number.callers ?? 'anyone');
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const changed =
        agent !== number.agentId ||
        transferTo.trim() !== (number.transferTo ?? '') ||
        callers !== (number.callers ?? 'anyone') ||
        (lab && texts !== number.texts);
    const save = async () => {
        setBusy(true);
        setError(null);
        try {
            const options: AnswerWithOptions = { transferTo: transferTo.trim() || undefined, callers, ...(lab ? { texts } : {}) };
            onChanged(await number.answerWith(agent, options));
            invalidateV1('phone_numbers');
            toast(
                `Calls to ${number.number} now reach ${agents.get(agent)?.name ?? 'the agent'}`
            );
        } catch (e) {
            setError(errorText(e));
        } finally {
            setBusy(false);
        }
    };
    return (
        <div className="flex flex-col gap-3">
            <div className="flex flex-col gap-3">
                <LabeledInput label="Transfer to (the agent's transfer_call tool; blank: none)" id="answer-transfer">
                    <input
                        id="answer-transfer"
                        className={cn(INPUT, 'font-mono')}
                        value={transferTo}
                        onChange={(e) => setTransferTo(e.target.value)}
                        placeholder="+14155550199"
                    />
                </LabeledInput>
                <LabeledInput label="Answers" id="answer-callers">
                    <select id="answer-callers" className={INPUT} value={callers} onChange={(e) => setCallers(e.target.value as PhoneCallers)}>
                        <option value="anyone">Anyone who calls</option>
                        <option value="users">Only your users (a verified phone, attested by the carrier)</option>
                        <option value="owner">Only its own user, or your account&apos;s owner</option>
                    </select>
                </LabeledInput>
                {lab && (
                    <label className="flex items-center gap-2 text-[13px]">
                        <input type="checkbox" checked={texts} onChange={(e) => setTexts(e.target.checked)} />
                        Let the agent text the caller (send_text; US carrier registration first)
                    </label>
                )}
            </div>
            <div className="flex flex-wrap items-center gap-2">
                <select
                    aria-label="Answering agent"
                    className={cn(INPUT, 'w-56')}
                    value={agent}
                    onChange={(e) => setAgent(e.target.value)}
                >
                    <option value="" disabled>
                        Choose an agent
                    </option>
                    {[...agents.values()].map((a) => (
                        <option key={a.id} value={a.id}>
                            {a.name}
                        </option>
                    ))}
                </select>
                <ConsoleButton
                    size="sm"
                    disabled={busy || !agent || !changed}
                    onClick={() => void save()}
                >
                    Answer with agent
                </ConsoleButton>
                {error && (
                    <span className="text-[12px] text-red-600 dark:text-red-400">
                        {error}
                    </span>
                )}
            </div>
        </div>
    );
}

/** Whether a number records its calls, and a switch to change it from the next call. */
function RecordCalls({ number, onChanged }: { number: PhoneNumber; onChanged: (n: PhoneNumber) => void }) {
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const toggle = async () => {
        setBusy(true);
        setError(null);
        try {
            onChanged(await number.update({ recordCalls: !number.recordCalls }));
            invalidateV1('phone_numbers');
        } catch (e) {
            setError(errorText(e));
        } finally {
            setBusy(false);
        }
    };
    return (
        <span className="inline-flex flex-wrap items-center gap-2">
            {number.recordCalls ? 'Every call, both ways; callers hear so first' : <span className="text-muted-foreground">Off</span>}
            <ConsoleButton size="sm" variant="ghost" disabled={busy} onClick={() => void toggle()}>
                {number.recordCalls ? 'Stop recording' : 'Record calls'}
            </ConsoleButton>
            {error && <span className="text-[12px] text-red-600 dark:text-red-400">{error}</span>}
        </span>
    );
}

function NumberDrawer({
    numberId,
    row,
    onClose,
}: {
    numberId: string | null;
    row?: PhoneNumber;
    onClose: () => void;
}) {
    const { client, lab } = useConsole();
    const fetched = useV1(
        numberId && !row ? `phone_numbers/${numberId}` : null,
        () => PhoneNumber.get(numberId!, { client })
    );
    const [updated, setUpdated] = useState<PhoneNumber | null>(null);
    const number =
        (updated && updated.id === numberId ? updated : null) ??
        row ??
        fetched.data;
    const calls = useV1(
        number ? `phone_numbers/${number.id}/calls` : null,
        () => number!.calls()
    );
    useEffect(() => {
        if (number)
            recordRecent({
                type: 'phone_number',
                id: number.id,
                label: number.number,
                path: 'resources/phone',
                params: { number: number.id },
            });
    }, [number?.id]); // eslint-disable-line react-hooks/exhaustive-deps
    return (
        <Drawer
            open={numberId !== null}
            onOpenChange={(o) => !o && onClose()}
            kind="phone_number"
            title={
                number ? (
                    <span className="font-mono">{number.number}</span>
                ) : undefined
            }
            id={numberId ?? undefined}
            footer={
                number && number.source === 'connected' ? (
                    <ConfirmAction
                        label="Disconnect"
                        title={`Disconnect ${number.number}?`}
                        description="NoClick puts back where its calls went before, and it stays in your phone provider account. You can connect it again."
                        confirmLabel="Disconnect"
                        onConfirm={async () => {
                            await number.disconnect();
                            invalidateV1('phone_numbers');
                            invalidateV1('account');
                            onClose();
                        }}
                    />
                ) : number ? (
                    <ConfirmAction
                        label="Release number"
                        title={`Release ${number.number}?`}
                        description="It stops ringing and billing now, and you can't get the same number back."
                        confirmLabel="Release"
                        onConfirm={async () => {
                            await number.release();
                            invalidateV1('phone_numbers');
                            invalidateV1('account');
                            onClose();
                        }}
                    />
                ) : undefined
            }
        >
            {!number && fetched.error !== undefined && (
                <ErrorPanel
                    error={fetched.error}
                    onRetry={() => void fetched.refresh()}
                />
            )}
            {number && (
                <div className="flex flex-col gap-5">
                    <dl className="m-0">
                        {number.name && (
                            <Field label="Name">
                                <span className="font-mono text-[12px]">{number.name}</span>
                            </Field>
                        )}
                        <Field label="User">
                            {userLabel(number.userId)}
                        </Field>
                        <Field label="Source">
                            {numberSource(number)}
                            {number.connection && (
                                <span className="text-muted-foreground">
                                    {' · through '}
                                    <span className="font-mono text-[12px] text-foreground">{number.connection}</span>
                                    {', your phone provider account'}
                                </span>
                            )}
                        </Field>
                        <Field label="Recording">
                            <RecordCalls number={number} onChanged={setUpdated} />
                        </Field>
                        <Field label="Monthly">
                            {number.source === 'connected' ? (
                                <span className="text-muted-foreground">
                                    Your phone provider bills the number and its minutes; NoClick bills only what it adds: the agent&apos;s time on calls.
                                </span>
                            ) : (
                                <Money usd={number.monthlyUsd} full />
                            )}
                        </Field>
                        <Field label={numberSource(number)}>
                            <TimeCell
                                value={number.createdAt}
                                tier="absolute"
                            />
                        </Field>
                    </dl>
                    {lab && number.source === 'connected' && (
                        <Section title="Port it to NoClick">
                            <p className="m-0 text-[13px] text-muted-foreground">
                                To move the number itself to NoClick, disconnect it first, then port it in with Port a number. For one kept with
                                Twilio, the account name is &quot;Twilio, Inc.&quot;, the account number the last 8 characters of your Account SID, and
                                the PIN comes from Twilio&apos;s support.
                            </p>
                        </Section>
                    )}
                    <Section title="Inbound calls reach">
                        <AnswerWith number={number} onChanged={setUpdated} />
                    </Section>
                    <PlaceCall number={number} />
                    <Section title="Calls">
                        <p className="m-0 mb-2 text-[12px] text-muted-foreground">
                            Calls this number answered and placed, newest first.
                        </p>
                        {calls.error !== undefined ? (
                            <ErrorPanel
                                error={calls.error}
                                onRetry={() => void calls.refresh()}
                            />
                        ) : calls.loading ? (
                            <div
                                aria-busy
                                className="h-20 animate-pulse rounded-lg bg-foreground/[0.04]"
                            />
                        ) : calls.data?.length ? (
                            <ul
                                aria-label="Calls"
                                className={cn(
                                    'm-0 list-none rounded-lg border p-0',
                                    HAIRLINE
                                )}
                            >
                                {calls.data.map((c) => (
                                    <CallRow
                                        key={c.id ?? String(c.createdAt)}
                                        call={c}
                                    />
                                ))}
                            </ul>
                        ) : (
                            <p className="m-0 text-[13px] text-muted-foreground">
                                No calls yet.
                            </p>
                        )}
                    </Section>
                </div>
            )}
        </Drawer>
    );
}

/** The shared number purchase flow (``usePhoneNumberPurchase``) over ``/v1``: prices are the API's own dollars, and a
 *  purchase's ceilings are exactly the prices the row showed. */
function useConsoleNumberTransport(client: ReturnType<typeof useConsole>['client'], buyer: { user: string | null; name: string }): NumberPurchaseTransport {
    const { site } = useConsole();
    const latest = useRef(buyer);
    latest.current = buyer;
    const send = useCallback<NumberPurchaseTransport['send']>(
        async (event) => {
            if (event.event_name === 'phone_number:coverage') {
                const countries = await PhoneNumber.coverage({ client, user: null });
                return {
                    countries: countries.map((c) => ({
                        country: c.country,
                        number_types: c.types,
                        texting_types: c.textingTypes,
                        documents_types: c.documentsTypes,
                        steps_types: c.stepsTypes,
                    })),
                };
            }
            if (event.event_name === 'phone_number:places') {
                return { places: await PhoneNumber.places(event.country as string, { client, user: null, type: event.number_type as PhoneNumberType }) };
            }
            if (event.event_name === 'phone_number:search') {
                const found = await PhoneNumber.available({
                    client,
                    user: null,
                    country: event.country as string,
                    type: event.number_type as PhoneNumberType,
                    areaCode: (event.area_code as string | null) ?? undefined,
                    locality: (event.locality as string | null) ?? undefined,
                    region: (event.region as string | null) ?? undefined,
                    contains: (event.contains as string | null) ?? undefined,
                    features: event.features as 'voice' | 'voice_sms',
                    limit: event.limit as number,
                });
                return { numbers: found.map(offerOf) };
            }
            if (event.event_name === 'phone_number:buy') {
                const holder = event.holder as NumberHolder | undefined;
                const number = await PhoneNumber.buy(event.phone_number as string, {
                    client,
                    user: latest.current.user,
                    country: event.country as string,
                    type: event.number_type as PhoneNumberType,
                    maxMonthlyUsd: event.monthly_usd as number,
                    maxUpfrontUsd: event.upfront_usd as number,
                    address: holder && {
                        name: holder.name,
                        businessName: holder.business_name ?? undefined,
                        street: holder.street,
                        street2: holder.street2 ?? undefined,
                        city: holder.city,
                        region: holder.region ?? undefined,
                        postalCode: holder.postal_code,
                        country: holder.country,
                        phone: holder.phone ?? undefined,
                    },
                    name: latest.current.name.trim() || undefined,
                });
                // The console files no documents, so a number it buys is never left in the carrier's review.
                if (!(number instanceof PhoneNumber)) throw new Error(`${number.number} is in the carrier's review: follow it as order ${number.id}.`);
                return { credential_id: number.id, phone_number: number.number };
            }
            throw new Error(`The console doesn't send ${event.event_name}.`);
        },
        [client]
    );
    // Where an account short of funds adds some: NoClick's top-up, as every surface that sells numbers links it.
    return useMemo(() => ({ send, fundsHref: addFundsUrl(site) }), [send, site]);
}

function offerOf(n: AvailableNumber) {
    return {
        phone_number: n.number,
        country: n.country,
        number_type: n.type,
        locality: n.locality ?? '',
        region: n.region ?? '',
        capabilities: n.capabilities,
        monthly_usd: n.monthlyUsd ?? 0,
        upfront_usd: n.upfrontUsd ?? 0,
        requirements: n.requirements,
        texting: n.texting,
    };
}

function BuyNumberFlow({ defaultUser, onBought }: { defaultUser: string | null; onBought: (number: string) => void }) {
    const { client, country } = useConsole();
    // What your code calls it (`PhoneNumber.from_name`), and whose it is.
    const [name, setName] = useState('');
    const [user, setUser] = useState<string | null>(defaultUser);
    const transport = useConsoleNumberTransport(client, { user, name });
    // Documents are filed in the app, or through the API with them (POST /v1/phone_numbers/documents).
    const purchase = usePhoneNumberPurchase({ transport, country, filesDocuments: false, onCredentialCreated: (_id, number) => onBought(number) });
    return (
        <div className="flex flex-col gap-4">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <UserField value={user} onChange={setUser} />
                <LabeledInput label="Name (optional, what your code calls it)" id="number-name">
                    <input id="number-name" className={cn(INPUT, 'font-mono')} value={name} onChange={(e) => setName(e.target.value)} placeholder="front-desk" />
                </LabeledInput>
            </div>
            <NumberFinder purchase={purchase} compact list={(rows) => <div className={cn('overflow-hidden rounded-lg border', HAIRLINE)}>{rows}</div>} />
        </div>
    );
}

function BuyNumber({ defaultUser }: { defaultUser: string | null }) {
    const [open, setOpen] = useState(false);
    return (
        <>
            <ConsoleButton variant="primary" onClick={() => setOpen(true)}>
                Buy a number
            </ConsoleButton>
            <ConsoleDialog
                open={open}
                onOpenChange={setOpen}
                size="lg"
                title="Buy a number"
                description="Numbers in every country NoClick sells in, each at its own price: charged monthly, and once when bought where its carrier charges that."
            >
                {open && (
                    <BuyNumberFlow
                        defaultUser={defaultUser}
                        onBought={(number) => {
                            setOpen(false);
                            invalidateV1('phone_numbers');
                            invalidateV1('account');
                            toast(`Bought ${number}`);
                        }}
                    />
                )}
            </ConsoleDialog>
        </>
    );
}

export function PhoneNumbersPanel({ user, setUser }: PanelProps) {
    const { client, lab } = useConsole();
    const account = useAccount().data;
    const agents = useAgentNames();
    const [numberId, setNumber] = useSearchParam('number');
    const enabled = account?.features.phone_numbers ?? false;
    const paged = usePaged(
        `phone_numbers?${user}`,
        (cursor) =>
            PhoneNumber.listPage({
                client,
                userFilter: user,
                cursor,
                limit: 50,
            }),
        (n) => n.id
    );
    const columns: Column<PhoneNumber>[] = [
        {
            id: 'number',
            header: 'Number',
            cell: (n) => (
                <span className="font-mono text-[12px] font-medium">
                    {n.number}
                </span>
            ),
        },
        {
            id: 'source',
            header: 'Source',
            priority: 2,
            width: '6.5rem',
            cell: (n) => numberSource(n),
        },
        {
            id: 'agent',
            header: 'Answers',
            priority: 2,
            width: '9rem',
            cell: (n) =>
                n.agentId ? (
                    (agents.get(n.agentId)?.name ?? n.agentId)
                ) : (
                    <span className="text-muted-foreground">No agent</span>
                ),
        },
        {
            id: 'user',
            header: 'User',
            priority: 2,
            width: '8rem',
            cell: (n) => (
                <span
                    className={
                        n.userId
                            ? 'font-mono text-[12px]'
                            : 'text-muted-foreground'
                    }
                >
                    {userLabel(n.userId)}
                </span>
            ),
        },
        {
            id: 'monthly',
            header: 'Monthly',
            align: 'right',
            width: '6.5rem',
            cell: (n) =>
                n.source === 'connected' ? (
                    <span className="text-muted-foreground">Your provider</span>
                ) : (
                    <Money usd={n.monthlyUsd} />
                ),
        },
        {
            id: 'created',
            header: 'Added',
            width: '6.5rem',
            cell: (n) => <TimeCell value={n.createdAt} />,
        },
    ];
    return (
        <>
            <PanelToolbar
                user={user}
                setUser={setUser}
                limit={
                    account
                        ? `${account.counts.phone_numbers} ${account.counts.phone_numbers === 1 ? 'number' : 'numbers'}`
                        : null
                }
                action={
                    <>
                        <ConnectNumberDialog
                            defaultUser={defaultWriteUser(user)}
                            onOpenNumber={(id) => setNumber(id, { push: true })}
                        />
                        {enabled && lab && <PortNumberDialog defaultUser={defaultWriteUser(user)} />}
                        {enabled && <BuyNumber defaultUser={defaultWriteUser(user)} />}
                    </>
                }
            />
            {lab && <PortRequests user={user} onOpenNumber={(id) => setNumber(id, { push: true })} />}
            {account && !enabled && (
                <p
                    className={cn(
                        SURFACE,
                        'm-0 mb-3 px-4 py-3 text-[13px] text-muted-foreground'
                    )}
                >
                    {
                        "Phone numbers aren't enabled for this account yet, so numbers can't be bought here. You can connect a number you keep with your own phone provider, and numbers you already have are listed below."
                    }
                </p>
            )}
            <DataTable
                label="Phone numbers"
                columns={columns}
                rows={paged.rows}
                getRowId={(n) => n.id}
                loading={paged.loading}
                error={paged.error}
                onRetry={() => void paged.refresh()}
                onRowClick={(n) => setNumber(n.id, { push: true })}
                selectedId={numberId}
                nextCursor={paged.nextCursor}
                onLoadMore={() => void paged.loadMore()}
                loadingMore={paged.loadingMore}
                empty={
                    <EmptyCode
                        title="No phone numbers yet."
                        hint="A number your agents answer and call from, billed monthly."
                        snippet={PHONE_NUMBERS_EMPTY}
                    />
                }
            />
            <NumberDrawer
                numberId={numberId}
                row={paged.rows.find((n) => n.id === numberId)}
                onClose={() => setNumber(null)}
            />
        </>
    );
}
