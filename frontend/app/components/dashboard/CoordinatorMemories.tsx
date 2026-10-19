// A review surface for the coordinator's account-private memories. The compact
// retrieval description and full Markdown body are separate, editable fields so
// users can see what the coordinator knows and correct or forget it. It reads as
// the shell does: the serif for a memory's name, the shell's fields and pills,
// and the library as one group of rows divided by hairlines.
import { useId, useState } from 'react';
import { ArrowLeft, BookOpen, Brain, ChevronDown, ChevronRight, Folder, Loader2, MessageSquare, Pencil, Plus, RefreshCw, Search, Trash2, UserRound, X } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Skeleton } from '~/components/ui/skeleton';
import { BUTTON_DANGER, BUTTON_GHOST, BUTTON_PRIMARY, BUTTON_SECONDARY } from '~/components/shell/buttons';
import { FIELD, FIELD_LABEL } from '~/components/shell/fields';
import { DISPLAY } from '~/components/shell/titles';
import { cn } from '~/lib/utils';
import { EmptyState, HAIRLINE } from './primitives';
import { useCoordinatorMemories, type MemoryEntry, type MemoryTransport, type MemoryHeader, type MemoryNames, type CoordinatorMemoryState } from '~/hooks/useCoordinatorMemories';
import type { CoordinatorMemoryWrite } from '~/types/socket-events.generated';

const types: CoordinatorMemoryWrite['memory_type'][] = ['user', 'feedback', 'project', 'reference'];

const MEMORY_KINDS = {
    user: { label: 'About you', Icon: UserRound },
    feedback: { label: 'Preferences', Icon: MessageSquare },
    project: { label: 'Project context', Icon: Folder },
    reference: { label: 'Reference', Icon: BookOpen },
} as const;

const TEXTAREA = cn(FIELD, 'h-auto resize-y py-2.5 leading-relaxed');
const HELP = 'mt-1.5 block text-[12.5px] leading-relaxed text-muted-foreground';
const ICON_BUTTON =
    'inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-40';

/** "weekly-report-preferences" → "Weekly report preferences"; a trailing id the name was minted with stays out of it. */
function memoryTitle(name: string) {
    const words = name.replace(/-[0-9a-f]{8,}$/, '').replace(/-/g, ' ');
    return words.charAt(0).toUpperCase() + words.slice(1);
}

function memoryDate(value: string) {
    return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', year: 'numeric' }).format(new Date(value));
}

/** A memory's kind, or a plain memory where memories have none. */
function MemoryMark({ type }: { type?: MemoryHeader['memory_type'] }) {
    const Icon = type ? MEMORY_KINDS[type].Icon : Brain;
    return (
        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-foreground/[0.06] text-foreground/75 dark:bg-foreground/[0.08]" aria-hidden="true">
            <Icon className="h-4 w-4" />
        </span>
    );
}

