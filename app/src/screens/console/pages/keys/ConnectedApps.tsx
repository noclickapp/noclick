// Connected apps on the API keys page: the MCP clients a person allowed on the
// consent page (OAuth grants, each a principal of its own), with the bounds set
// there (what it can do, its cap and auto-approve amount, which user) and Revoke.
// Revoked grants stay listed, muted, so a revocation is visible after the fact;
// one NoClick itself makes (its assistant's) offers Restore, which turns it back
// on as it was.
import { useCallback, useId, useState, type ReactNode } from 'react';
import { toast } from 'sonner';
import { CAPABILITY_GROUPS, listConnectedApps, restoreConnectedApp, revokeConnectedApp, type ConnectedAppView } from '@/sdk/owner';
import { formatMoney } from '@/screens/console/lib/format';
import { MCP_URL } from '@/screens/console/lib/snippets';
import { useConsole } from '@/screens/console/hooks/useConsole';
import { invalidateV1 } from '@/sdk/useV1';
import { usePaged } from '@/sdk/usePaged';
import { ConsoleButton } from '../../ui/Button';
import { CapMeter } from '../../ui/CapMeter';
import { ConsoleDialog } from '../../ui/ConsoleDialog';
import { DataTable, type Column } from '../../ui/DataTable';
import { TimeCell } from '../../ui/TimeCell';
import { MoreMenu, formError } from '../Users';

/** A client's address as people know it (`claude.ai`), or null. */
function hostOf(uri: string | null): string | null {
    if (!uri) return null;
    try {
        return new URL(uri).host;
    } catch {
        return null;
    }
}

/** The groups a grant holds, in the order the consent page lists them. */
export function orderCapabilities(capabilities: readonly string[]): string[] {
    const known = CAPABILITY_GROUPS.filter((g) => capabilities.includes(g));
    return [...known, ...capabilities.filter((c) => !(CAPABILITY_GROUPS as readonly string[]).includes(c))];
}

/** "Under $5.00", "Always asks", or nothing for a grant that can't buy. */
export function autoApproveLabel(app: Pick<ConnectedAppView, 'capabilities' | 'auto_approve_under_usd'>): string | null {
    if (!app.capabilities.includes('spend')) return null;
    return app.auto_approve_under_usd == null ? 'Always asks' : `Under ${formatMoney(app.auto_approve_under_usd)}`;
}

/** What a row's menu does to a connection: revoke it, or turn a revoked one NoClick makes back on. */
type AppAction = 'revoke' | 'restore';

const ACTIONS = {
    revoke: { call: revokeConnectedApp, verb: 'Revoke', done: 'revoked', variant: 'danger' },
    restore: { call: restoreConnectedApp, verb: 'Restore', done: 'restored', variant: 'primary' },
} as const;

function AppActionDialog({ app, action, onClose }: { app: ConnectedAppView; action: AppAction; onClose: () => void }) {
    const { client } = useConsole();
    const [error, setError] = useState<string | null>(null);
    const [busy, setBusy] = useState(false);
    const { call, verb, done, variant } = ACTIONS[action];
    const act = async () => {
        setBusy(true);
        try {
            await call(client, app.id);
            invalidateV1('connected_apps');
            toast.success(`${app.client.name} ${done}`);
            onClose();
        } catch (e) {
            setError(formError(e).message);
        } finally {
            setBusy(false);
        }
    };
    const cap = app.spend_cap_usd_per_month == null ? 'no monthly cap of its own' : `a cap of ${formatMoney(app.spend_cap_usd_per_month)} a month`;
    return (
        <ConsoleDialog
            open
            onOpenChange={(o) => !o && onClose()}
            size="sm"
            title={`${verb} ${app.client.name}?`}
            footer={
                <>
                    <ConsoleButton variant="ghost" onClick={onClose}>
                        Cancel
                    </ConsoleButton>
                    <ConsoleButton variant={variant} onClick={act} disabled={busy}>
                        {verb}
                    </ConsoleButton>
                </>
            }
        >
            <p className="m-0 text-[13px] text-muted-foreground">
                {action === 'restore'
                    ? `It comes back as it was when you revoked it: it can ${orderCapabilities(app.capabilities).join(', ')}, with ${cap}, and its own approval settings. Its next call works.`
                    : `${app.client.name}’s next call fails. ${app.restorable ? 'You can restore it here, as it is now.' : 'To use it again, connect it again and allow it.'}`}
            </p>
            {error && <p className="m-0 mt-2 text-[12px] text-red-600 dark:text-red-400">{error}</p>}
        </ConsoleDialog>
    );
}

