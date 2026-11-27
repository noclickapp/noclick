// A hosted MCP server, opened from Home with `?mcp=`, with the two stories kept
// apart as the product does: is the server ready (its tools resolve: its status,
// and what's wrong when none do), and has a client connected (and seen them all:
// its Clients). Then its URL (copy, rotate), and what it serves folded last. Delete asks for the name. Changes act in the
// server's own user, as every console change does.
import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';
import { HAIRLINE } from '@/ui/primitives';
import { cn } from '@/ui/utils';
import { McpServer, NoClickError, type McpClient } from 'noclick';
import { formatCount } from '@/screens/console/lib/format';
import type { StatusLook } from '@/screens/console/lib/status';
import { useConsole } from '@/screens/console/hooks/useConsole';
import { invalidateV1, useV1 } from '@/sdk/useV1';
import { recordRecent } from '@/screens/console/hooks/useRecent';
import { inputClass, toolEntryText } from '../agentParts';
import { ConsoleButton } from '../ui/Button';
import { ConsoleDialog } from '../ui/ConsoleDialog';
import { CopyButton } from '../ui/CopyButton';
import { DataTable, type Column } from '../ui/DataTable';
import { Drawer } from '../ui/Drawer';
import { Folded, Problem } from '../ui/DrawerParts';
import { ErrorPanel } from '../ui/ErrorPanel';
import { StatusPill } from '../ui/StatusPill';
import { TimeCell } from '../ui/TimeCell';
import { Field, Section } from './resources/shared';

const plural = (n: number, one: string, many = `${one}s`) => `${formatCount(n)} ${n === 1 ? one : many}`;

/** The server's own story: its tools resolve (ready), or none do. */
export function mcpServerLook(server: McpServer): StatusLook {
    return server.toolCount > 0
        ? { label: 'Ready', reason: `${plural(server.toolCount, 'tool')}`, glyph: 'check', tone: 'ink' }
        : { label: 'No tools', reason: 'check its connections', glyph: 'cross', tone: 'failure' };
}

function clientColumns(served: number): Column<McpClient>[] {
    return [
        {
            id: 'client',
            header: 'Client',
            cell: (c) => (
                <span className="flex min-w-0 items-baseline gap-1.5">
                    <span className="truncate text-foreground">{c.name}</span>
                    {c.version && <span className="shrink-0 font-mono text-[12px] text-muted-foreground">{c.version}</span>}
                </span>
            ),
        },
        {
            id: 'tools',
            header: 'Tools it saw',
            width: '7.5rem',
            cell: (c) =>
                c.toolCount === null ? (
                    <span className="text-muted-foreground">Not listed yet</span>
                ) : (
                    <span className={cn('tabular-nums', c.toolCount < served && 'text-foreground/70')} title={c.toolCount < served ? 'It listed them before you added more; most clients list again when a session starts.' : undefined}>
                        {c.toolCount < served ? `${formatCount(c.toolCount)} of ${formatCount(served)}` : formatCount(c.toolCount)}
                    </span>
                ),
        },
        { id: 'first', header: 'First seen', priority: 3, width: '7rem', cell: (c) => <TimeCell value={c.firstSeenAt} /> },
        { id: 'last', header: 'Last seen', priority: 2, width: '7rem', cell: (c) => <TimeCell value={c.lastSeenAt} /> },
    ];
}

function DeleteServer({ server, act, onDeleted, onClose }: { server: McpServer; act: McpServer; onDeleted: () => void; onClose: () => void }) {
    const [typed, setTyped] = useState('');
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>(undefined);
    const remove = async () => {
        setBusy(true);
        setError(undefined);
        try {
            await act.delete();
            toast.success(`Deleted ${server.name}`);
            onDeleted();
        } catch (err) {
            setError(err);
        } finally {
            setBusy(false);
        }
    };
    return (
        <ConsoleDialog
            open
            onOpenChange={(o) => !o && onClose()}
            size="sm"
            title={`Delete ${server.name}?`}
            description="Its URL stops answering, so every client using it loses these tools. The connections it served stay."
            footer={
                <>
                    <ConsoleButton variant="ghost" onClick={onClose}>
                        Cancel
                    </ConsoleButton>
                    <ConsoleButton variant="danger" onClick={() => void remove()} disabled={typed !== server.name || busy}>
                        {busy ? 'Deleting…' : 'Delete server'}
                    </ConsoleButton>
                </>
            }
        >
            <label className="flex flex-col gap-1.5">
                <span className="text-[12px] text-muted-foreground">
                    Type <span className="font-mono text-foreground">{server.name}</span> to confirm
                </span>
                <input value={typed} onChange={(e) => setTyped(e.target.value)} aria-label="Server name" className={inputClass} />
            </label>
            {error !== undefined && <ErrorPanel error={error} className="mt-3" />}
        </ConsoleDialog>
    );
}

function RotateServer({ act, onRotated, onClose }: { act: McpServer; onRotated: (server: McpServer) => void; onClose: () => void }) {
    const [busy, setBusy] = useState(false);
    const rotate = async () => {
        setBusy(true);
        try {
            onRotated(await act.rotate());
            toast.success('New URL made; the old one stopped');
            onClose();
        } catch (err) {
            toast.error(err instanceof Error ? err.message : String(err), { description: err instanceof NoClickError ? (err.nextStep ?? undefined) : undefined });
        } finally {
            setBusy(false);
        }
    };
    return (
        <ConsoleDialog
            open
            onOpenChange={(o) => !o && onClose()}
            size="sm"
            title="Give it a new URL?"
            description="The current URL stops answering at once. Paste the new one into each client that uses it."
            footer={
                <>
                    <ConsoleButton variant="ghost" onClick={onClose}>
                        Cancel
                    </ConsoleButton>
                    <ConsoleButton variant="danger" onClick={() => void rotate()} disabled={busy}>
                        {busy ? 'Rotating…' : 'Rotate URL'}
                    </ConsoleButton>
                </>
            }
        />
    );
}