function MemoryEditor({
    entry,
    busy,
    kinds,
    names,
    onSave,
    onDelete,
    onReload,
}: {
    entry: MemoryEntry | 'new';
    busy: boolean;
    /** Whether memories have a kind to choose. */
    kinds: boolean;
    names: MemoryNames;
    onSave: (input: CoordinatorMemoryWrite) => Promise<void>;
    onDelete: (entry: MemoryEntry) => Promise<void>;
    onReload: (id: string) => Promise<void>;
}) {
    const fieldId = useId();
    const existing = entry === 'new' ? null : entry;
    const [name, setName] = useState(existing?.name ?? '');
    const [description, setDescription] = useState(existing?.description ?? '');
    const [type, setType] = useState<CoordinatorMemoryWrite['memory_type']>(existing?.memory_type ?? 'project');
    const [content, setContent] = useState(existing?.content ?? '');
    const [confirmDelete, setConfirmDelete] = useState(false);
    return (
        <form
            className="space-y-6"
            onSubmit={(event) => {
                event.preventDefault();
                void onSave({
                    name,
                    description,
                    memory_type: type,
                    content,
                    ...(existing ? { memory_id: existing.id, expected_version: existing.version } : {}),
                });
            }}
            data-testid="memory-editor"
        >
            <div className={cn('grid gap-5', kinds && 'sm:grid-cols-[minmax(0,1fr)_180px]')}>
                <label className="block min-w-0">
                    <span className={FIELD_LABEL}>Name</span>
                    <input
                        name="memory-name"
                        value={name}
                        onChange={(e) => setName(e.target.value)}
                        placeholder="weekly-report-preferences"
                        required
                        pattern={names.pattern}
                        maxLength={names.maxLength}
                        disabled={busy}
                        title={names.hint}
                        className={FIELD}
                    />
                </label>
                {kinds && (
                    <label className="block">
                        <span className={FIELD_LABEL}>Type</span>
                        <span className="relative block">
                            <select
                                name="memory-type"
                                value={type}
                                onChange={(e) => setType(e.target.value as typeof type)}
                                disabled={busy}
                                className={cn(FIELD, 'cursor-pointer appearance-none pr-10 disabled:cursor-not-allowed')}
                            >
                                {types.map((value) => (
                                    <option key={value} value={value} className="bg-popover text-foreground">
                                        {MEMORY_KINDS[value].label}
                                    </option>
                                ))}
                            </select>
                            <ChevronDown className="pointer-events-none absolute right-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
                        </span>
                    </label>
                )}
            </div>
            <label className="block">
                <span id={`${fieldId}-summary-label`} className={FIELD_LABEL}>
                    When this is useful
                </span>
                <textarea
                    name="memory-description"
                    aria-labelledby={`${fieldId}-summary-label`}
                    aria-describedby={`${fieldId}-summary-help`}
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    placeholder="What should NoClick be doing when it recalls this?"
                    required
                    maxLength={600}
                    rows={2}
                    disabled={busy}
                    className={cn(TEXTAREA, 'min-h-[84px]')}
                />
                <span id={`${fieldId}-summary-help`} className={HELP}>
                    A short summary that helps NoClick find this memory.
                </span>
            </label>
            <label className="block">
                <span className="flex items-baseline justify-between gap-3">
                    <span id={`${fieldId}-content-label`} className={FIELD_LABEL}>
                        Memory
                    </span>
                    <span className="text-[12px] text-muted-foreground">Markdown</span>
                </span>
                <textarea
                    name="memory-content"
                    aria-labelledby={`${fieldId}-content-label`}
                    aria-describedby={`${fieldId}-content-help`}
                    value={content}
                    onChange={(e) => setContent(e.target.value)}
                    placeholder="Details, context, and references…"
                    required
                    maxLength={16000}
                    rows={9}
                    disabled={busy}
                    className={cn(TEXTAREA, 'min-h-[220px] leading-7')}
                />
                <span id={`${fieldId}-content-help`} className={HELP}>
                    The details NoClick reads when this memory is relevant.
                </span>
            </label>
            <div className="flex flex-wrap items-center gap-2">
                <button type="submit" className={BUTTON_PRIMARY} disabled={busy || !name.trim() || !description.trim() || !content.trim()}>
                    {busy && <Loader2 className="h-4 w-4 animate-spin" />}
                    Save memory
                </button>
                {existing && (
                    <>
                        <button type="button" className={BUTTON_GHOST} disabled={busy} onClick={() => void onReload(existing.id)}>
                            Reload saved version
                        </button>
                        <button
                            type="button"
                            className={cn(ICON_BUTTON, 'ml-auto hover:bg-red-500/10 hover:text-red-600 dark:hover:text-red-400')}
                            disabled={busy}
                            onClick={() => setConfirmDelete(true)}
                            aria-label="Delete memory"
                        >
                            <Trash2 className="h-4 w-4" />
                        </button>
                    </>
                )}
            </div>
            {confirmDelete && existing && (
                <div className="space-y-3 rounded-2xl bg-red-500/[0.06] p-4" role="alert">
                    <p className="m-0 text-[14px] leading-relaxed text-foreground">Forget this memory? NoClick stops recalling it. Your chat history stays.</p>
                    <div className="flex gap-2">
                        <button type="button" className={BUTTON_DANGER} disabled={busy} onClick={() => void onDelete(existing)}>
                            Forget memory
                        </button>
                        <button type="button" className={BUTTON_GHOST} disabled={busy} onClick={() => setConfirmDelete(false)}>
                            Cancel
                        </button>
                    </div>
                </div>
            )}
        </form>
    );
}

function MemoryLoading() {
    return (
        <div className={cn('divide-y overflow-hidden rounded-2xl border', HAIRLINE)} role="status" aria-label="Loading memories">
            {[72, 88, 60].map((width) => (
                <div key={width} className="flex items-start gap-3.5 px-4 py-4">
                    <Skeleton className="h-9 w-9 rounded-xl" />
                    <div className="flex-1 space-y-2 pt-1">
                        <Skeleton className="h-3.5 w-2/5" />
                        <Skeleton className="h-3" style={{ width: `${width}%` }} />
                    </div>
                </div>
            ))}
        </div>
    );
}

