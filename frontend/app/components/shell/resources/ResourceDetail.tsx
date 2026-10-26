// One resource, in full: where it sits (Resources / its kind), what it is,
// where it came from and what uses it, its facts, and a body that shows the
// thing itself — an automation's tables, a file's preview, a workspace's files;
// for the platform's kinds the registered platform draws it (a repo's files, a
// domain's records). Every kind shares this anatomy; only the body and the
// actions differ.
import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent, type ReactNode } from 'react';
import { useSearchParams } from 'react-router';
import { toast } from 'sonner';
import { AlertCircle, Check, ChevronRight, Clock, Copy, Download, ExternalLink, Folder, Trash2, Upload, XCircle } from 'lucide-react';
import { NodeMark, agentMarkType, compactNumber, countOf, dateLabel, fmtBytes, harnessLabel, relTime } from '~/components/dashboard/primitives';
import type { FileEntry, FileSource } from '~/components/dashboard/types';
import { FilePreviewBody, FilePreviewDialog, fileDownloadHref, type FilePreviewRequest } from '~/components/dashboard/FilePreviewDialog';
import { CopyButton } from '~/components/ui/CopyButton';
import { Skeleton } from '~/components/ui/skeleton';
import { openCreateCredential } from '~/components/shared/popups/CreateCredentialDialog';
import { uploadWorkspaceFiles } from '~/hooks/useAgentWorkspaceFiles';
import type { WorkspaceRef } from '~/hooks/useDashboardOverview';
import { fileKindOf } from '~/lib/embedKind';
import { navigateToWorkflow } from '~/lib/navigation';
import { socketCall } from '~/lib/socketCall';
import { cn } from '~/lib/utils';
import { PhoneBarBack, useInPhoneShell } from '../AppShell';
import { FileThumb, basename, folderListing } from './fileParts';
import { kindDef, type ResourceItem, type FileRef } from './model';
import { usePlatformResources, type Removal } from './platform';
import { ConfirmAction, FolderTrail, InnerBackContext, InnerLevel, RemovalPanel, ResourceUserChip, RowDelete, Section, Surface, WorkflowChip, type InnerStep } from './ui';
import { DatasetRows } from './DatasetRows';
import { BUTTON_PRIMARY, BUTTON_SECONDARY } from '../buttons';
import { PAGE_TITLE } from '~/components/shell/titles';

function Facts({ rows }: { rows: [string, ReactNode][] }) {
    return (
        <dl className="mt-8 grid grid-cols-2 gap-x-8 gap-y-5 border-t border-border pt-6 dark:border-foreground/[0.08] sm:grid-cols-[repeat(auto-fit,minmax(9rem,1fr))]">
            {rows.map(([label, value]) => (
                <div key={label} className="min-w-0">
                    <dt className="text-[12.5px] text-muted-foreground">{label}</dt>
                    <dd className="mt-1 truncate text-[14px] text-foreground">{value}</dd>
                </div>
            ))}
        </dl>
    );
}

function UsedBy({ item }: { item: ResourceItem }) {
    const users = item.users ?? [];
    if (!item.usedBy.length && !users.length) return null;
    return (
        <Section title="Used by" meta={item.usedBy.length + users.length}>
            <div className="flex flex-wrap gap-2">
                {item.usedBy.map((w) => (
                    <WorkflowChip key={w.id} workflow={w} />
                ))}
                {users.map((u) => (
                    <ResourceUserChip key={`${u.kind}:${u.id}:${u.binding ?? ''}`} user={u} />
                ))}
            </div>
        </Section>
    );
}

// ---------------------------------------------------------------------------
// Bodies

type WorkspaceListing = { source: FileSource } | 'loading' | 'failed';

