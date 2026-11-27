// Storage: buckets of files by key. The drawer (`?bucket=`, the folder in `&prefix=`)
// browses the files a level at a time and copies a signed link to one, switches the
// bucket public or private, exports, and deletes. S3 keys and new-file notifications are
// designed, not built yet: they show only in the lab.
import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router';
import { ChevronRight, FileText, Folder, Link2 } from 'lucide-react';
import { toast } from 'sonner';
import { HAIRLINE } from '@/ui/primitives';
import { cn } from '@/ui/utils';
import { Bucket, type BucketObject, type S3Credentials } from 'noclick';
import { NEW_SNIPPETS } from '@/screens/console/lib/snippets';
import { defaultWriteUser, userLabel } from '@/screens/console/lib/userFilter';
import { useConsole } from '@/screens/console/hooks/useConsole';
import { usePaged } from '@/sdk/usePaged';
import { useSearchParam } from '@/screens/console/hooks/useQueryState';
import { recordRecent } from '@/screens/console/hooks/useRecent';
import { invalidateV1, useV1 } from '@/sdk/useV1';
import { NewInCode } from '../../NewInCode';
import { ConsoleButton } from '../../ui/Button';
import { CodeSnippet } from '../../ui/CodeSnippet';
import { ConsoleDialog } from '../../ui/ConsoleDialog';
import { CopyButton } from '../../ui/CopyButton';
import { DataTable, type Column } from '../../ui/DataTable';
import { Drawer } from '../../ui/Drawer';
import { EmptyCode } from '../../ui/EmptyCode';
import { ErrorPanel } from '../../ui/ErrorPanel';
import { RevealOnceSecret } from '../../ui/RevealOnceSecret';
import { Segmented } from '../../ui/Segmented';
import { TimeCell } from '../../ui/TimeCell';
import { errorText, Field, INPUT, LabeledInput, PanelToolbar, Section, type PanelProps } from './shared';
import { DeleteByName, ExportSection, formatExact, formatSize, UsedByText } from './StorageShared';

/** How long a copied signed link works. */
const LINK_TTL_S = 3600;
const PAGE = 50;

const LIFETIMES = [
    { value: '900', label: '15 minutes' },
    { value: '3600', label: '1 hour' },
    { value: '43200', label: '12 hours' },
] as const;

/** `invoices/2026-09/` → `["invoices/", "invoices/2026-09/"]`: the prefixes a breadcrumb walks. */
export function prefixTrail(prefix: string): string[] {
    const parts = prefix.split('/').filter(Boolean);
    return parts.map((_, i) => `${parts.slice(0, i + 1).join('/')}/`);
}

/** The last segment of a key or folder: `invoices/2026-09/0042.pdf` → `0042.pdf`, a folder keeps its `/`. */
export function baseName(key: string): string {
    const trimmed = key.endsWith('/') ? key.slice(0, -1) : key;
    return trimmed.slice(trimmed.lastIndexOf('/') + 1) + (key.endsWith('/') ? '/' : '');
}

function Breadcrumbs({ bucket, prefix, onPrefix }: { bucket: Bucket; prefix: string; onPrefix: (prefix: string) => void }) {
    const trail = prefixTrail(prefix);
    const crumb = 'rounded px-1 py-0.5 font-mono text-[12px] text-muted-foreground transition-colors hover:bg-foreground/[0.05] hover:text-foreground';
    return (
        <nav aria-label="Folder" className="mb-2 flex min-w-0 flex-wrap items-center gap-0.5">
            {prefix ? (
                <button type="button" className={crumb} onClick={() => onPrefix('')}>
                    {bucket.name}
                </button>
            ) : (
                <span aria-current="page" className="px-1 py-0.5 font-mono text-[12px] text-foreground">
                    {bucket.name}
                </span>
            )}
            {trail.map((p, i) => (
                <span key={p} className="inline-flex items-center gap-0.5">
                    <ChevronRight aria-hidden className="h-3 w-3 text-muted-foreground" />
                    {i === trail.length - 1 ? (
                        <span aria-current="page" className="px-1 py-0.5 font-mono text-[12px] text-foreground">
                            {baseName(p).slice(0, -1)}
                        </span>
                    ) : (
                        <button type="button" className={crumb} onClick={() => onPrefix(p)}>
                            {baseName(p).slice(0, -1)}
                        </button>
                    )}
                </span>
            ))}
        </nav>
    );
}

