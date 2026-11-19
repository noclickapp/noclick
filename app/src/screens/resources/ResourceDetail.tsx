// One resource, in full: where it sits (Resources / its kind), what it is, where it came from and what uses it, its
// facts, and a body that shows the thing itself: an automation's tables, a file's preview; for the platform's kinds
// the reads around the page draw it (a repo's files, a domain's records), and a host draws what it added. Every kind
// shares this anatomy; only the body and the actions differ.
import { useState, type ReactNode } from 'react';
import { useSearchParams } from 'react-router';
import { toast } from 'sonner';
import { AlertCircle, Check, ChevronRight, Clock, Copy, Download, ExternalLink, Trash2, XCircle } from 'lucide-react';
import { Project } from 'noclick';
import { NodeMark, compactNumber, countOf, fmtBytes, relTime } from '@/ui/primitives';
import { CopyButton } from '@/ui/CopyButton';
import { cn } from '@/ui/utils';
import { PhoneBarBack, useInPhoneShell } from '@/ui/phoneBar';
import { useSlot } from '@/slots';
import { errorText } from '@/screens/console/pages/resources/shared';
import { useClient } from '@/sdk/client';
import { FilePreviewBody, fileDownloadHref } from './FilePreview';
import { FileThumb } from './fileParts';
import { useResources } from './context';
import { NUMBER_ACTIONS } from './slots';
import { kindDef, type ResourceItem, type TableRef } from './model';
import { usePlatformResources, type Removal } from './platform';
import { ConfirmAction, InnerBackContext, InnerLevel, RemovalPanel, ResourceUserChip, RowDelete, Section, Surface, WorkflowChip, type InnerStep } from './ui';
import { DatasetRows } from './DatasetRows';
import { BUTTON_PRIMARY, BUTTON_SECONDARY } from '@/ui/buttons';
import { PAGE_TITLE } from '@/ui/titles';

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

/** An automation's tables: each opens its rows a level down (`?table=` its id), and can be deleted, its preview's
 *  words first, by whoever may edit its automation. */
function TablesBody({ tables, now, onChanged }: { tables: TableRef[]; now: string; onChanged: () => void }) {
    const [params, setParams] = useSearchParams();
    const [removing, setRemoving] = useState<TableRef | null>(null);
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
                            {table.removal && <RowDelete name={table.entry.path} asking={false} onAsk={() => setRemoving(table)} onConfirm={() => undefined} />}
                        </div>
                    ))}
                </Surface>
            )}
            {removing?.removal && (
                <RemovalPanel
                    key={removing.entry.resourceId}
                    removal={removing.removal}
                    onCancel={() => setRemoving(null)}
                    onDone={({ done }) => {
                        toast.success(done);
                        setRemoving(null);
                        onChanged();
                    }}
                />
            )}
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

/** Where a resource's page sits: the way back (Resources / its kind, or a phone's bar, which `inner` takes over while
 *  its body is a level down), at the page's width. A platform's own page for a kind (an agent's) is framed the same. */
