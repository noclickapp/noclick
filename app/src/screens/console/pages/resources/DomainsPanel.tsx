// Domains: those bought through NoClick (registered to the person, charged to the account),
// transferred in from another registrar, or connected from elsewhere, and what each serves.
// Connect, Transfer in and Buy open their dialogs; the drawer (`?domain=`) holds DNS, renewal,
// transfer out and Disconnect.
import { useConsole } from '@/screens/console/hooks/useConsole';
import { usePaged } from '@/sdk/usePaged';
import { useSearchParam } from '@/screens/console/hooks/useQueryState';
import { Domain } from 'noclick';
import { defaultWriteUser, userLabel } from '@/screens/console/lib/userFilter';
import { DataTable, type Column } from '../../ui/DataTable';
import { EmptyCode } from '../../ui/EmptyCode';
import { StatusPill } from '../../ui/StatusPill';
import { PanelToolbar, type PanelProps } from './shared';
import { BuyDomainDialog } from './DomainsBuyDialog';
import { ConnectDomainDialog } from './DomainsConnectDialog';
import { DomainDrawer } from './DomainsDrawer';
import { DOMAINS_EMPTY, ServesLinks, dayLabel, domainLook, registeredHere, sourceLabel } from './DomainsParts';
import { TransferDomainDialog } from './DomainsTransferDialog';

export function DomainsPanel({ user, setUser }: PanelProps) {
    const { client, now } = useConsole();
    const [domainId, setDomain] = useSearchParam('domain');
    const paged = usePaged(`domains?${user}`, (cursor) => Domain.listPage({ client, userFilter: user, cursor, limit: 50 }), (d) => d.id);
    const open = (id: string) => setDomain(id, { push: true });
    const columns: Column<Domain>[] = [
        {
            id: 'name',
            header: 'Domain',
            cell: (d) => <span className="truncate font-medium text-foreground">{d.name}</span>,
        },
        {
            id: 'source',
            header: 'Source',
            priority: 2,
            width: '6.5rem',
            cell: (d) => sourceLabel(d),
        },
        {
            id: 'status',
            header: 'Status',
            width: '11.5rem',
            cell: (d) => <StatusPill look={domainLook(d, now())} />,
        },
        {
            id: 'serves',
            header: 'Serves',
            priority: 3,
            cell: (d) => <ServesLinks serves={d.serves} empty="—" />,
        },
        {
            id: 'expires',
            header: 'Expires',
            priority: 2,
            width: '7.5rem',
            cell: (d) => (registeredHere(d) ? <span className="whitespace-nowrap tabular-nums">{dayLabel(d.expiresAt)}</span> : <span className="text-muted-foreground">—</span>),
        },
        {
            id: 'renew',
            header: 'Auto-renew',
            priority: 3,
            width: '6rem',
            cell: (d) => (registeredHere(d) ? (d.autoRenew ? 'On' : 'Off') : <span className="text-muted-foreground">—</span>),
        },
        {
            id: 'user',
            header: 'User',
            priority: 2,
            width: '8rem',
            cell: (d) => <span className={d.userId ? 'text-foreground/85' : 'text-muted-foreground'}>{userLabel(d.userId)}</span>,
        },
    ];
    return (
        <>
            <PanelToolbar
                user={user}
                setUser={setUser}
                action={
                    <>
                        <ConnectDomainDialog defaultUser={defaultWriteUser(user)} onOpenDomain={open} />
                        <TransferDomainDialog defaultUser={defaultWriteUser(user)} onOpenDomain={open} />
                        <BuyDomainDialog defaultUser={defaultWriteUser(user)} onOpenDomain={open} />
                    </>
                }
            />
            <DataTable
                rowMenu="domain"
                label="Domains"
                columns={columns}
                rows={paged.rows}
                getRowId={(d) => d.id}
                loading={paged.loading}
                error={paged.error}
                onRetry={() => void paged.refresh()}
                onRowClick={(d) => open(d.id)}
                selectedId={domainId}
                nextCursor={paged.nextCursor}
                onLoadMore={() => void paged.loadMore()}
                loadingMore={paged.loadingMore}
                loadMoreError={paged.loadMoreError}
                empty={
                    <EmptyCode
                        title="No domains yet."
                        hint="Buy one in your user's name, transfer one in, or connect one they own, then point an app or an inbox at it."
                        snippet={DOMAINS_EMPTY}
                    />
                }
            />
            <DomainDrawer domainId={domainId} row={paged.rows.find((d) => d.id === domainId)} onClose={() => setDomain(null)} />
        </>
    );
}
