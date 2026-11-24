// A domain's drawer (`?domain=`): what it waits on first (the registrant confirming
// their email, an approval, a transfer in, records to add), the facts, its DNS (records to
// add for a connected domain, which can also transfer in; moving a transferred one's DNS
// to NoClick; the editable zone NoClick hosts), what it serves, renewal, transfer out, and
// Disconnect for a connected one.
import { useEffect, useReducer, useState } from 'react';
import { MailWarning } from 'lucide-react';
import { toast } from 'sonner';
import { cn } from '@/ui/utils';
import { Domain, type DnsRecord, type TransferCode } from 'noclick';
import { formatMoneyFull } from '@/screens/console/lib/format';
import { userLabel } from '@/screens/console/lib/userFilter';
import { useConsole } from '@/screens/console/hooks/useConsole';
import { invalidateV1, useV1 } from '@/sdk/useV1';
import { heldCallOf, useReportHeld, type HeldCall } from '@/sdk/held';
import { HeldCallNotice } from '@/ui/HeldCallNotice';
import { recordRecent } from '@/screens/console/hooks/useRecent';
import { ConsoleButton } from '../../ui/Button';
import { Drawer } from '../../ui/Drawer';
import { ErrorPanel } from '../../ui/ErrorPanel';
import { Money } from '../../ui/Money';
import { Segmented } from '../../ui/Segmented';
import { StatusPill } from '../../ui/StatusPill';
import { ConfirmAction, errorText, Field, INPUT, LabeledInput, Section } from './shared';
import { ConnectedRecords } from './DomainsConnectDialog';
import { DnsRecordList, LinkBox, Notice, ServesLinks, dayLabel, daysUntil, domainLook, everyLabel, registeredHere, sourceLabel, yearsLabel } from './DomainsParts';
import { TransferDomainDialog } from './DomainsTransferDialog';

const RECORD_TYPES = ['A', 'AAAA', 'CNAME', 'MX', 'TXT', 'CAA'] as const;
const RENEW_YEARS = [1, 2, 3, 5];
const DAY_MS = 86_400_000;

/** `renew()` works until `renewableUntil`; after it, renewing isn't an API call. */
function renewable(domain: Domain, now: number): boolean {
    return !domain.renewableUntil || domain.renewableUntil.getTime() > now;
}

/** What needs the person, above everything else. */
function Notices({ domain }: { domain: Domain }) {
    const { now } = useConsole();
    if (domain.status === 'registrant_unverified') {
        return (
            <Notice title="Confirm the registrant's email" icon={<MailWarning className="h-4 w-4" />}>
                ICANN requires the registrant to confirm their email address. {domain.registrantEmail ?? 'The registrant'} was emailed a link to confirm it, in your
                brand on ICANN&apos;s behalf; the domain works meanwhile, and NoClick reminds them. Unconfirmed by {dayLabel(domain.registrantVerifyBy)}, it stops
                resolving until they confirm.
            </Notice>
        );
    }
    if (domain.status === 'awaiting_human') {
        return (
            <Notice title="Waiting for approval">
                Your policy holds purchases for a person to approve. Once they do, it&apos;s charged to your account and registered; if nobody approves within 24
                hours, nothing is charged.
            </Notice>
        );
    }
    if (domain.status === 'transferring_in') {
        return (
            <Notice title="Transferring in">
                The registry and its current registrar are moving it to NoClick, which takes up to about 5 days; the registrar may email the current owner to
                approve. Its DNS keeps working where it is meanwhile.
            </Notice>
        );
    }
    if (domain.status === 'expiring') {
        const days = daysUntil(domain.expiresAt, now());
        return (
            <Notice title={`Expires ${dayLabel(domain.expiresAt)}${days !== null && days >= 0 ? `, in ${days} days` : ''}`}>
                {domain.autoRenew ? "Your account couldn't pay for the renewal; NoClick retries and has emailed you." : 'Auto-renew is off, so it lapses then.'} Renew it
                below to keep it.
            </Notice>
        );
    }
    if (domain.status === 'expired') {
        return (
            <Notice title={`Expired ${dayLabel(domain.expiresAt)}`}>
                {renewable(domain, now())
                    ? `It no longer resolves. Renewing brings it back until ${dayLabel(domain.renewableUntil)}; after that it can't be renewed here, though NoClick support may restore it at the registry's fee.`
                    : `It no longer resolves, and its renewal window ended ${dayLabel(domain.renewableUntil)}, so it can't be renewed here. NoClick support may restore it, at the registry's fee.`}
            </Notice>
        );
    }
    if (domain.status === 'failed') {
        return domain.source === 'transferred' ? (
            <Notice title="The transfer failed">The registry refused the transfer, and nothing was charged. It stays with its current registrar.</Notice>
        ) : (
            <Notice title="The purchase failed">Registering failed, and nothing was charged. Nothing is registered.</Notice>
        );
    }
    return null;
}