function CopyLink({ bucket, entry }: { bucket: Bucket; entry: BucketObject }) {
    const [busy, setBusy] = useState(false);
    const name = baseName(entry.key);
    const copy = async () => {
        setBusy(true);
        try {
            const link = bucket.public ? await bucket.url(entry.key) : await bucket.signedUrl(entry.key, { expiresIn: LINK_TTL_S });
            await navigator.clipboard.writeText(link);
            toast(bucket.public ? `Copied the URL of ${name}` : `Copied a signed link to ${name}`, { description: bucket.public ? 'It works for as long as the bucket stays public.' : 'Anyone with it can download the file for the next hour.' });
        } catch (e) {
            toast.error(errorText(e));
        } finally {
            setBusy(false);
        }
    };
    const label = bucket.public ? 'Copy URL' : 'Copy signed link';
    return (
        <ConsoleButton variant="ghost" size="sm" disabled={busy} onClick={() => void copy()} aria-label={`${label}: ${name}`} title={label} icon={<Link2 className="h-3.5 w-3.5" />}>
            <span className="hidden sm:inline">{label}</span>
        </ConsoleButton>
    );
}

function FilesSection({ bucket, prefix, onPrefix }: { bucket: Bucket; prefix: string; onPrefix: (prefix: string) => void }) {
    const paged = usePaged(`buckets/${bucket.id}/objects?${prefix}`, (cursor) => bucket.objectsPage({ prefix: prefix || undefined, delimiter: '/', cursor, limit: PAGE }), (o) => o.key);
    return (
        <Section title="Files">
            <Breadcrumbs bucket={bucket} prefix={prefix} onPrefix={onPrefix} />
            {paged.error !== undefined && !paged.rows.length ? (
                <ErrorPanel error={paged.error} onRetry={() => void paged.refresh()} />
            ) : paged.loading ? (
                <div aria-busy className="h-32 animate-pulse rounded-lg bg-foreground/[0.04]" />
            ) : paged.rows.length ? (
                <div className={cn('rounded-lg border', HAIRLINE)}>
                    <ul aria-label={`Files in ${prefix || bucket.name}`} className={'m-0 list-none p-0'}>
                        {paged.rows.map((o) =>
                            o.isFolder ? (
                                <li key={o.key}>
                                    <button type="button" onClick={() => onPrefix(o.key)} className="flex h-10 w-full items-center gap-2.5 px-3 text-left text-[13px] transition-colors hover:bg-foreground/[0.03]">
                                        <Folder aria-hidden className="h-4 w-4 shrink-0 text-muted-foreground" />
                                        <span className="min-w-0 flex-1 truncate font-mono text-[13px] text-foreground">{baseName(o.key)}</span>
                                        <ChevronRight aria-hidden className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                                    </button>
                                </li>
                            ) : (
                                <li key={o.key} className="group flex h-10 items-center gap-2.5 pl-3 pr-1.5 text-[13px]">
                                    <FileText aria-hidden className="h-4 w-4 shrink-0 text-muted-foreground" />
                                    <span className="min-w-0 flex-1 truncate font-mono text-[13px] text-foreground" title={o.key}>
                                        {baseName(o.key)}
                                    </span>
                                    <span className="hidden w-32 shrink-0 truncate text-[12px] text-muted-foreground md:block">{o.contentType}</span>
                                    <span className="w-16 shrink-0 text-right text-[12px] tabular-nums text-muted-foreground">{formatSize(o.size)}</span>
                                    <span className="hidden w-20 shrink-0 text-right text-[12px] text-muted-foreground sm:block">
                                        <TimeCell value={o.updatedAt} />
                                    </span>
                                    <span className="shrink-0 transition-opacity md:opacity-0 md:focus-within:opacity-100 md:group-hover:opacity-100">
                                        <CopyLink bucket={bucket} entry={o} />
                                    </span>
                                </li>
                            )
                        )}
                    </ul>
                    {paged.loadMoreError !== undefined && <ErrorPanel error={paged.loadMoreError} onRetry={() => void paged.loadMore()} className={cn('rounded-none border-0 border-t', HAIRLINE)} />}
                    {paged.nextCursor && paged.loadMoreError === undefined && (
                        <div className={cn('flex justify-center border-t py-1.5', HAIRLINE)}>
                            <ConsoleButton variant="ghost" size="sm" onClick={() => void paged.loadMore()} disabled={paged.loadingMore}>
                                {paged.loadingMore ? 'Loading…' : 'Load more'}
                            </ConsoleButton>
                        </div>
                    )}
                </div>
            ) : (
                <p className="m-0 text-[13px] text-muted-foreground">{prefix ? `Nothing under ${prefix}.` : 'No files yet. Your code stores them with bucket.put, or a browser uploads through a PUT signed link.'}</p>
            )}
        </Section>
    );
}

