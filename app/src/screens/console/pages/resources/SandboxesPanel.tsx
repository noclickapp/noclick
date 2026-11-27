// Sandboxes: disposable machines for running code, billed per second. The
// drawer (`?sandbox=`) shows its lifetime and when it ends, lists its background
// execs, runs a command, reads a file by path, folds its shape and region last,
// and terminates it.
import { useEffect, useState } from 'react';
import { Link } from 'react-router';
import { HAIRLINE } from '@/ui/primitives';
import { cn } from '@/ui/utils';
import { NO_USER, Operation, Sandbox, type ExecResult } from 'noclick';
import { formatRelative, truncateId } from '@/screens/console/lib/format';
import { NEW_SNIPPETS } from '@/screens/console/lib/snippets';
import { operationStatus, sandboxStatus } from '@/screens/console/lib/status';
import { defaultWriteUser, userLabel } from '@/screens/console/lib/userFilter';
import {
    useAccount,
    useConsole,
    useConsoleHref,
} from '@/screens/console/hooks/useConsole';
import { usePaged } from '@/sdk/usePaged';
import { regionLabel, useRegions } from '@/screens/console/hooks/useRegions';
import { invalidateV1, useV1 } from '@/sdk/useV1';
import { useSearchParam } from '@/screens/console/hooks/useQueryState';
import { recordRecent } from '@/screens/console/hooks/useRecent';
import { NewInCode } from '../../NewInCode';
import { ConsoleButton } from '../../ui/Button';
import { DataTable, type Column } from '../../ui/DataTable';
import { Drawer } from '../../ui/Drawer';
import { Folded, HeaderNote } from '../../ui/DrawerParts';
import { EmptyCode } from '../../ui/EmptyCode';
import { ErrorPanel } from '../../ui/ErrorPanel';
import { ExecutionTimeline } from '../../ui/ExecutionTimeline';
import { StatusPill } from '../../ui/StatusPill';
import { TimeCell } from '../../ui/TimeCell';
import { ActsFor, ConfirmAction, errorText, Field, INPUT, PanelToolbar, Section, type PanelProps } from './shared';

/** How many recent background execs the drawer checks against this sandbox. */
const EXEC_HISTORY = 10;

const raw = (s: Sandbox) =>
    s.raw as {
        image: string;
        cpu: number;
        memory_mb: number;
        network: boolean | string[];
        end_reason: string | null;
        created_at: string;
        terminated_at: string | null;
        timeout_s: number;
    };
const live = (status: string) => status === 'starting' || status === 'running';

/** The hosts it may reach, or null when it reaches anywhere or nothing. */
const hostsOf = (s: Sandbox): string[] | null => {
    const { network } = raw(s);
    return Array.isArray(network) && network.length ? network : null;
};

/** `1 CPU, 2 GB, no network`, or `, 2 hosts` for a host list. */
export function sandboxShape(s: Sandbox): string {
    const r = raw(s);
    const memory =
        r.memory_mb >= 1024
            ? `${Number((r.memory_mb / 1024).toFixed(1))} GB`
            : `${r.memory_mb} MB`;
    const hosts = hostsOf(s);
    const network = hosts ? `${hosts.length} ${hosts.length === 1 ? 'host' : 'hosts'}` : r.network === true ? 'network' : 'no network';
    return `${r.cpu} CPU, ${memory}, ${network}`;
}

/** Its lifetime as status events: running from creation, then how it ended. */
export function sandboxEvents(s: Sandbox): { status: string; at: string }[] {
    const r = raw(s);
    const events = [
        {
            status: s.status === 'starting' ? 'queued' : 'running',
            at: r.created_at,
        },
    ];
    if (r.terminated_at)
        events.push({
            status: s.status === 'failed' ? 'failed' : 'canceled',
            at: r.terminated_at,
        });
    return events;
}