/** A transferred domain whose DNS is still at its old host: move it to NoClick, then review what was copied. */
function DnsElsewhere({ domain, onChanged }: { domain: Domain; onChanged: (copied: DnsRecord[]) => void }) {
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>(undefined);
    const move = async () => {
        setBusy(true);
        setError(undefined);
        try {
            const copied = await domain.useNoClickDns();
            invalidateV1('domains');
            onChanged(copied);
            toast(`NoClick hosts ${domain.name}'s DNS now`);
        } catch (e) {
            setError(e);
        } finally {
            setBusy(false);
        }
    };
    return (
        <Section title="DNS">
            <p className="m-0 mb-2 text-[13px] text-muted-foreground">
                {`${domain.name}'s DNS is still hosted where it was before the transfer, so records are changed there. Use NoClick DNS to move it here: NoClick copies the records it can read first, for you to review.`}
            </p>
            <ConsoleButton size="sm" disabled={busy} onClick={() => void move()}>
                {busy ? 'Moving…' : 'Use NoClick DNS'}
            </ConsoleButton>
            {error !== undefined && <ErrorPanel error={error} className="mt-2" />}
        </Section>
    );
}

/** A bought domain's zone: NoClick's managed records, yours, and adding one. */
function BoughtDns({ domain }: { domain: Domain }) {
    const records = useV1(`domains/${domain.id}/dns`, () => domain.dns.records());
    const [type, setType] = useState<string>('TXT');
    const [name, setName] = useState('');
    const [value, setValue] = useState('');
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const reportHeld = useReportHeld(useConsole());
    const run = async (write: () => Promise<unknown>, done: string, what: string) => {
        setBusy(true);
        setError(null);
        try {
            await write();
            await records.refresh();
            toast(done);
        } catch (e) {
            if (reportHeld(e, what, () => void records.refresh())) return;
            setError(errorText(e));
        } finally {
            setBusy(false);
        }
    };
    const add = () =>
        run(async () => {
            await domain.dns.set(type, name.trim() || '@', value.trim());
            setName('');
            setValue('');
        }, `Added the ${type} record`, `Add the ${type} record`);
    const remove = (record: DnsRecord) =>
        void run(() => domain.dns.delete(record), `Deleted the ${record.type} record at ${record.name}`, `Delete the ${record.type} record at ${record.name}`);
    return (
        <Section title="DNS records">
            <p className="m-0 mb-2 text-[12px] text-muted-foreground">{"NoClick hosts this domain's DNS. Locked records serve what it points at; the rest are yours."}</p>
            {records.error !== undefined ? (
                <ErrorPanel error={records.error} onRetry={() => void records.refresh()} />
            ) : records.loading ? (
                <div aria-busy className="h-24 animate-pulse rounded-lg bg-foreground/[0.04]" />
            ) : (
                <DnsRecordList records={records.data ?? []} label="DNS records" onDelete={remove} busy={busy} />
            )}
            <form
                className="mt-3 grid grid-cols-[5.5rem_minmax(0,1fr)] gap-2 sm:grid-cols-[5.5rem_9rem_minmax(0,1fr)_auto]"
                onSubmit={(e) => {
                    e.preventDefault();
                    if (value.trim()) void add();
                }}
            >
                <select aria-label="Record type" className={INPUT} value={type} onChange={(e) => setType(e.target.value)}>
                    {RECORD_TYPES.map((t) => (
                        <option key={t}>{t}</option>
                    ))}
                </select>
                <input aria-label="Record name" className={cn(INPUT, 'font-mono')} value={name} onChange={(e) => setName(e.target.value)} placeholder="@ or www" />
                <input
                    aria-label="Record value"
                    className={cn(INPUT, 'col-span-2 font-mono sm:col-span-1')}
                    value={value}
                    onChange={(e) => setValue(e.target.value)}
                    placeholder="v=spf1 include:_spf.example.com ~all"
                />
                <ConsoleButton type="submit" className="col-span-2 h-9 justify-center sm:col-span-1" disabled={busy || !value.trim()}>
                    Add record
                </ConsoleButton>
            </form>
            {error && <p className="m-0 mt-2 text-[12px] text-red-600 dark:text-red-400">{error}</p>}
        </Section>
    );
}