function AccessSection({ bucket, onChanged }: { bucket: Bucket; onChanged: (bucket: Bucket) => void }) {
    const { lab } = useConsole();
    const [asking, setAsking] = useState<'public' | 'private' | null>(null);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>(undefined);
    const [keysOpen, setKeysOpen] = useState(false);
    const [creds, setCreds] = useState<S3Credentials | null>(null);
    const change = async (to: 'public' | 'private') => {
        setBusy(true);
        setError(undefined);
        try {
            onChanged(await bucket.update({ public: to === 'public' }));
            invalidateV1('buckets');
            setAsking(null);
            toast(to === 'public' ? `${bucket.name} is public` : `${bucket.name} is private`);
        } catch (e) {
            setError(e);
        } finally {
            setBusy(false);
        }
    };
    return (
        <Section title="Access">
            <div className="flex flex-col gap-3">
                <div className="flex flex-wrap items-center gap-3">
                    <Segmented
                        label="Access"
                        value={bucket.public ? 'public' : 'private'}
                        onChange={(v) => {
                            if (v !== (bucket.public ? 'public' : 'private')) {
                                setError(undefined);
                                setAsking(v);
                            }
                        }}
                        options={[
                            { value: 'private', label: 'Private' },
                            { value: 'public', label: 'Public' },
                        ]}
                    />
                    <p className="m-0 min-w-0 flex-1 text-[12px] text-muted-foreground">
                        {bucket.public ? 'Every file is readable at a plain URL.' : lab ? 'Files are reached with your key, a signed link, or S3 keys.' : 'Files are reached with your key or a signed link.'}
                    </p>
                </div>
                {bucket.public && bucket.publicBaseUrl && (
                    <div className={cn('flex min-w-0 items-center gap-1 rounded-md border bg-foreground/[0.03] py-1 pl-3 pr-1', HAIRLINE)}>
                        <span className="min-w-0 flex-1 truncate font-mono text-[12px]">{bucket.publicBaseUrl}/</span>
                        <CopyButton value={`${bucket.publicBaseUrl}/`} label="Copy the public URL" />
                    </div>
                )}
                {lab && (
                    <div className="flex flex-wrap items-center gap-3">
                        <p className="m-0 min-w-0 flex-1 text-[13px] text-muted-foreground">Short-lived keys for rclone, the AWS CLI or an S3 library, for this bucket only.</p>
                        <ConsoleButton size="sm" onClick={() => setKeysOpen(true)}>
                            S3 access
                        </ConsoleButton>
                    </div>
                )}
            </div>
            <ConsoleDialog
                open={asking !== null}
                onOpenChange={(o) => !o && setAsking(null)}
                size="sm"
                title={asking === 'public' ? `Make ${bucket.name} public?` : `Make ${bucket.name} private?`}
                description={
                    asking === 'public'
                        ? `Every file in it, now and later, becomes readable by anyone who has its URL. It holds ${formatExact(bucket.objectCount)} files.`
                        : 'Every public URL stops working at once. Signed links keep working until they expire.'
                }
                footer={
                    <>
                        <ConsoleButton variant="ghost" onClick={() => setAsking(null)}>
                            Cancel
                        </ConsoleButton>
                        <ConsoleButton variant={asking === 'public' ? 'danger' : 'primary'} disabled={busy} onClick={() => void change(asking!)}>
                            {busy ? 'Saving…' : asking === 'public' ? 'Make public' : 'Make private'}
                        </ConsoleButton>
                    </>
                }
            >
                {error !== undefined && <ErrorPanel error={error} />}
            </ConsoleDialog>
            <S3AccessDialog bucket={bucket} open={keysOpen} onOpenChange={setKeysOpen} onCreated={setCreds} />
            <RevealOnceSecret
                secret={creds?.secretAccessKey ?? null}
                title={`S3 keys for ${bucket.name}`}
                description={creds ? `The secret is shown once. ${creds.readOnly ? 'Read-only keys; they' : 'They'} stop working ${creds.expiresAt ? creds.expiresAt.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : 'when they expire'}.` : undefined}
                onDone={() => setCreds(null)}
            >
                {() => (creds ? <CredentialsView creds={creds} /> : null)}
            </RevealOnceSecret>
        </Section>
    );
}