export function ResourcePageFrame({
    kindLabel,
    onBack,
    inner,
    wide,
    children,
}: {
    kindLabel: string;
    onBack: (to: 'all' | 'kind') => void;
    inner?: InnerStep | null;
    wide?: boolean;
    children: ReactNode;
}) {
    const inPhone = useInPhoneShell();
    return (
        // Relative: what a page positions (a screen-reader live region) lays out in its scroll, not the shell's.
        <div className="relative h-full overflow-y-auto scrollbar-subtle" data-testid="resource-detail">
            <div className={cn('mx-auto w-full px-5 pb-24 pt-4 sm:px-8 sm:pt-8', wide ? 'max-w-[1200px]' : 'max-w-[960px]')}>
                {inPhone ? (
                    <PhoneBarBack label={inner?.label ?? kindLabel} onBack={inner?.onBack ?? (() => onBack('kind'))} />
                ) : (
                    <nav aria-label="Breadcrumb" className="mb-6 flex items-center gap-1 text-[13px] text-muted-foreground">
                        <button type="button" onClick={() => onBack('all')} className="rounded-md px-1 py-0.5 transition-colors hover:text-foreground">
                            Resources
                        </button>
                        <ChevronRight className="h-3.5 w-3.5 opacity-60" />
                        <button type="button" onClick={() => onBack('kind')} className="rounded-md px-1 py-0.5 transition-colors hover:text-foreground">
                            {kindLabel}
                        </button>
                    </nav>
                )}
                {children}
            </div>
        </div>
    );
}

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
    const platform = usePlatformResources();
    const { openWorkflow } = useResources();
    const client = useClient();
    const NumberActions = useSlot(NUMBER_ACTIONS);
    const [inner, setInner] = useState<InnerStep | null>(null);
    // Taken when asked, so its preview is read once. Another item's page starts without it, put down as that page
    // renders: an effect runs only after the page is drawn, and undid a Delete clicked before it ran.
    const [removing, setRemoving] = useState<Removal | null>(null);
    const [removingFor, setRemovingFor] = useState(item.id);
    if (removingFor !== item.id) {
        setRemovingFor(item.id);
        setRemoving(null);
    }
    const removed =({ done, gone }: { done: string; gone: boolean }) => {
        toast.success(done);
        setRemoving(null);
        if (gone) onChanged();
    };

    // Taken down by its own id, whether or not its automation is still there.
    const unpublish = async () => {
        try {
            await Project.fromId(item.id, { client }).unpublish();
            toast.success(`Unpublished ${item.title}`);
            onChanged();
        } catch (err) {
            toast.error(`Unpublish failed: ${errorText(err)}`);
        }
    };

    let facts: [string, ReactNode][] = [];
    let actions: ReactNode = null;
    let body: ReactNode = null;

    if (file) {
        const href = fileDownloadHref(file.entry, file.source);
        const removal = file.removal;
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
                {removal && !removing && (
                    <button type="button" className={cn(BUTTON_SECONDARY, 'hover:text-red-600 dark:hover:text-red-400')} onClick={() => setRemoving(removal)}>
                        <Trash2 className="h-4 w-4" />
                        {removal.label}
                    </button>
                )}
            </>
        );
        body = (
            <Section title="Preview">
                <Surface className="p-4">
                    <FilePreviewBody file={file.entry} source={file.source} />
                </Surface>
            </Section>
        );
    } else if (item.platform) {
        const p = item.platform;
        const removal = platform?.removal(item) ?? null;
        facts = p.facts;
        const Actions = platform?.Actions;
        actions = (
            <>
                {Actions && <Actions item={item} />}
                {item.kind === 'numbers' && <NumberActions item={item} />}
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
    ) : item.mark ? (
        <span className="grid h-12 w-12 shrink-0 place-items-center rounded-xl bg-foreground/[0.05] ring-1 ring-inset ring-foreground/[0.06]">
            <NodeMark type={item.mark} size="md" />
        </span>
    ) : (
        <span className="grid h-12 w-12 shrink-0 place-items-center rounded-xl bg-foreground/[0.05] ring-1 ring-inset ring-foreground/[0.06]">
            <Icon className="h-5 w-5 text-foreground/80" strokeWidth={1.75} />
        </span>
    );

    return (
        <ResourcePageFrame kindLabel={kind.label} onBack={onBack} inner={inner} wide={item.kind === 'repos' || item.kind === 'databases'}>
            <header className="flex flex-wrap items-start gap-4">
                {lead}
                <div className="min-w-0 flex-1">
                    <h1 className={cn('min-w-0 break-words sm:truncate', PAGE_TITLE)}>{item.title}</h1>
                    <p className="mt-1 text-[14px] leading-snug text-muted-foreground sm:truncate">{item.subtitle}</p>
                    {item.origin && (
                        <p className="mt-1 text-[13px] text-muted-foreground">
                            Built in the{' '}
                            {openWorkflow ? (
                                <button
                                    type="button"
                                    onClick={() => openWorkflow({ id: item.origin!.id, name: item.origin!.name })}
                                    className="text-foreground underline-offset-4 hover:underline"
                                >
                                    {item.origin.name}
                                </button>
                            ) : (
                                <span className="text-foreground">{item.origin.name}</span>
                            )}{' '}
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
            {!item.platform?.usersInBody && <UsedBy item={item} />}
            <InnerBackContext.Provider value={setInner}>{body}</InnerBackContext.Provider>
        </ResourcePageFrame>
    );
}