/** One agent workspace volume as a file place: the listing the chat's Files panel shows. */
async function listWorkspace(w: WorkspaceRef): Promise<FileSource | null> {
    const d = await socketCall('agent_workspace:list', { workflow_id: w.workflow.id, node_id: w.agent.nodeId, conversation_key: w.conversationKey }, 20000);
    if (!d?.success) return null;
    const mount = (typeof d.workspace === 'string' && d.workspace) || '/workspace';
    const uploadUrlPath = typeof d.upload_url_path === 'string' ? d.upload_url_path : undefined;
    const mtime = (raw: unknown) =>
        typeof raw === 'number' ? new Date(raw > 1e12 ? raw : raw * 1000).toISOString() : typeof raw === 'string' && raw ? raw : new Date(0).toISOString();
    return {
        id: w.id,
        kind: 'workspace',
        label: `${w.agent.label} · ${w.conversationTitle || w.conversationKey}`,
        sublabel: `Agent workspace · mounted at ${mount}`,
        workflow: w.workflow,
        agent: w.agent,
        conversationTitle: w.conversationTitle,
        conversationKey: w.conversationKey,
        mount,
        uploadUrlPath,
        writable: !!uploadUrlPath,
        truncated: Boolean(d.truncated),
        files: ((d.files as Array<Record<string, unknown>>) ?? [])
            .map((f) => ({
                path: String(f.path ?? ''),
                size: Number(f.size ?? 0),
                mtime: mtime(f.mtime),
                kind: fileKindOf(String(f.path ?? '')),
                urlPath: typeof f.url_path === 'string' ? f.url_path : undefined,
            }))
            .sort((a, b) => b.mtime.localeCompare(a.mtime)),
    };
}

/** An automation's tables: each opens its rows a level down (`?table=` its id), and can be deleted. */
function TablesBody({ tables, now, onChanged }: { tables: FileRef[]; now: string; onChanged: () => void }) {
    const [params, setParams] = useSearchParams();
    const [confirming, setConfirming] = useState<string | null>(null);
    const go = (table: string | null) =>
        setParams((prev) => {
            const next = new URLSearchParams(prev);
            if (table) next.set('table', table);
            else next.delete('table');
            return next;
        });
    const asked = params.get('table');
    const open = asked ? tables.find((t) => t.entry.resourceId === asked) : undefined;
    if (open) {
        return (
            <InnerLevel label="Tables" onBack={() => go(null)} trail={[{ label: 'Tables', onGo: () => go(null) }, { label: open.entry.path }]}>
                <DatasetRows key={asked} table={open} />
            </InnerLevel>
        );
    }
    const remove = async ({ entry }: FileRef) => {
        try {
            await socketCall('resource:delete', { resource_id: entry.resourceId });
            toast.success(`Deleted ${entry.path}`);
            onChanged();
        } catch (err) {
            toast.error(`Delete failed: ${err instanceof Error ? err.message : String(err)}`);
        }
        setConfirming(null);
    };
    return (
        <Section title="Tables" meta={tables.length}>
            {tables.length === 0 ? (
                <p className="text-[13.5px] text-muted-foreground">No tables yet. A table an interface or the automation keeps records in lands here.</p>
            ) : (
                <Surface>
                    {tables.map((table) => (
                        <div key={table.entry.resourceId ?? table.entry.path} className="group flex items-center gap-3 border-b border-border px-4 py-2.5 last:border-0 dark:border-foreground/[0.06]">
                            <button type="button" onClick={() => table.entry.resourceId && go(table.entry.resourceId)} className="flex min-w-0 flex-1 items-center gap-3 text-left">
                                <FileThumb file={table.entry} />
                                <span className="min-w-0 flex-1 truncate text-[14px] text-foreground">{table.entry.path}</span>
                            </button>
                            <span className="shrink-0 text-[12.5px] tabular-nums text-muted-foreground">{countOf(table.entry.rows ?? 0, 'row')}</span>
                            <span className="hidden w-20 shrink-0 text-right text-[12.5px] tabular-nums text-muted-foreground sm:inline">{relTime(table.entry.mtime, now)}</span>
                            {table.entry.resourceId && (
                                <RowDelete
                                    name={table.entry.path}
                                    asking={confirming === table.entry.resourceId}
                                    onAsk={(ask) => setConfirming(ask ? table.entry.resourceId! : null)}
                                    onConfirm={() => void remove(table)}
                                />
                            )}
                        </div>
                    ))}
                </Surface>
            )}
        </Section>
    );
}