function ExecForm({ sandbox }: { sandbox: Sandbox }) {
    const [command, setCommand] = useState('');
    const [busy, setBusy] = useState(false);
    const [result, setResult] = useState<ExecResult | null>(null);
    const [error, setError] = useState<string | null>(null);
    const run = async () => {
        setBusy(true);
        setError(null);
        try {
            setResult(await sandbox.exec(command));
        } catch (e) {
            setError(errorText(e));
        } finally {
            setBusy(false);
        }
    };
    return (
        <Section title="Run a command">
            <form
                className="flex flex-col gap-3"
                onSubmit={(e) => {
                    e.preventDefault();
                    void run();
                }}
            >
                <ActsFor userId={sandbox.userId} />
                <div className="flex gap-2">
                    <input
                        aria-label="Command"
                        className={cn(INPUT, 'font-mono')}
                        value={command}
                        onChange={(e) => setCommand(e.target.value)}
                        placeholder='python -c "print(2 + 2)"'
                    />
                    <ConsoleButton
                        type="submit"
                        disabled={busy || !command.trim()}
                    >
                        {busy ? 'Running…' : 'Run'}
                    </ConsoleButton>
                </div>
            </form>
            {error && (
                <p className="m-0 mt-2 text-[12px] text-red-600 dark:text-red-400">
                    {error}
                </p>
            )}
            {result && (
                <div className="mt-2 flex flex-col gap-1.5">
                    <p
                        className={cn(
                            'm-0 text-[12px]',
                            result.exitCode === 0
                                ? 'text-muted-foreground'
                                : 'text-red-600 dark:text-red-400'
                        )}
                    >
                        Exit code {result.exitCode ?? 'unknown'}
                    </p>
                    {result.stdout && (
                        <pre
                            aria-label="stdout"
                            className={cn(
                                'm-0 max-h-60 overflow-auto rounded-lg border bg-foreground/[0.03] px-3 py-2 font-mono text-[12px]',
                                HAIRLINE
                            )}
                        >
                            {result.stdout}
                        </pre>
                    )}
                    {result.stderr && (
                        <pre
                            aria-label="stderr"
                            className={cn(
                                'm-0 max-h-60 overflow-auto rounded-lg border bg-foreground/[0.03] px-3 py-2 font-mono text-[12px] text-red-600 dark:text-red-400',
                                HAIRLINE
                            )}
                        >
                            {result.stderr}
                        </pre>
                    )}
                </div>
            )}
        </Section>
    );
}

function FileReader({ sandbox }: { sandbox: Sandbox }) {
    const [path, setPath] = useState('');
    const [file, setFile] = useState<{ path: string; text: string } | null>(
        null
    );
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const read = async () => {
        setBusy(true);
        setError(null);
        try {
            setFile({ path, text: await sandbox.files.readText(path.trim()) });
        } catch (e) {
            setError(errorText(e));
        } finally {
            setBusy(false);
        }
    };
    return (
        <Section title="Files">
            <form
                className="flex gap-2"
                onSubmit={(e) => {
                    e.preventDefault();
                    void read();
                }}
            >
                <input
                    aria-label="File path"
                    className={cn(INPUT, 'font-mono')}
                    value={path}
                    onChange={(e) => setPath(e.target.value)}
                    placeholder="/workspace/out.txt"
                />
                <ConsoleButton type="submit" disabled={busy || !path.trim()}>
                    Read
                </ConsoleButton>
            </form>
            {error && (
                <p className="m-0 mt-2 text-[12px] text-red-600 dark:text-red-400">
                    {error}
                </p>
            )}
            {file && (
                <pre
                    aria-label={file.path}
                    className={cn(
                        'm-0 mt-2 max-h-72 overflow-auto rounded-lg border bg-foreground/[0.03] px-3 py-2 font-mono text-[12px]',
                        HAIRLINE
                    )}
                >
                    {file.text || '(empty file)'}
                </pre>
            )}
        </Section>
    );
}