function CredentialsView({ creds }: { creds: S3Credentials }) {
    const rows: [string, string][] = [
        ['Endpoint', creds.endpoint],
        ['Bucket', creds.bucket],
        ['Region', creds.region],
        ['Access key ID', creds.accessKeyId],
        ['Secret access key', creds.secretAccessKey],
        ...(creds.sessionToken ? ([['Session token', creds.sessionToken]] as [string, string][]) : []),
    ];
    const env = [
        `AWS_ENDPOINT_URL=${creds.endpoint}`,
        `AWS_REGION=${creds.region}`,
        `AWS_ACCESS_KEY_ID=${creds.accessKeyId}`,
        `AWS_SECRET_ACCESS_KEY=${creds.secretAccessKey}`,
        ...(creds.sessionToken ? [`AWS_SESSION_TOKEN=${creds.sessionToken}`] : []),
    ].join('\n');
    return (
        <div className="flex flex-col gap-3">
            <dl className="m-0">
                {rows.map(([label, value]) => (
                    <Field key={label} label={label}>
                        <span className="flex min-w-0 items-center gap-1">
                            <span className="min-w-0 flex-1 truncate font-mono text-[12px]" title={value}>
                                {value}
                            </span>
                            <CopyButton value={value} label={`Copy ${label.toLowerCase()}`} />
                        </span>
                    </Field>
                ))}
            </dl>
            <div className="flex flex-col gap-1.5">
                <span className="text-[12px] text-muted-foreground">As environment variables, for the AWS CLI and most S3 libraries (use the bucket name above):</span>
                <CodeSnippet code={env} language="bash" />
            </div>
        </div>
    );
}