function MemoryDetail({ memory }: { memory: CoordinatorMemoryState }) {
    const entry = memory.selected!;
    const [editing, setEditing] = useState(entry === 'new');
    const existing = entry === 'new' ? null : entry;
    const Kind = existing && memory.kinds ? MEMORY_KINDS[existing.memory_type] : null;
    return (
        <article className="min-w-0 space-y-7 pb-8" data-testid="memory-detail">
            <header>
                {existing && (
                    <div className="mb-3 flex items-center justify-between gap-3">
                        {Kind ? (
                            <span className="inline-flex items-center gap-1.5 text-[12.5px] text-muted-foreground">
                                <Kind.Icon className="h-3.5 w-3.5" />
                                {Kind.label}
                            </span>
                        ) : (
                            <span />
                        )}
                        <button type="button" className={cn(BUTTON_GHOST, 'h-8 px-3')} disabled={memory.busy} onClick={() => setEditing(!editing)}>
                            {!editing && <Pencil className="h-3.5 w-3.5" />}
                            {editing ? 'Cancel editing' : 'Edit memory'}
                        </button>
                    </div>
                )}
                <h2 className={cn(DISPLAY, 'm-0 break-words text-[30px] leading-[1.1] text-foreground')}>{existing ? memoryTitle(existing.name) : 'Add a memory'}</h2>
                <p className="mb-0 mt-2 text-[13.5px] leading-relaxed text-muted-foreground">
                    {existing
                        ? `Updated ${memoryDate(existing.updated_at)} · ${existing.origin_conversation_id ? 'From a conversation' : 'Added by you'}`
                        : 'Something NoClick should keep in mind in future conversations.'}
                </p>
            </header>
            {editing ? (
                <MemoryEditor key={memory.editorRevision} entry={entry} busy={memory.busy} kinds={memory.kinds} names={memory.names} onSave={memory.save} onDelete={memory.forget} onReload={memory.select} />
            ) : (
                existing && (
                    <>
                        <section>
                            <h3 className="m-0 text-[13px] font-medium text-foreground/85">When this is useful</h3>
                            <p className="mb-0 mt-1.5 max-w-[68ch] text-[14px] leading-relaxed text-muted-foreground">{existing.description}</p>
                        </section>
                        <div
                            className={cn(
                                'prose prose-sm max-w-[68ch] overflow-x-auto break-words border-t pt-6 text-foreground dark:prose-invert prose-headings:font-semibold prose-headings:tracking-tight prose-headings:text-foreground prose-p:leading-7 prose-a:text-foreground prose-strong:text-foreground prose-code:text-foreground prose-pre:bg-muted [&>:first-child]:mt-0',
                                HAIRLINE
                            )}
                            data-testid="memory-content-preview"
                        >
                            <ReactMarkdown remarkPlugins={[remarkGfm]}>{existing.content}</ReactMarkdown>
                        </div>
                    </>
                )
            )}
        </article>
    );
}

/** "3 memories", "1 result", "40+ memories"; just the section's name until there is something to count. */
function libraryHeading({ loading, error, query, memories, has_more }: CoordinatorMemoryState) {
    if (loading || error || !memories.length) return query ? 'Search results' : 'Library';
    const one = memories.length === 1 && !has_more;
    return `${memories.length}${has_more ? '+' : ''} ${query ? (one ? 'result' : 'results') : one ? 'memory' : 'memories'}`;
}

/** The coordinator's memories: search, read, edit, add and forget, one column
 *  for the chat's Memories panel (CoordinatorMemories below owns the state). */
