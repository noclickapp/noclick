// Named connections, as Resources and a user's page show them: the table
// with each connection's status, a new connection (its link emailed to a
// user, or just shown), a fresh link that connects or reconnects one,
// checking one now, and deleting it.
import { useCallback, useState } from 'react';
import { toast } from 'sonner';
import { HAIRLINE } from '@/ui/primitives';
import { credentialLabel, CredentialMark } from './credentialMark';
import { Input } from '@/ui/input';
import { cn } from '@/ui/utils';
import { Connection, NO_USER, type JsonObject, type User } from 'noclick';
import { connectionStatus, type StatusLook } from '@/screens/console/lib/status';
import { userLabel, type UserFilterValue } from '@/screens/console/lib/userFilter';
import { useConsole } from '@/screens/console/hooks/useConsole';
import { invalidateV1, useV1 } from '@/sdk/useV1';
import { usePaged } from '@/sdk/usePaged';
import { ConsoleButton } from './ui/Button';
import { ConsoleDialog } from './ui/ConsoleDialog';
import { CopyButton } from './ui/CopyButton';
import { DataTable, type Column } from './ui/DataTable';
import { ErrorPanel } from './ui/ErrorPanel';
import { StatusPill } from './ui/StatusPill';
import { UserField } from './ui/UserField';
import { TimeCell } from './ui/TimeCell';
import { FormField, INPUT, MoreMenu, formError } from './pages/Users';

/** The API's rule for a connection name: 1-32 lowercase letters, digits, `-` and `_`, no `__`. */
export const CONNECTION_NAME = /^[a-z0-9][a-z0-9_-]{0,31}$/;

export function nameProblem(name: string): string | null {
    if (!name) return 'Name the connection.';
    if (!CONNECTION_NAME.test(name) || name.includes('__')) return "Use lowercase letters, digits, - and _ (up to 32, no '__').";
    return null;
}

export const integrationNodeType = (integration: string) => `automation-${integration}`;
export const nodeTypeOf = (c: Connection) => integrationNodeType(c.integration);

/** The connections of one scope (a user's id, or null for the account's own). */
export function useScopeConnections(user: string | null) {
    const { client } = useConsole();
    return useV1(`connections?scope=${user ?? NO_USER}`, () => Connection.list({ client, userFilter: user ?? NO_USER }));
}

/** The catalog of integrations, one read for every surface that shows it. */
export function useIntegrations(enabled = true) {
    const { client } = useConsole();
    return useV1(enabled ? 'integrations' : null, () => Connection.integrations(undefined, { client }));
}

export function connectionLook(c: Connection): StatusLook {
    return connectionStatus({ status: c.status, account: c.account, reachable: c.verification?.reachable ?? null, link: !!c.connectUrl });
}

/** Why a link's email didn't go out, when the API reports it; null when it went (or wasn't sent). */
export function undeliveredReason(delivery: unknown): string | null {
    const miss = (delivery as { undelivered?: JsonObject[] } | undefined)?.undelivered?.[0];
    return miss ? String(miss.reason || 'no reason given').replace(/\.$/, '') : null;
}

export function LinkShown({ url }: { url: string }) {
    return (
        <div className={cn('flex items-center gap-2 rounded-lg border bg-foreground/[0.03] px-3 py-2', HAIRLINE)}>
            <span className="min-w-0 flex-1 break-all font-mono text-[12px] text-foreground/90">{url}</span>
            <CopyButton value={url} label="Copy link" />
        </div>
    );
}

function sentLine(emailed: boolean, undelivered: string | null): string {
    if (undelivered) return `Created, but the email wasn't delivered: ${undelivered}. Copy the link and send it yourself.`;
    return emailed ? 'Sent. You can also copy the link.' : 'Send this link to whoever connects the account.';
}

/**
 * A new connection, pending until someone connects its account at the link.
 * On a user's page it's that user's and the link can be emailed to them;
 * elsewhere the User field says whose it is.
 */