/** What renewing for `years` costs: `renewalUsd` buys the TLD's minimum term (`renewalYears`). */
function renewalFor(domain: Domain, years: number): number | null {
    if (domain.renewalUsd == null) return null;
    return Math.round((domain.renewalUsd * years * 100) / (domain.renewalYears ?? 1)) / 100;
}

function Renewal({ domain, onChanged }: { domain: Domain; onChanged: () => void }) {
    const { now } = useConsole();
    const term = domain.renewalYears ?? 1;
    const [years, setYears] = useState(term);
    const [max, setMax] = useState(String(renewalFor(domain, term) ?? ''));
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [held, setHeld] = useState(false);
    // A renewal NoClick holds for the account's owner (the app's own key), followed where it was asked for.
    const [heldCall, setHeldCall] = useState<HeldCall | null>(null);
    const act = async (write: () => Promise<void>) => {
        setBusy(true);
        setError(null);
        try {
            await write();
            onChanged();
        } catch (e) {
            const call = heldCallOf(e);
            if (call) return setHeldCall(call);
            setError(errorText(e));
        } finally {
            setBusy(false);
        }
    };
    const setAutoRenew = (on: boolean) =>
        act(async () => {
            await domain.update({ autoRenew: on });
            invalidateV1('domains?');
            toast(on ? `${domain.name} renews itself` : `${domain.name} lapses on ${dayLabel(domain.expiresAt)}`);
        });
    const renew = () =>
        act(async () => {
            const renewal = await domain.renew({ years, maxPriceUsd: Number(max) });
            setHeld(renewal.status === 'awaiting_human');
            if (renewal.status !== 'awaiting_human') {
                await domain.refresh();
                invalidateV1('domains?');
                toast(`Renewing ${domain.name} for ${yearsLabel(years)}`);
            }
        });
    const renewsOn = domain.expiresAt ? new Date(domain.expiresAt.getTime() - 30 * DAY_MS) : null;
    const open = renewable(domain, now());
    return (
        <Section title="Renewal">
            <div className="flex flex-col gap-3">
                <div className="flex flex-wrap items-center gap-3">
                    <Segmented
                        label="Auto-renew"
                        options={[
                            { value: 'on', label: 'Auto-renew on' },
                            { value: 'off', label: 'Off' },
                        ]}
                        value={domain.autoRenew ? 'on' : 'off'}
                        onChange={(v) => {
                            if ((v === 'on') !== domain.autoRenew) void setAutoRenew(v === 'on');
                        }}
                    />
                    <span className="text-[12px] text-muted-foreground">
                        {domain.autoRenew ? (
                            <>
                                Renews {dayLabel(renewsOn)} for <Money usd={domain.renewalUsd} full /> {everyLabel(term)}, charged to your account
                            </>
                        ) : (
                            <>Lapses on {dayLabel(domain.expiresAt)}; NoClick never deletes it</>
                        )}
                    </span>
                </div>
                <form
                    className="flex flex-wrap items-end gap-2"
                    onSubmit={(e) => {
                        e.preventDefault();
                        void renew();
                    }}
                >
                    <LabeledInput label="Renew now" id="renew-years">
                        <select
                            id="renew-years"
                            className={cn(INPUT, 'w-28')}
                            value={years}
                            onChange={(e) => {
                                const next = Number(e.target.value);
                                setYears(next);
                                const cost = renewalFor(domain, next);
                                if (cost != null) setMax(String(cost));
                            }}
                        >
                            {RENEW_YEARS.filter((y) => y >= term).map((y) => (
                                <option key={y} value={y}>
                                    {y === 1 ? '1 year' : `${y} years`}
                                </option>
                            ))}
                        </select>
                    </LabeledInput>
                    <LabeledInput label="Most you'll pay (USD)" id="renew-max">
                        <input id="renew-max" inputMode="decimal" className={cn(INPUT, 'w-36')} value={max} onChange={(e) => setMax(e.target.value)} />
                    </LabeledInput>
                    <ConsoleButton type="submit" className="h-9" disabled={busy || !open || !(Number(max) > 0)}>
                        {busy ? 'Renewing…' : 'Renew'}
                    </ConsoleButton>
                </form>
                {domain.renewableUntil && (
                    <p className="m-0 text-[12px] text-muted-foreground">
                        {open
                            ? `Renewing works until ${dayLabel(domain.renewableUntil)}, the end of its renewal window; after that, NoClick support may restore it at the registry's fee.`
                            : `Its renewal window ended ${dayLabel(domain.renewableUntil)}, so it can't be renewed here; NoClick support may restore it at the registry's fee.`}
                    </p>
                )}
                {heldCall && (
                    <HeldCallNotice
                        key={heldCall.approvalId}
                        held={heldCall}
                        what={`Renew ${domain.name} for ${yearsLabel(years)}`}
                        onSettled={(state) => state.phase === 'done' && (void domain.refresh().then(onChanged), invalidateV1('domains?'))}
                    />
                )}
                {held && <Notice title="Renewal waiting for approval">Your policy holds renewals for a person to approve; it&apos;s charged to your account once they do.</Notice>}
                {error && <p className="m-0 text-[12px] text-red-600 dark:text-red-400">{error}</p>}
            </div>
        </Section>
    );
}