/** Background execs are operations whose input names the sandbox; list rows omit input, so the recent ones are read in full. */
function ExecHistory({ sandbox }: { sandbox: Sandbox }) {
    const { client } = useConsole();
    const href = useConsoleHref();
    const r = raw(sandbox);
    const history = useV1(
        `operations?sandbox-execs&${sandbox.id}&${r.terminated_at ?? 'live'}`,
        async () => {
            const page = await Operation.listPage({
                client,
                kind: 'sandbox.exec',
                userFilter: sandbox.userId ?? NO_USER,
                createdAfter: r.created_at,
                createdBefore: r.terminated_at ?? undefined,
                limit: EXEC_HISTORY,
            });
            const full = await Promise.all(
                page.data.map((op) =>
                    Operation.fromId(op.id, { client, user: null }).hydrate()
                )
            );
            // Older execs past this page may still be this sandbox's, so an empty match is only "none among these".
            return {
                execs: full.filter((op) => op.input?.sandbox_id === sandbox.id),
                more: page.nextCursor !== null,
            };
        }
    );
    return (
        <Section title="Background execs">
            <p className="m-0 mb-2 text-[12px] text-muted-foreground">
                {
                    "Commands run with background: true. Foreground execs return their output directly and aren't recorded."
                }
            </p>
            {history.error !== undefined ? (
                <ErrorPanel
                    error={history.error}
                    onRetry={() => void history.refresh()}
                />
            ) : history.loading ? (
                <div
                    aria-busy
                    className="h-16 animate-pulse rounded-lg bg-foreground/[0.04]"
                />
            ) : history.data?.execs.length ? (
                <ul
                    aria-label="Background execs"
                    className={cn(
                        'm-0 -mx-3 list-none p-0',
                        HAIRLINE
                    )}
                >
                    {history.data.execs.map((op) => (
                        <li
                            key={op.id}
                            className={cn(
                                'flex items-center gap-3 border-b px-3 py-2 text-[13px] last:border-b-0',
                                HAIRLINE
                            )}
                        >
                            <TimeCell
                                value={op.createdAt}
                                tier="log"
                                className="text-muted-foreground"
                            />
                            <Link
                                to={href('logs', { op: op.id })}
                                className="min-w-0 flex-1 truncate font-mono text-[12px] hover:underline"
                            >
                                {op.summaryText ?? truncateId(op.id)}
                            </Link>
                            <StatusPill
                                look={operationStatus(op.status, null, op.kind)}
                            />
                        </li>
                    ))}
                </ul>
            ) : (
                <p className="m-0 text-[13px] text-muted-foreground">
                    {history.data?.more
                        ? `None among the last ${EXEC_HISTORY} execs ${sandbox.userId ? 'for this user' : 'in your account'}.`
                        : 'No background execs.'}
                </p>
            )}
        </Section>
    );
}

function SandboxDrawer({
    sandboxId,
    row,
    onClose,
}: {
    sandboxId: string | null;
    row?: Sandbox;
    onClose: () => void;
}) {
    const { client, now } = useConsole();
    const fetched = useV1(
        sandboxId && !row ? `sandboxes/${sandboxId}` : null,
        () => Sandbox.get(sandboxId!, { client })
    );
    const [ended, setEnded] = useState<Sandbox | null>(null);
    const sandbox =
        (ended && ended.id === sandboxId ? ended : null) ?? row ?? fetched.data;
    useEffect(() => {
        if (sandbox)
            recordRecent({
                type: 'sandbox',
                id: sandbox.id,
                label: `${raw(sandbox).image} sandbox`,
                path: 'resources/sandboxes',
                params: { sandbox: sandbox.id },
            });
    }, [sandbox?.id]); // eslint-disable-line react-hooks/exhaustive-deps
    const r = sandbox ? raw(sandbox) : null;
    const hosts = sandbox ? hostsOf(sandbox) : null;
    const regions = useRegions().data;
    return (
        <Drawer
            open={sandboxId !== null}
            onOpenChange={(o) => !o && onClose()}
            kind="Sandbox"
            title={r ? `${r.image} sandbox` : undefined}
            id={sandboxId ?? undefined}
            status={
                sandbox ? (
                    <>
                        <StatusPill
                            look={sandboxStatus(sandbox.status, r?.end_reason)}
                        />
                        {live(sandbox.status) && sandbox.expiresAt && (
                            <HeaderNote>
                                {sandboxShape(sandbox)} · ends {formatRelative(sandbox.expiresAt, now())}
                            </HeaderNote>
                        )}
                    </>
                ) : undefined
            }
            footer={
                sandbox && live(sandbox.status) ? (
                    <ConfirmAction
                        label="Terminate"
                        title="Terminate this sandbox?"
                        description="It stops now, with its files, and billing stops with it."
                        confirmLabel="Terminate"
                        onConfirm={async () => {
                            await sandbox.terminate();
                            setEnded(sandbox);
                            invalidateV1('sandboxes');
                            invalidateV1('account');
                        }}
                    />
                ) : undefined
            }
        >
            {!sandbox && fetched.error !== undefined && (
                <ErrorPanel
                    error={fetched.error}
                    onRetry={() => void fetched.refresh()}
                />
            )}
            {sandbox && r && (
                <div className="flex flex-col gap-6">
                    <ExecutionTimeline
                        events={sandboxEvents(sandbox)}
                        now={now()}
                    />
                    <ExecHistory sandbox={sandbox} />
                    {sandbox.status === 'running' && (
                        <>
                            <ExecForm sandbox={sandbox} />
                            <FileReader sandbox={sandbox} />
                        </>
                    )}
                    <Folded title="Details: its shape, network, region and user">
                        <dl className="m-0">
                            <Field label="Shape">{sandboxShape(sandbox)}</Field>
                            {hosts && (
                                <Field label="Reaches only">
                                    <span className="font-mono text-[12px]">{hosts.join(', ')}</span>
                                </Field>
                            )}
                            <Field label="Region">{regionLabel(sandbox.region, regions)}</Field>
                            <Field label="User">
                                {userLabel(sandbox.userId)}
                            </Field>
                            <Field label="Created">
                                <TimeCell value={r.created_at} tier="absolute" />
                            </Field>
                            {live(sandbox.status) ? (
                                <Field label="Expires">
                                    <TimeCell
                                        value={sandbox.expiresAt}
                                        tier="absolute"
                                    />
                                </Field>
                            ) : (
                                <Field label="Ended">
                                    <TimeCell
                                        value={r.terminated_at}
                                        tier="absolute"
                                    />
                                    {r.end_reason && (
                                        <span className="text-muted-foreground">
                                            {' '}
                                            · {r.end_reason}
                                        </span>
                                    )}
                                </Field>
                            )}
                        </dl>
                    </Folded>
                </div>
            )}
        </Drawer>
    );
}