export function NewConnectionDialog({ user, open, onOpenChange }: { user: User | null; open: boolean; onOpenChange: (open: boolean) => void }) {
    const { client } = useConsole();
    const integrations = useIntegrations(open);
    const [scope, setScope] = useState<string | null>(null);
    const [integration, setIntegration] = useState('');
    const [name, setName] = useState('');
    const [named, setNamed] = useState(false);
    const [reason, setReason] = useState('');
    const [email, setEmail] = useState(true);
    const [done, setDone] = useState<{ url: string; emailed: boolean; undelivered: string | null } | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [busy, setBusy] = useState(false);
    const canEmail = !!user?.email;
    const close = (next: boolean) => {
        if (!next) {
            setScope(null);
            setIntegration('');
            setName('');
            setNamed(false);
            setReason('');
            setEmail(true);
            setDone(null);
            setError(null);
        }
        onOpenChange(next);
    };
    const pick = (value: string) => {
        setIntegration(value);
        if (!named) setName(value);
    };
    const problem = nameProblem(name);
    const create = async () => {
        if (!integration) return setError('Pick the service to connect.');
        if (problem) return setError(problem);
        setBusy(true);
        setError(null);
        try {
            const emailed = canEmail && email;
            // Acts for the user it's for, so it carries that user's header.
            const connection = await Connection.create(name, {
                client,
                user: user ? user.id : scope,
                integration,
                reason: reason.trim() || undefined,
                sendTo: emailed ? 'user' : undefined,
            });
            setDone({ url: connection.connectUrl ?? '', emailed, undelivered: undeliveredReason(connection.raw.delivery) });
            invalidateV1('connections');
            invalidateV1('operations');
        } catch (e) {
            setError(formError(e).message);
        } finally {
            setBusy(false);
        }
    };
    return (
        <ConsoleDialog
            open={open}
            onOpenChange={close}
            title="New connection"
            description={
                done
                    ? sentLine(done.emailed, done.undelivered)
                    : "A named connection your code and agents use by name. It's pending until someone connects the account at its link."
            }
            footer={
                done ? (
                    <ConsoleButton variant="primary" onClick={() => close(false)}>
                        Done
                    </ConsoleButton>
                ) : (
                    <>
                        <ConsoleButton variant="ghost" onClick={() => close(false)}>
                            Cancel
                        </ConsoleButton>
                        <ConsoleButton variant="primary" onClick={create} disabled={busy}>
                            {busy ? 'Creating…' : canEmail && email ? 'Create and send' : 'Create'}
                        </ConsoleButton>
                    </>
                )
            }
        >
            {done ? (
                <LinkShown url={done.url} />
            ) : (
                <div className="flex flex-col gap-3">
                    {!user && <UserField value={scope} onChange={setScope} />}
                    <FormField label="Integration" htmlFor="connection-integration">
                        <select
                            id="connection-integration"
                            value={integration}
                            onChange={(e) => pick(e.target.value)}
                            className="h-9 rounded-md border border-input bg-background px-2 text-[13px] text-foreground [color-scheme:light] dark:[color-scheme:dark]"
                        >
                            <option value="">{integrations.loading ? 'Loading…' : 'Choose a service'}</option>
                            {/* Model providers hold what an agent thinks with (its model connection), never tools. */}
                            {(['app', 'model'] as const).map((kind) => {
                                const rows = integrations.data?.filter((i) => i.kind === kind) ?? [];
                                return (
                                    rows.length > 0 && (
                                        <optgroup key={kind} label={kind === 'app' ? 'Services' : 'Model providers'}>
                                            {rows.map((i) => (
                                                <option key={i.name} value={i.name}>
                                                    {i.label ?? i.name}
                                                </option>
                                            ))}
                                        </optgroup>
                                    )
                                );
                            })}
                        </select>
                    </FormField>
                    <FormField
                        label="Name"
                        htmlFor="connection-name"
                        hint="What your code and agents call it, e.g. gmail or work-gmail."
                        error={name && problem ? problem : null}
                    >
                        <Input
                            id="connection-name"
                            className={cn(INPUT, 'font-mono')}
                            value={name}
                            onChange={(e) => {
                                setNamed(true);
                                setName(e.target.value);
                            }}
                        />
                    </FormField>
                    <FormField label="Reason (optional)" htmlFor="connection-reason" hint="Shown on the connect page.">
                        <Input id="connection-reason" className={INPUT} value={reason} onChange={(e) => setReason(e.target.value)} />
                    </FormField>
                    {canEmail && (
                        <label className="flex items-center gap-2 text-[13px] text-foreground/85">
                            <input type="checkbox" checked={email} onChange={(e) => setEmail(e.target.checked)} />
                            Email the link to {user!.email}
                        </label>
                    )}
                    {integrations.error !== undefined && <ErrorPanel error={integrations.error} onRetry={integrations.refresh} className="bg-transparent" />}
                    {error && <p className="m-0 text-[12px] text-red-600 dark:text-red-400">{error}</p>}
                </div>
            )}
        </ConsoleDialog>
    );
}

