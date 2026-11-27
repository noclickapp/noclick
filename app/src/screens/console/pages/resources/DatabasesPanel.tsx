// Databases: SQL databases your apps
// and agents keep their data in. The drawer (`?database=`) says what it holds beside its status, then shows the schema,
// runs a read-only select, lists branches, restores to a time and exports, its migrations and what uses it folded last,
// and deletes. The
// database an automation keeps its tables in is written only by the automation and
// goes with it: its drawer reads it, branches and exports it.
import { useEffect, useState } from 'react';
import { Link } from 'react-router';
import { ChevronRight, GitBranch, History } from 'lucide-react';
import { toast } from 'sonner';
import { HAIRLINE } from '@/ui/primitives';
import { cn } from '@/ui/utils';
import { DateField } from '@/ui/DateField';
import { Database, type Operation, type QueryResult, type Table, type UsedBy } from 'noclick';
import { NEW_SNIPPETS } from '@/screens/console/lib/snippets';
import { isReadQuery } from '@/lib/tableQuery';
import type { StatusLook } from '@/screens/console/lib/status';
import { formatRelative } from '@/screens/console/lib/format';
import { defaultWriteUser, userLabel } from '@/screens/console/lib/userFilter';
import { useConsole, useConsoleHref } from '@/screens/console/hooks/useConsole';
import { usePaged } from '@/sdk/usePaged';
import { useSearchParam } from '@/screens/console/hooks/useQueryState';
import { recordRecent } from '@/screens/console/hooks/useRecent';
import { invalidateV1, useV1, type V1State } from '@/sdk/useV1';
import { NewInCode } from '../../NewInCode';
import { ConsoleButton } from '../../ui/Button';
import { ConsoleDialog } from '../../ui/ConsoleDialog';
import { DataTable, type Column } from '../../ui/DataTable';
import { Drawer, SHEET_SURFACE } from '../../ui/Drawer';
import { Folded, HeaderNote } from '../../ui/DrawerParts';
import { EmptyCode } from '../../ui/EmptyCode';
import { ErrorPanel } from '../../ui/ErrorPanel';
import { SwitchRow } from '../../ui/SwitchRow';
import { IdChip } from '../../ui/IdChip';
import { Segmented } from '../../ui/Segmented';
import { StatusPill } from '../../ui/StatusPill';
import { TimeCell } from '../../ui/TimeCell';
import { errorText, Field, INPUT, LabeledInput, PanelToolbar, Section, type PanelProps } from './shared';
import { DeleteByName, ExportSection, formatExact, formatSize, UsedByText } from './StorageShared';

/** Point-in-time history by engine, as the design keeps it. */
const HISTORY_DAYS: Record<string, number> = { sqlite: 30, postgres: 7 };
/** Rows the query box shows of a result. */
const SHOWN_ROWS = 200;

export const ENGINE_LABEL: Record<string, string> = { sqlite: 'SQLite', postgres: 'Postgres' };

export function databaseStatus(status: string): StatusLook {
    switch (status) {
        case 'ready':
            return { label: 'Ready', glyph: 'check', tone: 'ink' };
        case 'restoring':
            return { label: 'Restoring', glyph: 'filled', tone: 'ink' };
        case 'branching':
            return { label: 'Branching', glyph: 'filled', tone: 'ink' };
        default:
            return { label: status, glyph: 'muted', tone: 'muted' };
    }
}

/** Who holds a database back from deletion: `booking binds it and concierge has it in its tools`. */
function inUse(users: readonly UsedBy[]): string {
    const apps = users.filter((u) => u.kind !== 'agent').map((u) => u.name);
    const agents = users.filter((u) => u.kind === 'agent').map((u) => u.name);
    return [
        apps.length ? `${apps.join(', ')} ${apps.length === 1 ? 'binds' : 'bind'} it` : '',
        agents.length ? `${agents.join(', ')} ${agents.length === 1 ? 'has it in its' : 'have it in their'} tools` : '',
    ]
        .filter(Boolean)
        .join(' and ');
}

