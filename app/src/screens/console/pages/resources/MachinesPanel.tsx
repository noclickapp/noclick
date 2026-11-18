// Machines: NoClick reviews each account before its first machine, so this is
// where the owner asks (the company, what its machines will run, the machines
// usage policy accepted), signed in, and reads the decision: under review,
// approved (with the account's machines, or how to start one) or declined with
// NoClick's reason, asked again from what was sent. The API's
// `action_required` for an account not yet approved links to this page in
// NoClick's own console. Asking is the owner's (ownerOnly.ts): a console
// acting as a key shows where the request stands and says who asks.
import { useId, useState, type FormEvent } from 'react';
import { cn } from '@/ui/utils';
import {
    getMachineAccess,
    requestMachineAccess,
    type MachineAccessStatus,
    type MachineAccessView,
} from '@/sdk/owner';
import { formatAbsolute, formatMoney } from '@/screens/console/lib/format';
import { Machine } from 'noclick';
import { userLabel } from '@/screens/console/lib/userFilter';
import { MACHINES_START } from '@/screens/console/lib/snippets';
import type { StatusLook } from '@/screens/console/lib/status';
import { useConsole } from '@/screens/console/hooks/useConsole';
import { machinesPolicyUrl } from '@/screens/console/lib/site';
import { usePaged } from '@/sdk/usePaged';
import { useV1 } from '@/sdk/useV1';
import { ConsoleButton } from '../../ui/Button';
import { DataTable, type Column } from '../../ui/DataTable';
import { EmptyCode } from '../../ui/EmptyCode';
import { ErrorPanel } from '../../ui/ErrorPanel';
import { OwnerOnlyNote } from '../../ui/OwnerOnlyNote';
import { PageSection } from '../../ui/PageHeader';
import { useOwnerOnly } from '../../ownerOnly';
import { StatusPill } from '../../ui/StatusPill';
import { errorText, Field, INPUT, LabeledInput, PanelToolbar, type PanelProps } from './shared';

const STANDING: Record<Exclude<MachineAccessStatus, 'not_submitted'>, { look: StatusLook; line: string }> = {
    pending: {
        look: { label: 'Under review', glyph: 'waiting', tone: 'ink' },
        line: 'NoClick is reviewing your request. The decision shows here, and creating a machine works once it is approved.',
    },
    approved: {
        look: { label: 'Approved', glyph: 'filled', tone: 'ink' },
        line: 'Your account can create machines.',
    },
    rejected: {
        look: { label: 'Declined', glyph: 'cross', tone: 'failure' },
        line: 'NoClick declined your request. You can ask again below, with more about your company or what will run.',
    },
};

export function MachinesPanel({ user, setUser }: PanelProps) {
    const { client } = useConsole();
    const ownerCan = useOwnerOnly();
    const access = useV1('machines/vetting', (signal) => getMachineAccess(client, signal));
    if (access.error !== undefined && !access.data) return <ErrorPanel error={access.error} onRetry={() => void access.refresh()} />;
    const a = access.data;
    if (!a) return <div aria-busy className="h-40 animate-pulse rounded-xl bg-foreground/[0.03]" />;
    return (
        <>
            {a.status !== 'not_submitted' && <Standing access={a} />}
            {a.status === 'approved' && <Machines user={user} setUser={setUser} />}
            {(a.status === 'not_submitted' || a.status === 'rejected') &&
                (ownerCan('machineAccess') ? (
                    <RequestForm key={a.status} from={a.status === 'rejected' ? a : null} onAsked={access.mutate} />
                ) : (
                    <PageSection title="Ask for machines">
                        <OwnerOnlyNote what="machineAccess" />
                    </PageSection>
                ))}
        </>
    );
}

/** A machine NoClick runs by its size; your own by its server's, once the server reported it. */
function sizeLabel(m: Machine): string {
    const shape = m.cpu ? ` · ${m.cpu} vCPU, ${m.memoryGb} GB` : '';
    return m.kind === 'own' ? `Your own${shape}` : `${m.size}${shape}`;
}

/** The account's machines once it may have them, or how to start one. */
function Machines({ user, setUser }: PanelProps) {
    const { client } = useConsole();
    const paged = usePaged(`machines?${user}`, (cursor) => Machine.listPage({ client, userFilter: user, cursor, limit: 50 }), (m) => m.id);
    const columns: Column<Machine>[] = [
        { id: 'name', header: 'Name', cell: (m) => <span className="truncate font-medium text-foreground">{m.name}</span> },
        { id: 'size', header: 'Size', width: '9rem', cell: (m) => sizeLabel(m) },
        { id: 'region', header: 'Region', width: '6rem', priority: 2, cell: (m) => m.region },
        { id: 'status', header: 'Status', width: '8rem', cell: (m) => m.status },
        { id: 'monthly', header: 'A month', width: '6rem', priority: 2, cell: (m) => <span className="tabular-nums">{formatMoney(m.monthlyUsd)}</span> },
        { id: 'user', header: 'User', width: '8rem', priority: 3, cell: (m) => userLabel(m.userId) },
    ];
    return (
        <PageSection title="Your machines">
            <PanelToolbar user={user} setUser={setUser} />
            <DataTable
                label="Machines"
                columns={columns}
                rows={paged.rows}
                getRowId={(m) => m.id}
                loading={paged.loading}
                error={paged.error}
                onRetry={() => void paged.refresh()}
                nextCursor={paged.nextCursor}
                onLoadMore={() => void paged.loadMore()}
                loadingMore={paged.loadingMore}
                empty={
                    <EmptyCode
                        title="No machines yet."
                        hint="Size, region and price ceiling are yours to choose; a machine is charged a thirtieth of its monthly price a day."
                        snippet={MACHINES_START}
                    />
                }
            />
        </PageSection>
    );
}