/** A fresh link where someone connects (or reconnects) the connection's account; a user's can be emailed to them. */
export function ConnectLinkDialog({ connection, onClose }: { connection: Connection; onClose: () => void }) {
    const [reason, setReason] = useState('');
    const [email, setEmail] = useState(!!connection.userId);
    const [done, setDone] = useState<{ url: string; emailed: boolean; undelivered: string | null } | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [busy, setBusy] = useState(false);
    const reconnect = connection.status !== 'pending';
    const create = async () => {
        setBusy(true);
        setError(null);
        try {
            const emailed = !!connection.userId && email;
            const link = await connection.connectLink({ reason: reason.trim() || undefined, sendTo: emailed ? 'user' : undefined });
            setDone({ url: link.url, emailed, undelivered: link.undelivered[0] ? undeliveredReason({ undelivered: link.undelivered }) : null });
            invalidateV1('connections');
            invalidateV1('operations');
        } catch (e) {
            setError(formError(e).message);
        } finally {
            setBusy(false);
        }
    };
    return (
        <ConsoleDialog
            open
            onOpenChange={(o) => !o && onClose()}
            title={`${reconnect ? 'Reconnect' : 'Connect'} ${connection.name}`}
            description={
                done
                    ? sentLine(done.emailed, done.undelivered)
                    : reconnect
                      ? 'A new link to connect this account again. The connection keeps its name, so nothing that uses it changes.'
                      : 'A new link where someone connects this account.'
            }
            footer={
                done ? (
                    <ConsoleButton variant="primary" onClick={onClose}>
                        Done
                    </ConsoleButton>
                ) : (
                    <>
                        <ConsoleButton variant="ghost" onClick={onClose}>
                            Cancel
                        </ConsoleButton>
                        <ConsoleButton variant="primary" onClick={create} disabled={busy}>
                            {busy ? 'Creating…' : 'Create link'}
                        </ConsoleButton>
                    </>
                )
            }
        >
            {done ? (
                <LinkShown url={done.url} />
            ) : (
                <div className="flex flex-col gap-3">
                    <FormField label="Reason (optional)" htmlFor="link-reason" hint="Shown on the connect page.">
                        <Input id="link-reason" className={INPUT} value={reason} onChange={(e) => setReason(e.target.value)} />
                    </FormField>
                    {connection.userId && (
                        <label className="flex items-center gap-2 text-[13px] text-foreground/85">
                            <input type="checkbox" checked={email} onChange={(e) => setEmail(e.target.checked)} />
                            Email it to the user
                        </label>
                    )}
                    {error && <p className="m-0 text-[12px] text-red-600 dark:text-red-400">{error}</p>}
                </div>
            )}
        </ConsoleDialog>
    );
}

/** Agents and hosted MCP servers outside a connection's scope with it in their tools (designed, lab only). */
function sharedWith(connection: Connection) {
    return connection.usedBy.filter((u) => u.userId !== connection.userId);
}

const HOLDER_KINDS: Record<string, string> = { agent: 'agent', mcp_server: 'MCP server', project: 'app' };

/** What holds a connection in its own scope (agents, hosted MCP servers, apps): what loses it when it's deleted. */
function heldBy(connection: Connection) {
    return connection.usedBy.filter((u) => u.userId === connection.userId);
}

export function DeleteConnectionDialog({ connection, onClose }: { connection: Connection; onClose: () => void }) {
    const { lab } = useConsole();
    const shared = lab ? sharedWith(connection) : [];
    const held = heldBy(connection);
    const [error, setError] = useState<string | null>(null);
    const [busy, setBusy] = useState(false);
    const remove = async () => {
        setBusy(true);
        try {
            await connection.delete();
            invalidateV1('connections');
            invalidateV1('agents');
            toast.success(`Deleted ${connection.name}`);
            onClose();
        } catch (e) {
            setError(formError(e).message);
        } finally {
            setBusy(false);
        }
    };
    return (
        <ConsoleDialog
            open
            onOpenChange={(o) => !o && onClose()}
            size="sm"
            title={`Delete ${connection.name}?`}
            footer={
                <>
                    <ConsoleButton variant="ghost" onClick={onClose}>
                        Cancel
                    </ConsoleButton>
                    <ConsoleButton variant="danger" onClick={remove} disabled={busy}>
                        Delete
                    </ConsoleButton>
                </>
            }
        >
            <p className="m-0 text-[13px] text-muted-foreground">
                {"Its account is disconnected at the provider where the provider allows it. Code and agents that name it stop reaching it, and agents it was granted to lose its tools."}
            </p>
            {held.length > 0 && (
                <p className="m-0 mt-2 text-[13px] text-muted-foreground">
                    {`Held by ${held.map((u) => `${u.name} (${HOLDER_KINDS[u.kind] ?? u.kind})`).join(', ')}, which lose it.`}
                </p>
            )}
            {shared.length > 0 && (
                <p className="m-0 mt-2 text-[13px] text-muted-foreground">
                    Shared into {shared.map((u) => `${u.name} (${userLabel(u.userId)})`).join(', ')}: its tools there answer that it was deleted.
                </p>
            )}
            {error && <p className="m-0 mt-2 text-[12px] text-red-600 dark:text-red-400">{error}</p>}
        </ConsoleDialog>
    );
}