function WorkspaceBody({ workspace, now }: { workspace: WorkspaceRef; now: string }) {
    const [listing, setListing] = useState<WorkspaceListing>('loading');
    const [preview, setPreview] = useState<FilePreviewRequest | null>(null);
    const [confirming, setConfirming] = useState<string | null>(null);
    const input = useRef<HTMLInputElement>(null);

    const load = useCallback(async () => {
        try {
            const source = await listWorkspace(workspace);
            setListing(source ? { source } : 'failed');
        } catch {
            setListing('failed');
        }
    }, [workspace]);
    useEffect(() => {
        void load();
    }, [load]);

    const source = typeof listing === 'object' ? listing.source : null;
    // The folder open (`?path=`, ending in /), as a repo's is: Back walks out of it.
    const [params, setParams] = useSearchParams();
    const asked = (params.get('path') ?? '').replace(/^\/+/, '');
    const folder = asked === '' || asked.endsWith('/') ? asked : `${asked}/`;
    const go = (to: string) =>
        setParams((prev) => {
            const next = new URLSearchParams(prev);
            if (to) next.set('path', to);
            else next.delete('path');
            return next;
        });
    const listed = useMemo(() => (source ? folderListing(source.files, folder) : null), [source, folder]);
    const upload = async (e: ChangeEvent<HTMLInputElement>) => {
        const files = Array.from(e.target.files ?? []);
        e.target.value = '';
        if (!source?.uploadUrlPath || !files.length) return;
        const id = toast.loading(`Uploading ${files.length === 1 ? files[0].name : `${files.length} files`}…`);
        try {
            await uploadWorkspaceFiles(source.uploadUrlPath, files, (p) => toast.loading(`Uploading ${p.fileName} · ${Math.round(p.fraction * 100)}%`, { id }));
            toast.success('Uploaded', { id });
            await load();
        } catch (err) {
            toast.error(`Upload failed: ${err instanceof Error ? err.message : String(err)}`, { id });
        }
    };
    const remove = async (file: FileEntry) => {
        try {
            await socketCall('agent_workspace:delete', { workflow_id: workspace.workflow.id, node_id: workspace.agent.nodeId, conversation_key: workspace.conversationKey, path: file.path });
            await load();
        } catch (err) {
            toast.error(`Delete failed: ${err instanceof Error ? err.message : String(err)}`);
        }
        setConfirming(null);
    };

    return (
        <Section
            title="Files"
            meta={source ? source.files.length : undefined}
            action={
                source?.writable ? (
                    <>
                        <button type="button" className={BUTTON_SECONDARY} onClick={() => input.current?.click()}>
                            <Upload className="h-4 w-4" />
                            Upload
                        </button>
                        <input ref={input} type="file" multiple className="hidden" onChange={upload} />
                    </>
                ) : undefined
            }
        >
            <FolderTrail dir={folder} onGo={go} />
            {listing === 'loading' ? (
                <Surface>
                    {[0, 1, 2].map((i) => (
                        <div key={i} className="flex items-center gap-3 border-b border-border px-4 py-3 last:border-0 dark:border-foreground/[0.06]">
                            <Skeleton className="h-8 w-8 rounded-lg" />
                            <Skeleton className="h-3.5 w-1/3" />
                        </div>
                    ))}
                </Surface>
            ) : listing === 'failed' ? (
                <p className="text-[13.5px] text-muted-foreground">This workspace couldn’t be read right now.</p>
            ) : source && source.files.length === 0 ? (
                <p className="text-[13.5px] text-muted-foreground">Nothing saved yet. Files the agent writes under {source.mount ?? '/workspace'} land here, and so does anything you upload.</p>
            ) : listed && !listed.folders.length && !listed.files.length ? (
                <p className="text-[13.5px] text-muted-foreground">
                    Nothing is in {folder} anymore.{' '}
                    <button type="button" onClick={() => go('')} className="font-medium text-foreground underline underline-offset-4">
                        See every file
                    </button>
                </p>
            ) : (
                source &&
                listed && (
                    <Surface>
                        {listed.folders.map((f) => (
                            <button
                                key={f.path}
                                type="button"
                                onClick={() => go(f.path)}
                                className="group flex w-full items-center gap-3 border-b border-border px-4 py-2.5 text-left transition-colors last:border-0 hover:bg-foreground/[0.03] focus-visible:bg-foreground/[0.03] focus-visible:outline-none dark:border-foreground/[0.06]"
                            >
                                <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-foreground/[0.05]">
                                    <Folder className="h-4 w-4 text-foreground/65 dark:text-foreground/50" strokeWidth={1.75} />
                                </span>
                                <span className="min-w-0 flex-1 truncate text-[14px] text-foreground">{f.name}</span>
                                <span className="hidden shrink-0 text-[12.5px] tabular-nums text-muted-foreground sm:inline">{countOf(f.files, 'file')}</span>
                                <span className="hidden w-20 shrink-0 text-right text-[12.5px] tabular-nums text-muted-foreground sm:inline">{relTime(f.mtime, now)}</span>
                                <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground/60 transition-transform duration-200 group-hover:translate-x-0.5 group-hover:text-muted-foreground" />
                            </button>
                        ))}
                        {listed.files.map((file) => (
                            <div key={file.path} className="group flex items-center gap-3 border-b border-border px-4 py-2.5 last:border-0 dark:border-foreground/[0.06]">
                                <button type="button" onClick={() => setPreview({ file, source })} className="flex min-w-0 flex-1 items-center gap-3 text-left">
                                    <FileThumb file={file} />
                                    <span className="min-w-0 flex-1 truncate text-[14px] text-foreground">{basename(file.path)}</span>
                                </button>
                                <span className="hidden shrink-0 text-[12.5px] tabular-nums text-muted-foreground sm:inline">{fmtBytes(file.size)}</span>
                                <span className="hidden w-20 shrink-0 text-right text-[12.5px] tabular-nums text-muted-foreground sm:inline">{relTime(file.mtime, now)}</span>
                                {source.writable && (
                                    <RowDelete
                                        name={basename(file.path)}
                                        asking={confirming === file.path}
                                        onAsk={(ask) => setConfirming(ask ? file.path : null)}
                                        onConfirm={() => void remove(file)}
                                    />
                                )}
                            </div>
                        ))}
                    </Surface>
                )
            )}
            {source?.truncated && <p className="mt-3 text-[12.5px] text-muted-foreground">The workspace holds more files than this lists: the newest are shown.</p>}
            <FilePreviewDialog request={preview} onClose={() => setPreview(null)} />
        </Section>
    );
}