function TransferOut({ domain }: { domain: Domain }) {
    const { now } = useConsole();
    const [code, setCode] = useState<TransferCode | null>(null);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const locked = !!domain.transferLockedUntil && domain.transferLockedUntil.getTime() > now();
    const reveal = async () => {
        setBusy(true);
        setError(null);
        try {
            setCode(await domain.transferOut());
            invalidateV1('domains?');
        } catch (e) {
            setError(errorText(e));
        } finally {
            setBusy(false);
        }
    };
    return (
        <Section title="Transfer out">
            <p className="m-0 mb-2 text-[13px] text-muted-foreground">
                {`Move the domain to another registrar: they ask for its auth code. The registry locks a domain for a while after it's registered, transferred in or its registrant changes${locked ? `, so transfers open ${dayLabel(domain.transferLockedUntil)}.` : '.'}`}
            </p>
            {code ? (
                <div className="flex flex-col gap-1.5">
                    <LinkBox url={code.authCode} label="auth code" />
                    <span className="text-[12px] text-muted-foreground">
                        Give this code to the new registrar
                        {code.expiresAt ? `; it works until ${dayLabel(code.expiresAt)}` : ''}. The domain shows
                        Transferring out until the move completes.
                    </span>
                </div>
            ) : (
                <ConsoleButton size="sm" disabled={busy || locked} onClick={() => void reveal()}>
                    {busy ? 'Unlocking…' : 'Get transfer code'}
                </ConsoleButton>
            )}
            {error && <p className="m-0 mt-2 text-[12px] text-red-600 dark:text-red-400">{error}</p>}
        </Section>
    );
}