function S3AccessDialog({ bucket, open, onOpenChange, onCreated }: { bucket: Bucket; open: boolean; onOpenChange: (open: boolean) => void; onCreated: (creds: S3Credentials) => void }) {
    const [readOnly, setReadOnly] = useState(true);
    const [ttl, setTtl] = useState('3600');
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>(undefined);
    const create = async () => {
        setBusy(true);
        setError(undefined);
        try {
            const creds = await bucket.s3Credentials({ readOnly, ttlS: Number(ttl) });
            onOpenChange(false);
            onCreated(creds);
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
            title={`S3 access to ${bucket.name}`}
            description="Keys for the bucket's S3-compatible endpoint. They reach this bucket only, and the secret is shown once."
            footer={
                <ConsoleButton variant="primary" disabled={busy} onClick={() => void create()}>
                    {busy ? 'Creating…' : 'Create keys'}
                </ConsoleButton>
            }
        >
            <div className="flex flex-col gap-3">
                <label className="flex items-start gap-2 text-[13px]">
                    <input type="checkbox" className="mt-0.5" checked={readOnly} onChange={(e) => setReadOnly(e.target.checked)} />
                    <span>
                        Read-only
                        <span className="block text-[12px] text-muted-foreground">Keys that can list and download, but not upload or delete.</span>
                    </span>
                </label>
                <LabeledInput label="Valid for" id="s3-ttl">
                    <select id="s3-ttl" className={INPUT} value={ttl} onChange={(e) => setTtl(e.target.value)}>
                        {LIFETIMES.map((l) => (
                            <option key={l.value} value={l.value}>
                                {l.label}
                            </option>
                        ))}
                    </select>
                </LabeledInput>
                {error !== undefined && <ErrorPanel error={error} />}
            </div>
        </ConsoleDialog>
    );
}

function BucketDrawer({ bucketId, row, onClose }: { bucketId: string | null; row?: Bucket; onClose: () => void }) {
    const { client, lab } = useConsole();
    const [prefix, setPrefix] = useSearchParam('prefix');
    const fetched = useV1(bucketId && !row ? `buckets/${bucketId}` : null, () => Bucket.get(bucketId!, { client }));
    const [updated, setUpdated] = useState<Bucket | null>(null);
    const bucket = (updated && updated.id === bucketId ? updated : null) ?? row ?? fetched.data;
    useEffect(() => {
        if (bucket) recordRecent({ type: 'bucket', id: bucket.id, label: bucket.name, path: 'resources/storage', params: { bucket: bucket.id } });
    }, [bucket?.id]); // eslint-disable-line react-hooks/exhaustive-deps
    const files = bucket?.objectCount ?? 0;
    return (
        <Drawer
            open={bucketId !== null}
            onOpenChange={(o) => !o && onClose()}
            kind="bucket"
            title={bucket?.name}
            id={bucketId ?? undefined}
            footer={
                bucket ? (
                    <DeleteByName
                        label="Delete bucket"
                        name={bucket.name}
                        description={
                            bucket.usedBy.length
                                ? `${bucket.usedBy.map((u) => u.name).join(', ')} ${bucket.usedBy.some((u) => u.binding) ? 'binds' : 'has'} it${bucket.usedBy.some((u) => u.binding) ? '' : ' in its tools'}, so the delete is refused until that changes.`
                                : files > 0
                                  ? `It holds ${formatExact(files)} files (${formatSize(bucket.sizeBytes)}), which are deleted with it. This can't be undone.`
                                  : "It's empty; its name becomes free to use again."
                        }
                        onConfirm={async () => {
                            await bucket.delete({ force: files > 0 });
                            invalidateV1('buckets');
                            invalidateV1('account');
                            toast(`Deleted ${bucket.name}`);
                            onClose();
                        }}
                    />
                ) : undefined
            }
        >
            {!bucket && fetched.error !== undefined && <ErrorPanel error={fetched.error} onRetry={() => void fetched.refresh()} />}
            {!bucket && fetched.error === undefined && <div aria-busy className="h-40 animate-pulse rounded-lg bg-foreground/[0.04]" />}
            {bucket && (
                <div key={bucket.id} className="flex flex-col gap-6">
                    <dl className="m-0">
                        <Field label="Access">{bucket.public ? 'Public' : 'Private'}</Field>
                        <Field label="Size">
                            <span className="tabular-nums">{formatSize(bucket.sizeBytes)}</span>
                        </Field>
                        <Field label="Files">
                            <span className="tabular-nums">{formatExact(bucket.objectCount)}</span>
                        </Field>
                        <Field label="Used by">
                            <UsedByText users={bucket.usedBy} />
                        </Field>
                        <Field label="Region">{bucket.region ?? '—'}</Field>
                        {lab && <Field label="New files">
                            {bucket.notifications.length ? (
                                <span className="flex flex-col">
                                    {bucket.notifications.map((n) => (
                                        <span key={`${n.queue}:${n.prefix ?? ''}`}>
                                            Put on queue <span className="font-mono text-[12px]">{n.queue}</span>
                                            {n.prefix && (
                                                <span className="text-muted-foreground">
                                                    {' '}
                                                    when under <span className="font-mono text-[12px]">{n.prefix}</span>
                                                </span>
                                            )}
                                        </span>
                                    ))}
                                </span>
                            ) : (
                                <span className="text-muted-foreground">Tell nobody</span>
                            )}
                        </Field>}
                        <Field label="User">{userLabel(bucket.userId)}</Field>
                        <Field label="Created">
                            <TimeCell value={bucket.createdAt} tier="absolute" />
                        </Field>
                    </dl>
                    <FilesSection bucket={bucket} prefix={prefix ?? ''} onPrefix={(p) => setPrefix(p || null)} />
                    <AccessSection bucket={bucket} onChanged={setUpdated} />
                    <ExportSection what="Every file at its key, with an index of each one's type and metadata, at a link valid 7 days." start={() => bucket.export()} />
                </div>
            )}
        </Drawer>
    );
}

export function StoragePanel({ user, setUser }: PanelProps) {
    const { client } = useConsole();
    const [bucketId, setBucket] = useSearchParam('bucket');
    const [, setParams] = useSearchParams();
    const paged = usePaged(`buckets?${user}`, (cursor) => Bucket.listPage({ client, userFilter: user, cursor, limit: 50 }), (b) => b.id);
    const columns: Column<Bucket>[] = [
        { id: 'name', header: 'Name', cell: (b) => <span className="truncate font-medium text-foreground">{b.name}</span> },
        { id: 'access', header: 'Access', width: '6rem', cell: (b) => <span className={b.public ? 'text-foreground' : 'text-muted-foreground'}>{b.public ? 'Public' : 'Private'}</span> },
        { id: 'size', header: 'Size', width: '6rem', cell: (b) => <span className="tabular-nums">{formatSize(b.sizeBytes)}</span> },
        { id: 'files', header: 'Files', width: '6rem', priority: 2, cell: (b) => <span className="tabular-nums">{formatExact(b.objectCount)}</span> },
        { id: 'used', header: 'Used by', priority: 3, cell: (b) => <UsedByText users={b.usedBy} /> },
        {
            id: 'user',
            header: 'User',
            width: '8rem',
            priority: 2,
            cell: (b) => <span className={b.userId ? 'text-foreground/85' : 'text-muted-foreground'}>{userLabel(b.userId)}</span>,
        },
        { id: 'created', header: 'Created', width: '6.5rem', priority: 3, cell: (b) => <TimeCell value={b.createdAt} /> },
    ];
    return (
        <>
            <PanelToolbar
                user={user}
                setUser={setUser}
                action={<NewInCode kind="bucket" place={{ user: defaultWriteUser(user) }} />}
            />
            <DataTable
                rowMenu="bucket"
                label="Buckets"
                columns={columns}
                rows={paged.rows}
                getRowId={(b) => b.id}
                loading={paged.loading}
                error={paged.error}
                onRetry={() => void paged.refresh()}
                onRowClick={(b) => setBucket(b.id, { push: true })}
                selectedId={bucketId}
                nextCursor={paged.nextCursor}
                onLoadMore={() => void paged.loadMore()}
                loadingMore={paged.loadingMore}
                empty={<EmptyCode title="No buckets yet." hint="Files by key, private by default, with signed links." snippet={NEW_SNIPPETS.bucket({ user: defaultWriteUser(user) })} />}
            />
            <BucketDrawer
                bucketId={bucketId}
                row={paged.rows.find((b) => b.id === bucketId)}
                onClose={() =>
                    setParams(
                        (prev) => {
                            const out = new URLSearchParams(prev);
                            out.delete('bucket');
                            out.delete('prefix');
                            return out;
                        },
                        { replace: true, preventScrollReset: true }
                    )
                }
            />
        </>
    );
}
