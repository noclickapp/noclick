// Machines: NoClick reviews each account before its first machine, so this is
// where the account reads the decision (under review, approved with the
// account's machines or how to start one, or declined with NoClick's reason)
// and, until it's approved, how its code asks: the company, what its machines
// will run, and who accepted the machines usage policy and when (NewInCode's
// `machines`). The API's `action_required` for an account not yet approved
// links to this page in NoClick's own console.
import { getMachineAccess, type MachineAccessStatus, type MachineAccessView } from '@/sdk/owner';
import { formatAbsolute, formatMoney } from '@/screens/console/lib/format';
import { Machine } from 'noclick';
import { userLabel } from '@/screens/console/lib/userFilter';
import { MACHINES_START } from '@/screens/console/lib/snippets';
import type { StatusLook } from '@/screens/console/lib/status';
import { useConsole } from '@/screens/console/hooks/useConsole';
import { usePaged } from '@/sdk/usePaged';
import { useV1 } from '@/sdk/useV1';
import { NewInCode } from '../../NewInCode';
import { DataTable, type Column } from '../../ui/DataTable';
import { EmptyCode } from '../../ui/EmptyCode';
import { ErrorPanel } from '../../ui/ErrorPanel';
import { PageSection } from '../../ui/PageHeader';
import { StatusPill } from '../../ui/StatusPill';
import { Field, PanelToolbar, type PanelProps } from './shared';

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
    const access = useV1('machines/vetting', (signal) => getMachineAccess(client, signal));
    if (access.error !== undefined && !access.data) return <ErrorPanel error={access.error} onRetry={() => void access.refresh()} />;
    const a = access.data;
    if (!a) return <div aria-busy className="h-40 animate-pulse rounded-xl bg-foreground/[0.03]" />;
    return (
        <>
            {a.status !== 'not_submitted' && <Standing access={a} />}
            {a.status === 'approved' && <Machines user={user} setUser={setUser} />}
            {(a.status === 'not_submitted' || a.status === 'rejected') && (
                <PageSection
                    title={a.status === 'rejected' ? 'Ask again' : 'Ask for machines'}
                    note="NoClick reviews each account before its first machine, under the machines usage policy: no cryptocurrency mining, network scanning or bulk email, whatever runs on them. Your code asks, saying who read the policy and accepted it for your company."
                >
                    <div>
                        <NewInCode kind="machines" label={a.status === 'rejected' ? 'Ask again' : 'Ask for machines'} />
                    </div>
                </PageSection>
            )}
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