/** How its clients stand, in a line: none yet, some behind on its tools, or all caught up. */
function clientsLine(server: McpServer, clients: McpClient[]): string {
    const behind = clients.filter((c) => c.toolCount !== null && c.toolCount < server.toolCount).length;
    if (!clients.length) return 'No client has connected yet. Most clients connect when a session starts: open a new chat after adding the URL.';
    if (behind) return `${plural(behind, 'client')} listed its tools before you added more; they see the rest in their next session.`;
    return `${plural(clients.length, 'client')} connected, each with all of its tools.`;
}

export function McpServerDrawer({ serverId, row, onClose }: { serverId: string; row?: McpServer; onClose: () => void }) {
    const { client } = useConsole();
    const fetched = useV1(row ? null : `mcp_servers/${serverId}`, () => McpServer.get(serverId, { client, user: null }));
    // A rotate answers the same object with a new URL; the tick re-renders it.
    const [changed, setChanged] = useState<{ server: McpServer; tick: number } | null>(null);
    const server = (changed && changed.server.id === serverId ? changed.server : null) ?? row ?? fetched.data;
    const userId = server?.userId ?? null;
    const act = useMemo(() => McpServer.fromId(serverId, { client, user: userId }), [client, serverId, userId]);
    const clients = useV1(server ? `mcp_servers/${serverId}/clients` : null, () => act.clients());
    const [rotating, setRotating] = useState(false);
    const [deleting, setDeleting] = useState(false);
    useEffect(() => {
        if (server) recordRecent({ type: 'MCP server', id: server.id, label: server.name, path: '', params: { mcp: server.id } });
    }, [server?.id]); // eslint-disable-line react-hooks/exhaustive-deps
    return (
        <Drawer
            open
            onOpenChange={(o) => !o && onClose()}
            kind="MCP server"
            title={server?.name}
            id={serverId}
            status={server ? <StatusPill look={mcpServerLook(server)} /> : undefined}
            footer={
                server ? (
                    <ConsoleButton variant="danger" size="sm" onClick={() => setDeleting(true)}>
                        Delete server
                    </ConsoleButton>
                ) : undefined
            }
        >
            {!server && fetched.error !== undefined ? (
                <ErrorPanel error={fetched.error} onRetry={() => void fetched.refresh()} />
            ) : !server ? (
                <div aria-busy className="h-40 animate-pulse rounded-lg bg-foreground/[0.04]" />
            ) : (
                <div className="flex flex-col gap-6">
                    {server.toolCount === 0 && (
                        <Problem title="None of its tools resolve">A connection it names isn&apos;t connected, so a client that connects sees no tools.</Problem>
                    )}
                    <Section title="Clients">
                        {clients.data && <p className="m-0 mb-2 text-[12px] text-muted-foreground">{clientsLine(server, clients.data)}</p>}
                        {(!clients.data || clients.data.length > 0) && (
                            <DataTable
                                label="Clients"
                                columns={clientColumns(server.toolCount)}
                                rows={clients.data ?? []}
                                getRowId={(c) => `${c.name}@${c.version ?? ''}`}
                                loading={!clients.data && clients.error === undefined}
                                error={clients.error}
                                onRetry={() => void clients.refresh()}
                                skeletonRows={2}
                            />
                        )}
                    </Section>
                    <Section title="URL">
                        <div className={cn('flex items-center gap-2 rounded-lg border bg-foreground/[0.03] px-3 py-2', HAIRLINE)}>
                            <span className="min-w-0 flex-1 break-all font-mono text-[12px] text-foreground/90">{server.url}</span>
                            <CopyButton value={server.url} label="Copy server URL" />
                        </div>
                        <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
                            <p className="m-0 min-w-0 flex-1 text-[12px] text-muted-foreground">Paste it into Claude, ChatGPT, Cursor or any MCP client. Anyone with it can call these tools; rotate it if it leaks.</p>
                            <ConsoleButton size="sm" variant="ghost" onClick={() => setRotating(true)}>
                                Rotate URL
                            </ConsoleButton>
                        </div>
                    </Section>
                    <Folded title="Details: what it serves, its user">
                        <dl className="m-0">
                            <Field label="Serves">
                                <span className="flex flex-wrap gap-1">
                                    {server.tools.map((t, i) => (
                                        <span key={i} className="rounded-md bg-foreground/[0.05] px-1.5 py-[1px] font-mono text-[12px] text-foreground/85">
                                            {toolEntryText(t)}
                                        </span>
                                    ))}
                                </span>
                            </Field>
                            <Field label="User">{server.userId ? <span>{server.userId}</span> : 'Your account'}</Field>
                            <Field label="Created">
                                <TimeCell value={server.createdAt} tier="absolute" />
                            </Field>
                        </dl>
                    </Folded>
                </div>
            )}
            {rotating && server && (
                <RotateServer
                    act={act}
                    onRotated={(s) => {
                        setChanged((c) => ({ server: s, tick: (c?.tick ?? 0) + 1 }));
                        invalidateV1('mcp_servers?home');
                    }}
                    onClose={() => setRotating(false)}
                />
            )}
            {deleting && server && (
                <DeleteServer
                    server={server}
                    act={act}
                    onClose={() => setDeleting(false)}
                    onDeleted={() => {
                        invalidateV1('mcp_servers');
                        invalidateV1('account');
                        setDeleting(false);
                        onClose();
                    }}
                />
            )}
        </Drawer>
    );
}