function Standing({ access: a }: { access: MachineAccessView }) {
    const { look, line } = STANDING[a.status as Exclude<MachineAccessStatus, 'not_submitted'>];
    return (
        <PageSection title="Your request">
            <dl className="m-0">
                <Field label="Status">
                    <StatusPill look={look} />
                </Field>
                {a.reason && <Field label="Why">{a.reason}</Field>}
                {a.company_name && <Field label="Company">{a.company_name}</Field>}
                {a.website && <Field label="Website">{a.website}</Field>}
                {a.country && <Field label="Country">{a.country}</Field>}
                {a.use_case && (
                    <Field label="What will run">
                        <span className="whitespace-pre-wrap">{a.use_case}</span>
                    </Field>
                )}
                {a.submitted_at && <Field label="Asked">{formatAbsolute(a.submitted_at)}</Field>}
                {a.decided_at && <Field label="Decided">{formatAbsolute(a.decided_at)}</Field>}
            </dl>
            <p className="m-0 mt-2 text-[13px] text-muted-foreground">{line}</p>
        </PageSection>
    );
}

/** The request, as the owner (the API refuses a key); asked again, it starts from what was sent before. */
function RequestForm({ from, onAsked }: { from: MachineAccessView | null; onAsked: (view: MachineAccessView) => void }) {
    const { client, site } = useConsole();
    const id = useId();
    const [company, setCompany] = useState(from?.company_name ?? '');
    const [website, setWebsite] = useState(from?.website ?? '');
    const [country, setCountry] = useState(from?.country ?? '');
    const [useCase, setUseCase] = useState(from?.use_case ?? '');
    const [accepted, setAccepted] = useState(false);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>(undefined);
    const ready = !!(company.trim() && website.trim() && country.trim() && useCase.trim() && accepted) && !busy;
    const title = from ? 'Ask again' : 'Ask for machines';

    const submit = async (event: FormEvent) => {
        event.preventDefault();
        if (!ready) return;
        setBusy(true);
        setError(undefined);
        try {
            onAsked(
                await requestMachineAccess(client, {
                    company_name: company.trim(),
                    website: website.trim(),
                    country: country.trim().toUpperCase(),
                    use_case: useCase.trim(),
                    accept_usage_policy: true,
                })
            );
        } catch (e) {
            setError(e);
        } finally {
            setBusy(false);
        }
    };

    return (
        <PageSection
            title={title}
            note="NoClick reviews each account before its first machine, under the machines usage policy: no cryptocurrency mining, network scanning or bulk email, whatever runs on them."
        >
            <form aria-label="Ask for machines" onSubmit={(e) => void submit(e)} className="flex max-w-xl flex-col gap-4">
                <LabeledInput label="Company name" id={`${id}-company`}>
                    <input id={`${id}-company`} value={company} onChange={(e) => setCompany(e.target.value)} maxLength={200} autoComplete="organization" className={INPUT} />
                </LabeledInput>
                <div className="flex flex-wrap gap-4">
                    <div className="min-w-[14rem] flex-1">
                        <LabeledInput label="Website" id={`${id}-website`}>
                            <input id={`${id}-website`} value={website} onChange={(e) => setWebsite(e.target.value)} maxLength={300} placeholder="https://" autoComplete="url" className={INPUT} />
                        </LabeledInput>
                    </div>
                    <div className="w-28">
                        <LabeledInput label="Country" id={`${id}-country`}>
                            <input
                                id={`${id}-country`}
                                value={country}
                                onChange={(e) => setCountry(e.target.value)}
                                maxLength={2}
                                placeholder="US"
                                autoComplete="country"
                                className={cn(INPUT, 'uppercase')}
                            />
                        </LabeledInput>
                    </div>
                </div>
                <LabeledInput label="What will your machines run?" id={`${id}-use`}>
                    <textarea
                        id={`${id}-use`}
                        value={useCase}
                        onChange={(e) => setUseCase(e.target.value)}
                        maxLength={2000}
                        rows={4}
                        placeholder="The agents or code, and what they do for your users."
                        className={cn(INPUT, 'h-auto py-2 leading-relaxed')}
                    />
                </LabeledInput>
                <label className="flex items-start gap-2 text-[13px] text-foreground">
                    <input type="checkbox" checked={accepted} onChange={(e) => setAccepted(e.target.checked)} className="mt-[3px] accent-foreground" />
                    <span>
                        I accept the{' '}
                        <a href={machinesPolicyUrl(site)} target="_blank" rel="noreferrer" className="underline underline-offset-2">
                            machines usage policy
                        </a>{' '}
                        for my company.
                    </span>
                </label>
                {error !== undefined && (
                    <p role="alert" className="m-0 text-[13px] text-red-600 dark:text-red-400">
                        {errorText(error)}
                    </p>
                )}
                <div>
                    <ConsoleButton type="submit" variant="primary" disabled={!ready}>
                        {busy ? 'Sending…' : title}
                    </ConsoleButton>
                </div>
            </form>
        </PageSection>
    );
}