const RECORD_COLUMNS = 'grid grid-cols-[52px_minmax(0,1fr)_84px] gap-3 sm:grid-cols-[72px_minmax(0,1fr)_minmax(0,2fr)_96px] sm:gap-4';

export interface DnsRecordRow {
    type: string;
    name: string;
    value: string;
    /** `found` once public DNS answers with it, `waiting` until then, `conflict` when another record is in the way. */
    status: 'found' | 'waiting' | 'conflict';
}

const RECORD_STATUS = {
    found: { label: 'Found', Icon: Check, tone: 'text-foreground/80' },
    waiting: { label: 'Waiting', Icon: Clock, tone: 'text-muted-foreground' },
    conflict: { label: 'Conflict', Icon: XCircle, tone: 'text-red-600 dark:text-red-400' },
} as const;

/** A domain's DNS records: each value copyable, each with whether public DNS has it yet. */
export function DnsRecords({ records, title = 'DNS records', className }: { records: DnsRecordRow[]; title?: string; className?: string }) {
    return (
        <Section title={title} className={className}>
            <Surface>
                <div className={cn(RECORD_COLUMNS, 'hidden border-b border-border px-4 py-2.5 text-[12.5px] text-muted-foreground dark:border-foreground/[0.06] sm:grid')}>
                    <span>Type</span>
                    <span>Name</span>
                    <span>Value</span>
                    <span className="text-right">Status</span>
                </div>
                {records.map((r) => {
                    const { label, Icon, tone } = RECORD_STATUS[r.status];
                    return (
                        <div key={`${r.type}:${r.name}:${r.value}`} className={cn(RECORD_COLUMNS, 'items-center border-b border-border px-4 py-3 text-[13.5px] last:border-0 dark:border-foreground/[0.06]')}>
                            <span className="font-mono text-[12.5px] text-foreground">{r.type}</span>
                            {/* One cell on a phone (name over value), two from sm up. */}
                            <div className="flex min-w-0 flex-col gap-0.5 sm:contents">
                                <span className="flex min-w-0 items-center gap-1">
                                    <span className="truncate font-mono text-[12.5px] text-foreground">{r.name}</span>
                                    <CopyButton value={r.name} className="-my-1 [&_svg]:h-3.5 [&_svg]:w-3.5" />
                                </span>
                                <span className="flex min-w-0 items-center gap-1">
                                    <span className="truncate font-mono text-[12.5px] text-muted-foreground">{r.value}</span>
                                    <CopyButton value={r.value} className="-my-1 [&_svg]:h-3.5 [&_svg]:w-3.5" />
                                </span>
                            </div>
                            <span className={cn('flex items-center justify-end gap-1 text-[12.5px]', tone)}>
                                <Icon className="h-3.5 w-3.5" />
                                {label}
                            </span>
                        </div>
                    );
                })}
            </Surface>
        </Section>
    );
}