export function DomainDrawer({ domainId, row, onClose }: { domainId: string | null; row?: Domain; onClose: () => void }) {
    const { client, now } = useConsole();
    const fetched = useV1(domainId && !row ? `domains/${domainId}` : null, () => Domain.get(domainId!, { client }));
    const domain = row ?? fetched.data;
    // Writes change the domain in place (verify, update, renew): redraw on each.
    const [, rerender] = useReducer((n: number) => n + 1, 0);
    // What moving a transferred domain's DNS here copied, for review.
    const [copied, setCopied] = useState<{ id: string; records: DnsRecord[] } | null>(null);
    useEffect(() => {
        if (domain)
            recordRecent({ type: 'domain', id: domain.id, label: domain.name, path: 'resources/domains', params: { domain: domain.id } });
    }, [domain?.id]); // eslint-disable-line react-hooks/exhaustive-deps
    const registered = !!domain && registeredHere(domain);
    const registrant = domain?.registrant ?? null;
    const copiedHere = copied && copied.id === domain?.id ? copied.records : null;
    return (
        <Drawer
            open={domainId !== null}
            onOpenChange={(o) => !o && onClose()}
            kind="domain"
            title={domain ? <span className="font-mono">{domain.name}</span> : undefined}
            id={domainId ?? undefined}
            status={domain ? <StatusPill look={domainLook(domain, now())} /> : undefined}
            footer={
                domain && !registered ? (
                    <ConfirmAction
                        label="Disconnect"
                        title={`Disconnect ${domain.name}?`}
                        description="It stops serving your apps. Its DNS stays as it is where it's hosted, and you can connect it again."
                        confirmLabel="Disconnect"
                        onConfirm={async () => {
                            await domain.delete();
                            invalidateV1('domains?');
                            invalidateV1('account');
                            onClose();
                        }}
                    />
                ) : undefined
            }
        >
            {!domain && fetched.error !== undefined && <ErrorPanel error={fetched.error} onRetry={() => void fetched.refresh()} />}
            {!domain && fetched.error === undefined && <div aria-busy className="h-40 animate-pulse rounded-lg bg-foreground/[0.04]" />}
            {domain && (
                <div className="flex flex-col gap-5">
                    <Notices domain={domain} />
                    <dl className="m-0">
                        <Field label="Source">
                            {sourceLabel(domain)} {dayLabel(domain.createdAt)}
                            {registered && <span className="text-muted-foreground">{" · registered in the person's name"}</span>}
                        </Field>
                        <Field label="User">{userLabel(domain.userId)}</Field>
                        {registered && (
                            <>
                                <Field label="Expires">
                                    {dayLabel(domain.expiresAt)}
                                    {daysUntil(domain.expiresAt, now()) !== null && <span className="text-muted-foreground"> · in {daysUntil(domain.expiresAt, now())} days</span>}
                                </Field>
                                <Field label="Renewable until">{dayLabel(domain.renewableUntil)}</Field>
                                <Field label="Registrant">
                                    {registrant ? (
                                        <>
                                            {registrant.organization ? `${registrant.organization} (${registrant.name})` : registrant.name}
                                            <span className="text-muted-foreground">{` · ${registrant.email}`}</span>
                                        </>
                                    ) : (
                                        <span className="text-muted-foreground">—</span>
                                    )}
                                </Field>
                                <Field label="Renewal">
                                    {domain.renewalUsd != null ? (
                                        `${formatMoneyFull(domain.renewalUsd)} ${everyLabel(domain.renewalYears ?? 1)}`
                                    ) : (
                                        <span className="text-muted-foreground">—</span>
                                    )}
                                </Field>
                            </>
                        )}
                        <Field label="Serves">
                            <ServesLinks serves={domain.serves} empty="Nothing yet: point an app or an inbox at it" />
                        </Field>
                        {domain.wildcard && <Field label="Subdomains">{`Every subdomain too (*.${domain.name})`}</Field>}
                    </dl>
                    {copiedHere && (
                        <Section title="Copied from its old DNS host">
                            <p className="m-0 mb-2 text-[12px] text-muted-foreground">
                                Check these against its old host, and add any it couldn&apos;t read below. Resolvers move over to NoClick within a day or two.
                            </p>
                            <DnsRecordList records={copiedHere} label="Copied records" />
                        </Section>
                    )}
                    {domain.noClickDns ? (
                        <BoughtDns domain={domain} />
                    ) : registered ? (
                        <DnsElsewhere domain={domain} onChanged={(records) => setCopied({ id: domain.id, records })} />
                    ) : (
                        <Section title="Records to add at its DNS host">
                            <ConnectedRecords domain={domain} onChanged={rerender} />
                        </Section>
                    )}
                    {!registered && (
                        <Section title="Transfer in">
                            <p className="m-0 mb-2 text-[13px] text-muted-foreground">
                                Move its registration to NoClick, charged to your account: it keeps what it serves, and it renews here.
                            </p>
                            <TransferDomainDialog from={domain} defaultUser={domain.userId} onOpenDomain={() => undefined} />
                        </Section>
                    )}
                    {registered && <Renewal domain={domain} onChanged={rerender} />}
                    {registered && <TransferOut domain={domain} />}
                    {registered && (
                        <p className="m-0 text-[12px] text-muted-foreground">
                            A domain registered through NoClick is never deleted: turn off auto-renew to let it lapse, or transfer it out.
                        </p>
                    )}
                </div>
            )}
        </Drawer>
    );
}