/** `2026-09-26T15:20` in local time, as a date-and-time field (`DateField`) holds it. */
function localInput(ms: number): string {
    const d = new Date(ms);
    const pad = (n: number) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** Why a restore or branch time can't be used for a database of `engine`, or null. */
function historyError(value: string, now: number, engine: string): string | null {
    const at = Date.parse(value);
    const days = HISTORY_DAYS[engine];
    if (Number.isNaN(at)) return 'Pick a date and time.';
    if (at > now) return "That's in the future.";
    if (at < now - days * 86_400_000) return `A ${ENGINE_LABEL[engine]} database keeps ${days} days of history.`;
    return null;
}

/** An operation this drawer started: what it is, and where to follow it. */
function Started({ op, what }: { op: Operation<Database>; what: string }) {
    const href = useConsoleHref();
    return (
        <p className="m-0 mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px] text-muted-foreground">
            <StatusPill look={{ label: 'Running', glyph: 'filled', tone: 'ink' }} />
            <span>{what}</span>
            <Link to={href('logs', { op: op.id })} className="text-foreground underline-offset-2 hover:underline">
                Follow the operation
            </Link>
        </p>
    );
}

function SchemaSection({ db, schema, onQuery }: { db: Database; schema: V1State<Table[]>; onQuery: (sql: string) => void }) {
    const [open, setOpen] = useState<string | null>(null);
    const estimate = db.engine === 'postgres';
    return (
        <Section title="Schema">
            {schema.error !== undefined ? (
                <ErrorPanel error={schema.error} onRetry={() => void schema.refresh()} />
            ) : schema.loading ? (
                <div aria-busy className="h-24 animate-pulse rounded-lg bg-foreground/[0.04]" />
            ) : schema.data?.length ? (
                <ul aria-label="Tables" className={'m-0 -mx-3 list-none p-0'}>
                    {schema.data.map((t) => (
                        <TableRow key={t.name} table={t} estimate={estimate} open={open === t.name} onToggle={() => setOpen(open === t.name ? null : t.name)} onQuery={onQuery} />
                    ))}
                </ul>
            ) : (
                <p className="m-0 text-[13px] text-muted-foreground">No tables yet. Your code creates them with db.migrate or db.execute.</p>
            )}
        </Section>
    );
}

function TableRow({ table, estimate, open, onToggle, onQuery }: { table: Table; estimate: boolean; open: boolean; onToggle: () => void; onQuery: (sql: string) => void }) {
    return (
        <li>
            <div className="flex items-center gap-2 px-3 py-2">
                <button type="button" aria-expanded={open} onClick={onToggle} className="flex min-w-0 flex-1 items-center gap-2 text-left">
                    <ChevronRight className={cn('h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform', open && 'rotate-90')} />
                    <span className="truncate font-mono text-[13px] text-foreground">{table.name}</span>
                    <span className="shrink-0 text-[12px] tabular-nums text-muted-foreground">
                        {estimate ? '≈' : ''}
                        {formatExact(table.rowCount)} {table.rowCount === 1 ? 'row' : 'rows'}
                    </span>
                </button>
                <ConsoleButton variant="ghost" size="sm" onClick={() => onQuery(`select * from ${table.name} limit 20`)}>
                    Query
                </ConsoleButton>
            </div>
            {open && (
                <table aria-label={`Columns of ${table.name}`} className="mb-2 ml-8 mr-3 w-[calc(100%-2.75rem)] border-collapse text-[12px]">
                    <tbody>
                        {table.columns.map((c) => (
                            <tr key={c.name}>
                                <td className="w-2/5 py-0.5 pr-3 font-mono text-foreground/90">{c.name}</td>
                                <td className="py-0.5 pr-3 font-mono text-muted-foreground">{c.type}</td>
                                <td className="py-0.5 text-muted-foreground">
                                    {[c.primaryKey && 'primary key', !c.nullable && !c.primaryKey && 'not null', c.default !== null && `default ${c.default}`].filter(Boolean).join(' · ')}
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            )}
        </li>
    );
}

function ResultTable({ result }: { result: QueryResult }) {
    const shown = result.rows.slice(0, SHOWN_ROWS);
    return (
        <div className="mt-2 flex flex-col gap-1.5">
            <p className="m-0 text-[12px] tabular-nums text-muted-foreground">
                {formatExact(result.rows.length)} {result.rows.length === 1 ? 'row' : 'rows'}
                {result.rows.length > SHOWN_ROWS ? `, the first ${SHOWN_ROWS} shown` : ''} · read {formatExact(result.rowsRead)}
                {result.durationMs !== null ? ` · ${result.durationMs} ms` : ''}
            </p>
            {result.columns.length > 0 && (
                <div className={cn('max-h-72 overflow-auto rounded-lg border', HAIRLINE)}>
                    <table aria-label="Result" className="w-full border-collapse font-mono text-[12px]">
                        <thead className={cn('sticky top-0', SHEET_SURFACE)}>
                            <tr>
                                {result.columns.map((c) => (
                                    <th key={c} scope="col" className={cn('whitespace-nowrap border-b px-3 py-1.5 text-left font-medium text-muted-foreground', HAIRLINE)}>
                                        {c}
                                    </th>
                                ))}
                            </tr>
                        </thead>
                        <tbody>
                            {shown.map((row, i) => (
                                <tr key={i}>
                                    {result.columns.map((c) => (
                                        <td key={c} className="max-w-[16rem] truncate whitespace-nowrap px-3 py-1.5 text-foreground/90">
                                            {row[c] === null || row[c] === undefined ? <span className="text-muted-foreground">NULL</span> : String(row[c])}
                                        </td>
                                    ))}
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}
        </div>
    );
}

function QuerySection({ db, sql, setSql, table }: { db: Database; sql: string; setSql: (sql: string) => void; table?: string }) {
    const [busy, setBusy] = useState(false);
    const [result, setResult] = useState<QueryResult | null>(null);
    const [error, setError] = useState<string | null>(null);
    const typed = sql.trim().length > 0;
    const readable = isReadQuery(sql);
    const run = async () => {
        if (!readable) return;
        setBusy(true);
        setError(null);
        try {
            setResult(await db.query(sql.trim()));
        } catch (e) {
            setResult(null);
            setError(errorText(e));
        } finally {
            setBusy(false);
        }
    };
    return (
        <Section title="Query">
            <form
                className="flex flex-col gap-2"
                onSubmit={(e) => {
                    e.preventDefault();
                    void run();
                }}
            >
                <textarea
                    aria-label="SQL"
                    rows={3}
                    spellCheck={false}
                    value={sql}
                    onChange={(e) => setSql(e.target.value)}
                    onKeyDown={(e) => {
                        if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                            e.preventDefault();
                            void run();
                        }
                    }}
                    placeholder={`select * from ${table ?? 'my_table'} limit 20`}
                    className={cn(INPUT, 'h-auto resize-y py-2 font-mono leading-relaxed')}
                />
                <div className="flex items-center gap-3">
                    <p className="m-0 min-w-0 flex-1 text-[12px] text-muted-foreground">
                        {typed && !readable ? 'Only one select runs here. Run writes from your code with db.execute.' : 'Read-only: one select at a time, as db.query runs it.'}
                    </p>
                    <ConsoleButton type="submit" disabled={busy || !readable}>
                        {busy ? 'Running…' : 'Run'}
                    </ConsoleButton>
                </div>
            </form>
            {error && <p className="m-0 mt-2 text-[12px] text-red-600 dark:text-red-400">{error}</p>}
            {result && <ResultTable result={result} />}
        </Section>
    );
}

function BranchDialog({ db, open, onOpenChange, onStarted }: { db: Database; open: boolean; onOpenChange: (open: boolean) => void; onStarted: (op: Operation<Database>, name: string) => void }) {
    const { now } = useConsole();
    const [name, setName] = useState(`${db.name}-preview`);
    const [from, setFrom] = useState<'now' | 'time'>('now');
    const [at, setAt] = useState(() => localInput(now() - 3_600_000));
    const [postgres, setPostgres] = useState(false);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>(undefined);
    const timeError = from === 'time' ? historyError(at, now(), db.engine) : null;
    const start = async () => {
        setBusy(true);
        setError(undefined);
        try {
            const op = await db.branch(name.trim(), { at: from === 'time' ? new Date(at) : undefined, engine: postgres ? 'postgres' : undefined });
            onStarted(op, name.trim());
            onOpenChange(false);
        } catch (e) {
            setError(e);
        } finally {
            setBusy(false);
        }
    };
    return (
        <ConsoleDialog
            open={open}
            onOpenChange={onOpenChange}
            mark={<GitBranch aria-hidden className="h-5 w-5" />}
            title={`Branch ${db.name}`}
            description="A copy that's a database of its own, with the same owner. Changes to one never reach the other."
            footer={
                <ConsoleButton variant="primary" disabled={busy || !name.trim() || timeError !== null} onClick={() => void start()}>
                    {busy ? 'Starting…' : 'Branch'}
                </ConsoleButton>
            }
        >
            <div className="flex flex-col gap-3">
                <LabeledInput label="Name" id="branch-name">
                    <input id="branch-name" className={cn(INPUT, 'font-mono')} value={name} onChange={(e) => setName(e.target.value)} autoComplete="off" />
                </LabeledInput>
                <div className="flex flex-col gap-1.5">
                    <span className="text-[12px] font-medium text-muted-foreground">Copy</span>
                    <Segmented
                        label="Copy"
                        value={from}
                        onChange={setFrom}
                        options={[
                            { value: 'now', label: 'As it is now' },
                            { value: 'time', label: 'As it was at' },
                        ]}
                    />
                </div>
                {from === 'time' && (
                    <LabeledInput label="Time (your time zone)" id="branch-at">
                        <DateField id="branch-at" withTime value={at} onChange={setAt} />
                    </LabeledInput>
                )}
                {timeError && <p className="m-0 text-[12px] text-red-600 dark:text-red-400">{timeError}</p>}
                {db.engine === 'sqlite' && (
                    <SwitchRow label="Branch into Postgres" description="The way past SQLite's 10 GB. Point your app at the branch once it's ready." checked={postgres} onCheckedChange={setPostgres} />
                )}
                {error !== undefined && <ErrorPanel error={error} />}
            </div>
        </ConsoleDialog>
    );
}

function BranchesSection({ db, onOpen }: { db: Database; onOpen: (id: string) => void }) {
    const branches = useV1(`databases/${db.id}/branches`, () => db.branches());
    const [branching, setBranching] = useState(false);
    const [started, setStarted] = useState<{ op: Operation<Database>; name: string } | null>(null);
    return (
        <section>
            <div className="mb-2 flex items-center justify-between gap-2">
                <h3 className="m-0 text-[14px] font-semibold tracking-[-0.01em] text-foreground">Branches</h3>
                <ConsoleButton size="sm" onClick={() => setBranching(true)}>
                    New branch
                </ConsoleButton>
            </div>
            {branches.error !== undefined ? (
                <ErrorPanel error={branches.error} onRetry={() => void branches.refresh()} />
            ) : branches.loading ? (
                <div aria-busy className="h-12 animate-pulse rounded-lg bg-foreground/[0.04]" />
            ) : branches.data?.length ? (
                <ul aria-label="Branches" className={'m-0 -mx-3 list-none p-0'}>
                    {branches.data.map((b) => (
                        <li key={b.id}>
                            <button type="button" onClick={() => onOpen(b.id)} className="flex w-full items-center gap-3 px-3 py-2 text-left text-[13px] transition-colors hover:bg-foreground/[0.03]">
                                <span className="min-w-0 flex-1 truncate font-medium text-foreground">{b.name}</span>
                                <span className="shrink-0 text-muted-foreground">{ENGINE_LABEL[b.engine] ?? b.engine}</span>
                                <span className="w-16 shrink-0 text-right tabular-nums text-muted-foreground">{formatSize(b.sizeBytes)}</span>
                                <span className="hidden w-20 shrink-0 text-right text-muted-foreground sm:block">{b.createdAt ? <TimeCell value={b.createdAt} /> : null}</span>
                                <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                            </button>
                        </li>
                    ))}
                </ul>
            ) : (
                <p className="m-0 text-[13px] text-muted-foreground">No branches. A branch is a copy to try a migration on, or to recover data from, without touching this one.</p>
            )}
            {started && <Started op={started.op} what={`Branching into ${started.name}.`} />}
            {branching && (
                <BranchDialog
                    db={db}
                    open={branching}
                    onOpenChange={setBranching}
                    onStarted={(op, name) => {
                        setStarted({ op, name });
                        invalidateV1('databases');
                        toast(`Branching ${db.name} into ${name}`);
                    }}
                />
            )}
        </section>
    );
}

function RestoreSection({ db }: { db: Database }) {
    const { now } = useConsole();
    const [open, setOpen] = useState(false);
    const [at, setAt] = useState(() => localInput(now() - 3_600_000));
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>(undefined);
    const [started, setStarted] = useState<{ op: Operation<Database>; at: string } | null>(null);
    const timeError = historyError(at, now(), db.engine);
    const when = Number.isNaN(Date.parse(at)) ? at : new Date(at).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    const restore = async () => {
        setBusy(true);
        setError(undefined);
        try {
            const op = await db.restore({ at: new Date(at) });
            setStarted({ op, at: when });
            setOpen(false);
            invalidateV1('databases');
            toast(`Restoring ${db.name} to ${when}`);
        } catch (e) {
            setError(e);
        } finally {
            setBusy(false);
        }
    };
    return (
        <Section title="Restore">
            <div className="flex flex-wrap items-center gap-3">
                <p className="m-0 min-w-0 flex-1 text-[13px] text-muted-foreground">Every change is kept for {HISTORY_DAYS[db.engine]} days. Put the database back as it was at any moment in that window.</p>
                <ConsoleButton
                    size="sm"
                    onClick={() => {
                        setAt(localInput(now() - 3_600_000));
                        setError(undefined);
                        setOpen(true);
                    }}
                >
                    Restore to a time
                </ConsoleButton>
            </div>
            {started && <Started op={started.op} what={`Restoring to ${started.at}.`} />}
            <ConsoleDialog
                open={open}
                onOpenChange={setOpen}
                size="sm"
                tone="danger"
                mark={<History aria-hidden className="h-5 w-5" />}
                title={`Restore ${db.name}`}
                description="In place: everything written after that moment is gone. To keep it, branch at that time instead."
                footer={
                    <>
                        <ConsoleButton variant="ghost" onClick={() => setOpen(false)}>
                            Cancel
                        </ConsoleButton>
                        <ConsoleButton variant="danger" disabled={busy || timeError !== null} onClick={() => void restore()}>
                            {busy ? 'Starting…' : 'Restore'}
                        </ConsoleButton>
                    </>
                }
            >
                <div className="flex flex-col gap-2">
                    <LabeledInput label="Restore to (your time zone)" id="restore-at">
                        <DateField id="restore-at" withTime value={at} onChange={setAt} />
                    </LabeledInput>
                    {timeError ? (
                        <p className="m-0 text-[12px] text-red-600 dark:text-red-400">{timeError}</p>
                    ) : (
                        <p className="m-0 text-[12px] text-muted-foreground">{"While it runs, queries are refused. Apps that bind it see the restored data when it's done."}</p>
                    )}
                    {error !== undefined && <ErrorPanel error={error} />}
                </div>
            </ConsoleDialog>
        </Section>
    );
}

function MigrationsLine({ db }: { db: Database }) {
    const { now } = useConsole();
    const migrations = useV1(`databases/${db.id}/migrations`, () => db.migrations());
    if (migrations.error !== undefined) return <span className="text-muted-foreground">{"Couldn't load them."}</span>;
    if (!migrations.data) return <span className="text-muted-foreground">…</span>;
    const last = migrations.data.at(-1);
    if (!last) return <span className="text-muted-foreground">None applied</span>;
    return (
        <span>
            {migrations.data.length} applied
            <span className="text-muted-foreground">
                {' '}
                · last <span className="font-mono text-[12px]">{last.name}</span>
                {last.appliedAt ? `, ${formatRelative(last.appliedAt, now())}` : ''}
            </span>
        </span>
    );
}

function DatabaseDrawer({ databaseId, row, rows, onOpen, onClose }: { databaseId: string | null; row?: Database; rows: readonly Database[]; onOpen: (id: string) => void; onClose: () => void }) {
    const { client } = useConsole();
    const fetched = useV1(databaseId && !row ? `databases/${databaseId}` : null, () => Database.get(databaseId!, { client }));
    const db = row ?? fetched.data;
    const schema = useV1(db ? `databases/${db.id}/schema` : null, () => db!.schema());
    const [sql, setSql] = useState('');
    useEffect(() => setSql(''), [databaseId]);
    useEffect(() => {
        if (db) recordRecent({ type: 'database', id: db.id, label: db.name, path: 'resources/databases', params: { database: db.id } });
    }, [db?.id]); // eslint-disable-line react-hooks/exhaustive-deps
    const parent = db?.parentId ? rows.find((d) => d.id === db.parentId) : undefined;
    return (
        <Drawer
            open={databaseId !== null}
            onOpenChange={(o) => !o && onClose()}
            kind="Database"
            wide
            title={db?.name}
            id={databaseId ?? undefined}
            status={
                db ? (
                    <>
                        <StatusPill look={databaseStatus(db.status)} />
                        <HeaderNote>
                            {ENGINE_LABEL[db.engine] ?? db.engine} · {formatSize(db.sizeBytes)}
                            {db.engine === 'sqlite' && ' of 10 GB'}
                            {db.tableCount != null && ` · ${db.tableCount === 1 ? '1 table' : `${formatExact(db.tableCount)} tables`}`}
                        </HeaderNote>
                    </>
                ) : undefined
            }
            footer={
                db?.workflow ? (
                    <span className="text-[13px] text-muted-foreground">Its automation keeps its tables here: they change in the automation, and go when it’s deleted.</span>
                ) : db ? (
                    <DeleteByName
                        label="Delete database"
                        name={db.name}
                        description={
                            db.usedBy.length
                                ? `${inUse(db.usedBy)}, so the delete is refused until nothing uses it. Its data and history go with it.`
                                : "Its tables, data and history are deleted now and can't be restored. One with branches is refused until they're deleted."
                        }
                        onConfirm={async () => {
                            await db.delete();
                            invalidateV1('databases');
                            invalidateV1('account');
                            toast(`Deleted ${db.name}`);
                            onClose();
                        }}
                    />
                ) : undefined
            }
        >
            {!db && fetched.error !== undefined && <ErrorPanel error={fetched.error} onRetry={() => void fetched.refresh()} />}
            {!db && fetched.error === undefined && <div aria-busy className="h-40 animate-pulse rounded-lg bg-foreground/[0.04]" />}
            {db && (
                <div key={db.id} className="flex flex-col gap-6">
                    <SchemaSection db={db} schema={schema} onQuery={setSql} />
                    <QuerySection db={db} sql={sql} setSql={setSql} table={schema.data?.[0]?.name} />
                    <BranchesSection db={db} onOpen={onOpen} />
                    {!db.workflow && <RestoreSection db={db} />}
                    <ExportSection what={`A SQL dump of the schema and data, loadable into any ${ENGINE_LABEL[db.engine] ?? ''} database.`} start={() => db.export()} />
                    <Folded title="Details: migrations, what uses it, its user">
                        <dl className="m-0">
                            <Field label="Migrations">
                                <MigrationsLine db={db} />
                            </Field>
                            <Field label="Used by">
                                <UsedByText users={db.usedBy} />
                            </Field>
                            {db.workflow?.name && <Field label="Tables of">The {db.workflow.name} automation</Field>}
                            {db.parentId && (
                                <Field label="Branch of">
                                    <button type="button" onClick={() => onOpen(db.parentId!)} className="text-foreground underline-offset-2 hover:underline">
                                        {parent?.name ?? <IdChip id={db.parentId} />}
                                    </button>
                                </Field>
                            )}
                            <Field label="User">{userLabel(db.userId)}</Field>
                            <Field label="Created">
                                <TimeCell value={db.createdAt} tier="absolute" />
                            </Field>
                        </dl>
                    </Folded>
                </div>
            )}
        </Drawer>
    );
}

export function DatabasesPanel({ user, setUser }: PanelProps) {
    const { client } = useConsole();
    const [databaseId, setDatabase] = useSearchParam('database');
    const paged = usePaged(`databases?${user}`, (cursor) => Database.listPage({ client, userFilter: user, cursor, limit: 50 }), (d) => d.id);
    const nameOf = (id: string) => paged.rows.find((d) => d.id === id)?.name;
    const columns: Column<Database>[] = [
        {
            id: 'name',
            header: 'Name',
            cell: (d) => (
                <span className="flex min-w-0 flex-col">
                    <span className="flex min-w-0 items-center gap-2">
                        <span className="truncate font-medium text-foreground">{d.name}</span>
                        {d.status !== 'ready' && <StatusPill look={databaseStatus(d.status)} />}
                    </span>
                    {d.parentId && <span className="truncate text-[12px] text-muted-foreground">branch of {nameOf(d.parentId) ?? 'another database'}</span>}
                    {d.workflow?.name && <span className="truncate text-[12px] text-muted-foreground">Tables of {d.workflow.name}</span>}
                </span>
            ),
        },
        { id: 'engine', header: 'Engine', width: '6.5rem', cell: (d) => <span className="text-foreground/80">{ENGINE_LABEL[d.engine] ?? d.engine}</span> },
        { id: 'size', header: 'Size', width: '6rem', cell: (d) => <span className="tabular-nums">{formatSize(d.sizeBytes)}</span> },
        { id: 'tables', header: 'Tables', width: '5rem', priority: 2, cell: (d) => <span className="tabular-nums">{formatExact(d.tableCount)}</span> },
        { id: 'used', header: 'Used by', priority: 3, cell: (d) => <UsedByText users={d.usedBy} /> },
        {
            id: 'user',
            header: 'User',
            width: '8rem',
            priority: 2,
            cell: (d) => <span className={d.userId ? 'text-foreground/85' : 'text-muted-foreground'}>{userLabel(d.userId)}</span>,
        },
        { id: 'created', header: 'Created', width: '6.5rem', priority: 3, cell: (d) => <TimeCell value={d.createdAt} /> },
    ];
    return (
        <>
            <PanelToolbar
                user={user}
                setUser={setUser}
                action={<NewInCode kind="database" place={{ user: defaultWriteUser(user) }} />}
            />
            <DataTable
                rowMenu="database"
                label="Databases"
                columns={columns}
                rows={paged.rows}
                getRowId={(d) => d.id}
                loading={paged.loading}
                error={paged.error}
                onRetry={() => void paged.refresh()}
                onRowClick={(d) => setDatabase(d.id, { push: true })}
                selectedId={databaseId}
                nextCursor={paged.nextCursor}
                onLoadMore={() => void paged.loadMore()}
                loadingMore={paged.loadingMore}
                empty={<EmptyCode title="No databases yet." hint="A SQL database for an app or an agent: SQLite by default, Postgres when you outgrow it." snippet={NEW_SNIPPETS.database({ user: defaultWriteUser(user) })} />}
            />
            <DatabaseDrawer
                databaseId={databaseId}
                row={paged.rows.find((d) => d.id === databaseId)}
                rows={paged.rows}
                onOpen={(id) => setDatabase(id, { push: true })}
                onClose={() => setDatabase(null)}
            />
        </>
    );
}