export function SandboxesPanel({ user, setUser }: PanelProps) {
    const { client, now } = useConsole();
    const account = useAccount().data;
    const [sandboxId, setSandbox] = useSearchParam('sandbox');
    const paged = usePaged(
        `sandboxes?${user}`,
        (cursor) =>
            Sandbox.listPage({
                client,
                userFilter: user,
                cursor,
                limit: 50,
            }),
        (s) => s.id
    );
    const columns: Column<Sandbox>[] = [
        {
            id: 'image',
            header: 'Image',
            cell: (s) => <span className="truncate text-foreground">{raw(s).image}</span>,
        },
        {
            id: 'status',
            header: 'Status',
            width: '10rem',
            cell: (s) => <StatusPill look={sandboxStatus(s.status, raw(s).end_reason)} />,
        },
        {
            id: 'shape',
            header: 'Machine',
            priority: 3,
            cell: (s) => (
                <span className="text-muted-foreground">{sandboxShape(s)}</span>
            ),
        },
        {
            id: 'region',
            header: 'Region',
            priority: 3,
            width: '6rem',
            cell: (s) => <span className={s.region ? 'text-foreground/85' : 'text-muted-foreground'}>{s.region ?? 'Anywhere'}</span>,
        },
        {
            id: 'user',
            header: 'User',
            priority: 2,
            width: '8rem',
            cell: (s) => (
                <span className={s.userId ? 'text-foreground/85' : 'text-muted-foreground'}>{userLabel(s.userId)}</span>
            ),
        },
        {
            id: 'created',
            header: 'Created',
            priority: 2,
            width: '6.5rem',
            cell: (s) => <TimeCell value={raw(s).created_at} />,
        },
        {
            id: 'expires',
            header: 'Expires',
            width: '6.5rem',
            cell: (s) =>
                live(s.status) && s.expiresAt ? (
                    <span
                        className="tabular-nums"
                        title={s.expiresAt.toISOString()}
                    >
                        {formatRelative(s.expiresAt, now())}
                    </span>
                ) : (
                    <span className="text-muted-foreground">—</span>
                ),
        },
    ];
    return (
        <>
            <PanelToolbar
                user={user}
                setUser={setUser}
                limit={
                    account
                        ? `${account.counts.sandboxes_live} of ${account.limits.sandboxes_live_max} live sandboxes`
                        : null
                }
                action={
                    <NewInCode kind="sandbox" place={{ user: defaultWriteUser(user) }} />
                }
            />
            <DataTable
                rowMenu="sandbox"
                label="Sandboxes"
                columns={columns}
                rows={paged.rows}
                getRowId={(s) => s.id}
                loading={paged.loading}
                error={paged.error}
                onRetry={() => void paged.refresh()}
                onRowClick={(s) => setSandbox(s.id, { push: true })}
                selectedId={sandboxId}
                nextCursor={paged.nextCursor}
                onLoadMore={() => void paged.loadMore()}
                loadingMore={paged.loadingMore}
                empty={
                    <EmptyCode
                        title="No sandboxes yet."
                        hint="A sandbox is a disposable machine for running code, billed per second."
                        snippet={NEW_SNIPPETS.sandbox({ user: defaultWriteUser(user) })}
                    />
                }
            />
            <SandboxDrawer
                sandboxId={sandboxId}
                row={paged.rows.find((s) => s.id === sandboxId)}
                onClose={() => setSandbox(null)}
            />
        </>
    );
}