/** Copies a live address, saying so for a moment. */
function CopyLink({ url }: { url: string }) {
    const [copied, setCopied] = useState(false);
    return (
        <button
            type="button"
            className={BUTTON_SECONDARY}
            onClick={() =>
                navigator.clipboard?.writeText(url).then(() => {
                    setCopied(true);
                    setTimeout(() => setCopied(false), 1500);
                })
            }
        >
            {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
            {copied ? 'Copied' : 'Copy link'}
        </button>
    );
}

// ---------------------------------------------------------------------------
// The page

export function ResourceDetail({
    item,
    now,
    cost,
    onBack,
    onChanged,
}: {
    item: ResourceItem;
    now: string;
    /** What it costs, in words ("$3.75 a month", "Included"); absent where nothing is billed at all. */
    cost?: string;
    /** `null` goes to Resources, a kind to that kind's list. */
    onBack: (to: 'all' | 'kind') => void;
    /** After a delete or unpublish: refresh the lists and leave the page. */
    onChanged: () => void;
}) {
    const kind = kindDef(item.kind);
    const Icon = kind.icon;
    const file = item.file;
    const inPhone = useInPhoneShell();
    const platform = usePlatformResources();
    const [inner, setInner] = useState<InnerStep | null>(null);
    // Taken when asked, so its preview is read once.
    const [removing, setRemoving] = useState<Removal | null>(null);
    useEffect(() => setRemoving(null), [item.id]);
    const removed =({ done, gone }: { done: string; gone: boolean }) => {
        toast.success(done);
        setRemoving(null);
        if (gone) onChanged();
    };

    const removeResource = async () => {
        if (!file?.entry.resourceId) return;
        try {
            await socketCall('resource:delete', { resource_id: file.entry.resourceId });
            toast.success(`Deleted ${item.title}`);
            onChanged();
        } catch (err) {
            toast.error(`Delete failed: ${err instanceof Error ? err.message : String(err)}`);
        }
    };
    const unpublish = async () => {
        try {
            await socketCall('publish:unpublish', { project_id: item.id });
            toast.success(`Unpublished ${item.title}`);
            onChanged();
        } catch (err) {
            toast.error(`Unpublish failed: ${err instanceof Error ? err.message : String(err)}`);
        }
    };

    let facts: [string, ReactNode][] = [];
    let actions: ReactNode = null;
    let body: ReactNode = null;

    if (item.credential) {
        const c = item.credential;
        facts = [
            ['Status', item.attention ? <span className="text-red-600 dark:text-red-400">Not reachable</span> : 'Working'],
            ['Added', dateLabel(c.createdAt)],
            ['Used by', `${c.usedBy.length} ${c.usedBy.length === 1 ? 'automation' : 'automations'}`],
            ['Owner', c.access === 'owner' ? 'You' : 'Shared with you'],
        ];
        actions = (
            <button type="button" className={BUTTON_SECONDARY} onClick={() => openCreateCredential({ credentialType: c.credentialType, credentialId: c.id })}>
                Manage
            </button>
        );
    } else if (file) {
        const href = fileDownloadHref(file.entry, file.source);
        facts = [
            ['Size', fmtBytes(file.entry.size)],
            ['Type', file.entry.mime ?? file.entry.kind],
            ['Updated', relTime(file.entry.mtime, now)],
            ['Automation', file.source.workflow?.name ?? '—'],
        ];
        actions = (
            <>
                {href && (
                    <a href={href} download target="_blank" rel="noreferrer" className={BUTTON_SECONDARY}>
                        <Download className="h-4 w-4" />
                        Download
                    </a>
                )}
                {file.entry.resourceId && <ConfirmAction label="Delete" confirm="Delete file" onConfirm={removeResource} />}
            </>
        );
        body = (
            <Section title="Preview">
                <Surface className="p-4">
                    <FilePreviewBody file={file.entry} source={file.source} />
                </Surface>
            </Section>
        );
    } else if (item.workspace) {
        const w = item.workspace;
        facts = [
            ['Agent', w.agent.label],
            ['Runs on', harnessLabel(w.agent.model)],
            ['Conversation', w.conversationTitle || w.conversationKey],
            ['Last active', w.lastActivity ? relTime(w.lastActivity, now) : '—'],
        ];
        body = <WorkspaceBody workspace={w} now={now} />;
    } else if (item.platform) {
        const p = item.platform;
        const removal = platform?.removal(item) ?? null;
        facts = p.facts;
        actions = (
            <>
                {p.unpublish && <ConfirmAction label="Unpublish" confirm="Take it down" icon={Trash2} onConfirm={unpublish} />}
                {removal && !removing && (
                    <button type="button" className={cn(BUTTON_SECONDARY, 'hover:text-red-600 dark:hover:text-red-400')} onClick={() => setRemoving(removal)}>
                        <Trash2 className="h-4 w-4" />
                        {removal.label}
                    </button>
                )}
                {p.url && <CopyLink url={p.url} />}
                {p.url && (
                    <a href={p.url} target="_blank" rel="noopener noreferrer" className={BUTTON_PRIMARY}>
                        Open
                        <ExternalLink className="h-3.5 w-3.5" />
                    </a>
                )}
            </>
        );
        if (platform) body = <platform.Body item={item} now={now} />;
    } else if (item.tables) {
        const rows = item.tables.reduce((sum, t) => sum + (t.entry.rows ?? 0), 0);
        facts = [
            ['Tables', String(item.tables.length)],
            ['Rows', compactNumber(rows)],
            ['Updated', item.updatedAt ? relTime(item.updatedAt, now) : '—'],
        ];
    }
    // An automation's tables, in place of a database's schema.
    if (item.tables) body = <TablesBody tables={item.tables} now={now} onChanged={onChanged} />;

    const lead = item.file && item.kind === 'files' ? (
        <FileThumb file={item.file.entry} size={48} />
    ) : item.workspace ? (
        <span className="grid h-12 w-12 shrink-0 place-items-center rounded-xl bg-foreground/[0.05] ring-1 ring-inset ring-foreground/[0.06]">
            <NodeMark type={agentMarkType(item.workspace.agent.model)} size="md" />
        </span>
    ) : (
        <span className="grid h-12 w-12 shrink-0 place-items-center rounded-xl bg-foreground/[0.05] ring-1 ring-inset ring-foreground/[0.06]">
            <Icon className="h-5 w-5 text-foreground/80" strokeWidth={1.75} />
        </span>
    );

    return (
        <div className="h-full overflow-y-auto scrollbar-subtle" data-testid="resource-detail">
            <div className={cn('mx-auto w-full px-5 pb-24 pt-4 sm:px-8 sm:pt-8', item.kind === 'repos' || item.kind === 'databases' ? 'max-w-[1200px]' : 'max-w-[960px]')}>
                {inPhone ? (
                    <PhoneBarBack label={inner?.label ?? kind.label} onBack={inner?.onBack ?? (() => onBack('kind'))} />
                ) : (
                    <nav aria-label="Breadcrumb" className="mb-6 flex items-center gap-1 text-[13px] text-muted-foreground">
                        <button type="button" onClick={() => onBack('all')} className="rounded-md px-1 py-0.5 transition-colors hover:text-foreground">
                            Resources
                        </button>
                        <ChevronRight className="h-3.5 w-3.5 opacity-60" />
                        <button type="button" onClick={() => onBack('kind')} className="rounded-md px-1 py-0.5 transition-colors hover:text-foreground">
                            {kind.label}
                        </button>
                    </nav>
                )}

                <header className="flex flex-wrap items-start gap-4">
                    {lead}
                    <div className="min-w-0 flex-1">
                        <h1 className={cn('min-w-0 break-words sm:truncate', PAGE_TITLE)}>{item.title}</h1>
                        <p className="mt-1 text-[14px] leading-snug text-muted-foreground sm:truncate">{item.subtitle}</p>
                        {item.origin && (
                            <p className="mt-1 text-[13px] text-muted-foreground">
                                Built in the{' '}
                                <button
                                    type="button"
                                    onClick={() => navigateToWorkflow({ id: item.origin!.id, name: item.origin!.name })}
                                    className="text-foreground underline-offset-4 hover:underline"
                                >
                                    {item.origin.name}
                                </button>{' '}
                                automation
                            </p>
                        )}
                        {item.owner && <p className="mt-1 text-[13px] text-muted-foreground">For {item.owner.name}, one of your users</p>}
                    </div>
                    {actions && <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto">{actions}</div>}
                </header>
                {removing && <RemovalPanel removal={removing} onCancel={() => setRemoving(null)} onDone={removed} />}

                {item.attention && (
                    <div className="mt-6 flex items-start gap-2.5 rounded-xl border border-red-500/20 bg-red-500/[0.04] px-4 py-3 text-[13.5px] text-foreground">
                        <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-red-600 dark:text-red-400" />
                        {item.attention}
                    </div>
                )}
                {item.pending && (
                    <div className="mt-6 flex items-start gap-2.5 rounded-xl border border-border bg-foreground/[0.03] px-4 py-3 text-[13.5px] text-foreground dark:border-foreground/[0.08]">
                        <Clock className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
                        {item.pending}
                    </div>
                )}

                {(facts.length > 0 || cost) && <Facts rows={cost ? [...facts, ['Cost', cost]] : facts} />}
                <UsedBy item={item} />
                <InnerBackContext.Provider value={setInner}>{body}</InnerBackContext.Provider>
            </div>
        </div>
    );
}