export function CoordinatorMemoriesView({ memory }: { memory: CoordinatorMemoryState }) {
    const hasSelection = memory.selected !== null;
    return (
        <div data-testid="coordinator-memories" className="space-y-5 text-foreground">
            {memory.error && (
                <div role="alert" className="rounded-xl bg-red-500/[0.06] px-4 py-3 text-[13.5px] text-red-600 dark:text-red-400">
                    {memory.error}
                </div>
            )}
            {memory.notice && (
                <p role="status" className="m-0 text-[13.5px] text-muted-foreground">
                    {memory.notice}
                </p>
            )}
            <aside className={cn('min-w-0 space-y-4', hasSelection && 'hidden')} aria-label="Memory library">
                <div className="flex items-center gap-2">
                    <div className="relative min-w-0 flex-1">
                        <Search className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
                        <input
                            aria-label="Search memories"
                            placeholder="Search memories"
                            value={memory.query}
                            onChange={(e) => memory.search(e.target.value)}
                            maxLength={300}
                            className={cn(FIELD, 'pl-10', memory.query && 'pr-10')}
                        />
                        {memory.query && (
                            <button type="button" onClick={() => memory.search('')} aria-label="Clear memory search" className={cn(ICON_BUTTON, 'absolute right-1 top-1/2 h-7 w-7 -translate-y-1/2')}>
                                <X className="h-3.5 w-3.5" />
                            </button>
                        )}
                    </div>
                    <button type="button" className={BUTTON_SECONDARY} onClick={memory.create} disabled={memory.busy}>
                        <Plus className="h-4 w-4" />
                        Add memory
                    </button>
                </div>
                <div className="flex h-8 items-center justify-between gap-3 pl-1">
                    <h3 className="m-0 text-[13px] font-medium text-muted-foreground">{libraryHeading(memory)}</h3>
                    <button type="button" onClick={memory.reload} disabled={memory.loading} aria-label="Refresh memories" className={ICON_BUTTON}>
                        <RefreshCw className={cn('h-3.5 w-3.5', memory.loading && 'animate-spin')} />
                    </button>
                </div>
                {memory.loading ? (
                    <MemoryLoading />
                ) : !memory.memories.length ? (
                    <EmptyState
                        title={memory.query ? 'No matching memories' : 'No memories yet'}
                        hint={memory.query ? 'Try different words.' : 'Add a preference, a decision, or something worth keeping.'}
                    />
                ) : (
                    <ul className={cn('m-0 divide-y overflow-hidden rounded-2xl border p-0', HAIRLINE, 'dark:divide-foreground/[0.06]')}>
                        {memory.memories.map((entry) => (
                            <li key={entry.id} className="list-none">
                                <button
                                    type="button"
                                    disabled={memory.busy}
                                    onClick={() => void memory.select(entry.id)}
                                    aria-pressed={memory.selected !== 'new' && memory.selected?.id === entry.id}
                                    className="group flex w-full items-start gap-3.5 px-4 py-3.5 text-left transition-colors hover:bg-foreground/[0.03] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring disabled:opacity-50 aria-pressed:bg-foreground/[0.05]"
                                    data-testid="memory-entry"
                                >
                                    <MemoryMark type={memory.kinds ? entry.memory_type : undefined} />
                                    <div className="min-w-0 flex-1">
                                        <div className="flex items-baseline gap-3">
                                            <span className="min-w-0 flex-1 truncate text-[14.5px] font-medium text-foreground" title={memoryTitle(entry.name)}>
                                                {memoryTitle(entry.name)}
                                            </span>
                                            <time dateTime={entry.updated_at} title={new Date(entry.updated_at).toLocaleString()} className="hidden shrink-0 text-[12.5px] tabular-nums text-muted-foreground sm:block">
                                                {memoryDate(entry.updated_at)}
                                            </time>
                                        </div>
                                        <p className="mb-0 mt-0.5 line-clamp-2 text-[13px] leading-relaxed text-muted-foreground">{entry.description}</p>
                                        {memory.kinds && <p className="mb-0 mt-1.5 text-[12px] text-muted-foreground/80">{MEMORY_KINDS[entry.memory_type].label}</p>}
                                    </div>
                                    <ChevronRight className="mt-2.5 h-4 w-4 shrink-0 text-muted-foreground/50 transition-colors group-hover:text-foreground" aria-hidden="true" />
                                </button>
                            </li>
                        ))}
                    </ul>
                )}
                {(memory.offset > 0 || memory.has_more) && (
                    <div className="flex justify-between">
                        <button type="button" className={BUTTON_GHOST} disabled={memory.offset === 0 || memory.loading} onClick={() => memory.setOffset(Math.max(0, memory.offset - 40))}>
                            Previous
                        </button>
                        <button type="button" className={BUTTON_GHOST} disabled={!memory.has_more || memory.loading} onClick={() => memory.setOffset(memory.offset + 40)}>
                            Next
                        </button>
                    </div>
                )}
            </aside>
            {(hasSelection || memory.busy) && (
                <div className="min-w-0">
                    {memory.busy && !memory.selected ? (
                        <MemoryLoading />
                    ) : memory.selected ? (
                        <>
                            <button type="button" disabled={memory.busy} onClick={memory.back} className={cn(BUTTON_GHOST, '-ml-3 mb-4 h-8 px-3')}>
                                <ArrowLeft className="h-4 w-4" />
                                All memories
                            </button>
                            <MemoryDetail key={memory.selected === 'new' ? 'new' : memory.selected.id} memory={memory} />
                        </>
                    ) : null}
                </div>
            )}
        </div>
    );
}

export function CoordinatorMemories({ transport }: { transport?: MemoryTransport }) {
    return <CoordinatorMemoriesView memory={useCoordinatorMemories(transport)} />;
}