export function ConnectedApps() {
    const { client } = useConsole();
    const headingId = useId();
    const [acting, setActing] = useState<{ app: ConnectedAppView; action: AppAction } | null>(null);
    const fetchPage = useCallback((cursor: string | null) => listConnectedApps(client, { cursor }), [client]);
    const apps = usePaged('connected_apps', fetchPage, (a) => a.id);

    // A revoked grant reads as history: everything but its name and when it was revoked is muted (in a colour that keeps its contrast, not by fading it).
    const dim = (app: ConnectedAppView, node: ReactNode) => (app.revoked_at ? <span className="text-muted-foreground [&_*]:text-muted-foreground">{node}</span> : node);

    const columns: Column<ConnectedAppView>[] = [
        {
            id: 'app',
            header: 'App',
            priority: 1,
            cell: (a) => {
                const host = hostOf(a.client.uri);
                return (
                    <span className="flex min-w-0 flex-col py-1">
                        <span className="flex min-w-0 items-center gap-2">
                            <span className={a.revoked_at ? 'truncate font-medium text-muted-foreground' : 'truncate font-medium text-foreground'}>{a.client.name}</span>
                            {a.revoked_at && <span className="shrink-0 rounded bg-foreground/[0.06] px-1.5 py-[1px] text-[12px] font-medium text-foreground/70">Revoked</span>}
                        </span>
                        {host && <span className="truncate text-[12px] text-muted-foreground">{host}</span>}
                    </span>
                );
            },
        },
        {
            id: 'capabilities',
            header: 'Can',
            priority: 2,
            width: '13rem',
            cell: (a) =>
                dim(
                    a,
                    <span className="inline-flex min-w-0 items-center gap-1 overflow-hidden" title={orderCapabilities(a.capabilities).join(', ')}>
                        {orderCapabilities(a.capabilities).map((c) => (
                            <span key={c} className="shrink-0 rounded bg-foreground/[0.05] px-1 font-mono text-[12px] text-foreground">
                                {c}
                            </span>
                        ))}
                    </span>
                ),
        },
        {
            id: 'user',
            header: 'Acts for',
            priority: 3,
            width: '8rem',
            cell: (a) => dim(a, a.user_id ? <span className="truncate">{a.user_id}</span> : <span className="text-muted-foreground">Account</span>),
        },
        {
            id: 'month',
            header: 'This month',
            priority: 1,
            align: 'right',
            className: 'w-[8.5rem] sm:w-[10rem]',
            cell: (a) => dim(a, <CapMeter spent={a.spent_usd_this_month} cap={a.spend_cap_usd_per_month} noCapLabel={a.capabilities.includes('spend')} />),
        },
        {
            id: 'auto',
            header: 'Auto-approve',
            priority: 3,
            width: '7.5rem',
            cell: (a) => {
                const label = autoApproveLabel(a);
                return dim(a, label ? <span className={a.auto_approve_under_usd == null ? 'text-muted-foreground' : 'tabular-nums'}>{label}</span> : <span className="text-muted-foreground">—</span>);
            },
        },
        {
            id: 'used',
            header: 'Last used',
            priority: 2,
            width: '8rem',
            cell: (a) =>
                a.revoked_at ? (
                    <span className="text-muted-foreground">
                        Revoked <TimeCell value={a.revoked_at} />
                    </span>
                ) : (
                    <TimeCell value={a.last_used_at} empty="Never used" />
                ),
        },
        { id: 'connected', header: 'Connected', priority: 3, width: '7rem', cell: (a) => dim(a, <TimeCell value={a.created_at} />) },
    ];

    return (
        <section aria-labelledby={headingId} className="mt-12">
            <h2 id={headingId} className="m-0 text-[16px] font-semibold tracking-tight text-foreground">
                Connected apps
            </h2>
            <p className="m-0 mb-4 mt-1 max-w-3xl text-[13px] leading-relaxed text-muted-foreground">
                AI clients you allowed to connect over MCP. Each one acts within the bounds you set when you allowed it.
            </p>
            <DataTable
                label="Connected apps"
                columns={columns}
                rows={apps.rows}
                getRowId={(a) => a.id}
                loading={apps.loading}
                error={apps.error}
                onRetry={apps.refresh}
                loadMoreError={apps.loadMoreError}
                rowActions={(a) =>
                    a.revoked_at ? (
                        a.restorable ? <MoreMenu label={`Actions for ${a.client.name}`} items={[{ label: 'Restore', onSelect: () => setActing({ app: a, action: 'restore' }) }]} /> : null
                    ) : (
                        <MoreMenu label={`Actions for ${a.client.name}`} items={[{ label: 'Revoke', danger: true, onSelect: () => setActing({ app: a, action: 'revoke' }) }]} />
                    )
                }
                nextCursor={apps.nextCursor}
                onLoadMore={apps.loadMore}
                loadingMore={apps.loadingMore}
                skeletonRows={3}
                empty={
                    <p className="m-0 py-8 text-center text-[13px] text-muted-foreground">
                        No connected apps. Add <span className="break-all font-mono text-foreground/80">{MCP_URL}</span> to Claude, ChatGPT or Cursor and allow it.
                    </p>
                }
            />
            {acting && <AppActionDialog app={acting.app} action={acting.action} onClose={() => setActing(null)} />}
        </section>
    );
}