/**
 * Connections a filter covers. `blocked` disables the writes (a suspended
 * user's), with the reason on hover; `showUser` adds whose each one is.
 */
export function ConnectionsTable({
    userFilter,
    showUser = false,
    blocked = null,
    empty,
}: {
    userFilter: UserFilterValue;
    showUser?: boolean;
    blocked?: string | null;
    empty: string;
}) {
    const { client, lab } = useConsole();
    const [dialog, setDialog] = useState<{ kind: 'link' | 'delete'; connection: Connection } | null>(null);
    const fetchPage = useCallback((cursor: string | null) => Connection.listPage({ client, userFilter, cursor, limit: 50 }), [client, userFilter]);
    const connections = usePaged(`connections?user=${userFilter}`, fetchPage, (c) => c.id);

    const verify = async (c: Connection) => {
        try {
            await c.verify();
            const look = connectionLook(c);
            toast(look.reason ? `${look.label} · ${look.reason}` : look.label, { description: c.verification?.message ?? undefined });
            invalidateV1('connections');
        } catch (e) {
            toast.error(formError(e).message);
        }
    };
    const copyLink = async (url: string) => {
        try {
            await navigator.clipboard.writeText(url);
            toast.success('Link copied');
        } catch {
            toast.error("Couldn't copy the link.");
        }
    };

    const columns: Column<Connection>[] = [
        {
            id: 'name',
            header: 'Connection',
            priority: 1,
            cell: (c) => (
                <span className="inline-flex min-w-0 items-center gap-2">
                    <CredentialMark credentialType={c.credentialType ?? ''} nodeType={nodeTypeOf(c)} />
                    <span className="truncate font-medium text-foreground">{c.name}</span>
                    <span className="hidden truncate text-[12px] text-muted-foreground sm:inline">{credentialLabel(c.credentialType ?? '', nodeTypeOf(c))}</span>
                    {lab && sharedWith(c).length > 0 && (
                        <span
                            title={sharedWith(c)
                                .map((u) => `${u.name} (${userLabel(u.userId)})`)
                                .join(', ')}
                            className="shrink-0 text-[12px] text-muted-foreground"
                        >
                            · shared with {sharedWith(c).length === 1 ? sharedWith(c)[0].name : `${sharedWith(c).length} agents`}
                        </span>
                    )}
                </span>
            ),
        },
        ...(showUser
            ? [
                  {
                      id: 'user',
                      header: 'User',
                      priority: 2,
                      width: '9rem',
                      cell: (c: Connection) => <span className={c.userId ? 'text-foreground/85' : 'text-muted-foreground'}>{userLabel(c.userId)}</span>,
                  } satisfies Column<Connection>,
              ]
            : []),
        { id: 'status', header: 'Status', priority: 1, className: 'w-[9rem] sm:w-[15rem]', cell: (c) => <StatusPill look={connectionLook(c)} /> },
        { id: 'created', header: 'Created', priority: 3, width: '7rem', cell: (c) => <TimeCell value={c.createdAt} /> },
    ];

    return (
        <>
            <DataTable
                label="Connections"
                columns={columns}
                rows={connections.rows}
                getRowId={(c) => c.id}
                loading={connections.loading}
                error={connections.error}
                onRetry={connections.refresh}
                nextCursor={connections.nextCursor}
                onLoadMore={connections.loadMore}
                loadingMore={connections.loadingMore}
                rowActions={(c) => (
                    <MoreMenu
                        label={`Actions for ${c.name}`}
                        items={[
                            ...(c.connectUrl ? [{ label: 'Copy connect link', onSelect: () => void copyLink(c.connectUrl!) }] : []),
                            {
                                label: c.status === 'pending' ? 'New connect link' : 'Reconnect',
                                onSelect: () => setDialog({ kind: 'link', connection: c }),
                                disabled: !!blocked,
                                reason: blocked ?? undefined,
                            },
                            ...(c.status === 'connected'
                                ? [{ label: 'Check now', onSelect: () => void verify(c), disabled: !!blocked, reason: blocked ?? undefined }]
                                : []),
                            { label: 'Delete', danger: true, separated: true, onSelect: () => setDialog({ kind: 'delete', connection: c }), disabled: !!blocked, reason: blocked ?? undefined },
                        ]}
                    />
                )}
                empty={<p className="m-0 py-8 text-center text-[13px] text-muted-foreground">{empty}</p>}
            />
            {dialog?.kind === 'link' && <ConnectLinkDialog connection={dialog.connection} onClose={() => setDialog(null)} />}
            {dialog?.kind === 'delete' && <DeleteConnectionDialog connection={dialog.connection} onClose={() => setDialog(null)} />}
        </>
    );
}
