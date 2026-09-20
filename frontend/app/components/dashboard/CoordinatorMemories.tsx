// A review surface for the coordinator's account-private memories. The compact
// retrieval description and full Markdown body are separate, editable fields so
// users can see what the coordinator knows and correct or forget it.
import { useId, useState } from 'react';
import {
    ArrowLeft,
    ChevronDown,
    ChevronRight,
    BookOpen,
    Folder,
    LockKeyhole,
    MessageSquare,
    Pencil,
    UserRound,
    Loader2,
    Plus,
    RefreshCw,
    Search,
    Trash2,
    X,
} from 'lucide-react';
import { Button } from '~/components/ui/button';
import { Input } from '~/components/ui/input';
import { Textarea } from '~/components/ui/textarea';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Skeleton } from '~/components/ui/skeleton';
import { cn } from '~/lib/utils';
import { EmptyState, relTime, TextLink } from './primitives';
import {
    useCoordinatorMemories,
    type MemoryEntry,
    type MemoryTransport,
    type MemoryHeader,
    type CoordinatorMemoryState,
} from '~/hooks/useCoordinatorMemories';
import type { CoordinatorMemoryWrite } from '~/types/socket-events.generated';

const types: CoordinatorMemoryWrite['memory_type'][] = [
    'user',
    'feedback',
    'project',
    'reference',
];

// Use the soft fields from template publishing, with a visible keyboard focus
// state. The editor sits directly on the page rather than inside another card.
const MEMORY_FIELD =
    'rounded-xl border-0 bg-foreground/[0.035] px-4 py-3 text-sm font-normal text-foreground shadow-none transition-colors placeholder:text-muted-foreground/50 focus-visible:bg-foreground/[0.055] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-foreground/15 focus-visible:ring-offset-0';

function MemoryEditor({
    entry,
    busy,
    onSave,
    onDelete,
    onReload,
}: {
    entry: MemoryEntry | 'new';
    busy: boolean;
    onSave: (input: CoordinatorMemoryWrite) => Promise<void>;
    onDelete: (entry: MemoryEntry) => Promise<void>;
    onReload: (id: string) => Promise<void>;
}) {
    const fieldId = useId();
    const existing = entry === 'new' ? null : entry;
    const [name, setName] = useState(existing?.name ?? '');
    const [description, setDescription] = useState(existing?.description ?? '');
    const [type, setType] = useState<CoordinatorMemoryWrite['memory_type']>(
        existing?.memory_type ?? 'project'
    );
    const [content, setContent] = useState(existing?.content ?? '');
    const [confirmDelete, setConfirmDelete] = useState(false);
    return (
        <form
            className="space-y-7"
            onSubmit={(event) => {
                event.preventDefault();
                void onSave({
                    name,
                    description,
                    memory_type: type,
                    content,
                    ...(existing
                        ? {
                              memory_id: existing.id,
                              expected_version: existing.version,
                          }
                        : {}),
                });
            }}
            data-testid="memory-editor"
        >
            <div className="grid gap-5 sm:grid-cols-[minmax(0,1fr)_190px]">
                <label className="block min-w-0 space-y-2.5 text-xs font-medium text-muted-foreground">
                    <span>Name</span>
                    <Input
                        name="memory-name"
                        value={name}
                        onChange={(e) => setName(e.target.value)}
                        placeholder="weekly-report-preferences"
                        required
                        pattern="[a-z0-9]+(-[a-z0-9]+)*"
                        maxLength={100}
                        disabled={busy}
                        title="Lowercase words separated by hyphens"
                        className={cn(MEMORY_FIELD, 'h-11')}
                    />
                </label>
                <label className="block space-y-2.5 text-xs font-medium text-muted-foreground">
                    <span>Type</span>
                    <span className="relative block">
                        <select
                            name="memory-type"
                            value={type}
                            onChange={(e) =>
                                setType(e.target.value as typeof type)
                            }
                            disabled={busy}
                            className={cn(
                                MEMORY_FIELD,
                                'h-11 w-full cursor-pointer appearance-none pr-11 disabled:cursor-not-allowed disabled:opacity-50'
                            )}
                        >
                            {types.map((value) => (
                                <option
                                    key={value}
                                    value={value}
                                    className="bg-popover text-foreground"
                                >
                                    {MEMORY_KINDS[value].label}
                                </option>
                            ))}
                        </select>
                        <ChevronDown
                            className="pointer-events-none absolute right-4 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground/70"
                            aria-hidden="true"
                        />
                    </span>
                </label>
            </div>
            <label className="block space-y-2.5 text-xs font-medium text-muted-foreground">
                <span id={`${fieldId}-summary-label`}>When this is useful</span>
                <Textarea
                    name="memory-description"
                    aria-labelledby={`${fieldId}-summary-label`}
                    aria-describedby={`${fieldId}-summary-help`}
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    placeholder="What should the coordinator be doing when it recalls this?"
                    required
                    maxLength={600}
                    rows={2}
                    disabled={busy}
                    className={cn(
                        MEMORY_FIELD,
                        'min-h-[88px] resize-y leading-relaxed'
                    )}
                />
                <span
                    id={`${fieldId}-summary-help`}
                    className="block text-[11px] font-normal leading-relaxed text-muted-foreground/70"
                >
                    A short summary that helps the coordinator find this memory.
                </span>
            </label>
            <label className="block space-y-2.5 text-xs font-medium text-muted-foreground">
                <span className="flex items-center justify-between gap-3">
                    <span id={`${fieldId}-content-label`}>Memory</span>
                    <span className="text-[11px] font-normal text-muted-foreground/60">
                        Markdown supported
                    </span>
                </span>
                <Textarea
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
                    className={cn(
                        MEMORY_FIELD,
                        'min-h-[224px] resize-y leading-7'
                    )}
                />
                <span
                    id={`${fieldId}-content-help`}
                    className="block text-[11px] font-normal leading-relaxed text-muted-foreground/70"
                >
                    The details the coordinator reads when this memory is
                    relevant.
                </span>
            </label>
            <div className="flex flex-wrap items-center gap-2 pt-1">
                <Button
                    type="submit"
                    size="sm"
                    className="px-5"
                    disabled={
                        busy ||
                        !name.trim() ||
                        !description.trim() ||
                        !content.trim()
                    }
                >
                    {busy && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                    Save memory
                </Button>
                {existing && (
                    <>
                        <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            className="text-muted-foreground"
                            disabled={busy}
                            onClick={() => void onReload(existing.id)}
                        >
                            Reload saved version
                        </Button>
                        <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            className="ml-auto text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
                            disabled={busy}
                            onClick={() => setConfirmDelete(true)}
                            aria-label="Delete memory"
                        >
                            <Trash2 className="h-4 w-4" />
                        </Button>
                    </>
                )}
            </div>
            {confirmDelete && existing && (
                <div
                    className="space-y-3 rounded-2xl bg-destructive/[0.06] p-4"
                    role="alert"
                >
                    <p className="text-sm">
                        Forget this memory? It will be removed from future
                        recall. Your chat history stays available.
                    </p>
                    <div className="flex gap-2">
                        <Button
                            type="button"
                            variant="destructive"
                            size="sm"
                            disabled={busy}
                            onClick={() => void onDelete(existing)}
                        >
                            Forget memory
                        </Button>
                        <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            disabled={busy}
                            onClick={() => setConfirmDelete(false)}
                        >
                            Cancel
                        </Button>
                    </div>
                </div>
            )}
        </form>
    );
}

const MEMORY_KINDS = {
    user: { label: 'About you', Icon: UserRound },
    feedback: { label: 'Preferences', Icon: MessageSquare },
    project: { label: 'Project context', Icon: Folder },
    reference: { label: 'Reference', Icon: BookOpen },
} as const;

function memoryTitle(name: string) {
    const words = name.replace(/-/g, ' ');
    return words.charAt(0).toUpperCase() + words.slice(1);
}

function MemoryKind({ type }: { type: MemoryHeader['memory_type'] }) {
    const { label, Icon } = MEMORY_KINDS[type];
    return (
        <span className="inline-flex items-center gap-1.5 text-[11px] font-normal text-muted-foreground">
            <Icon className="h-3 w-3" />
            {label}
        </span>
    );
}

function MemoryMark({ type }: { type: MemoryHeader['memory_type'] }) {
    const { Icon } = MEMORY_KINDS[type];
    return (
        <span
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-foreground/[0.05] text-muted-foreground"
            aria-hidden="true"
        >
            <Icon className="h-3.5 w-3.5" />
        </span>
    );
}

function memoryDate(value: string) {
    return new Intl.DateTimeFormat(undefined, {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
    }).format(new Date(value));
}

function MemoryLoading() {
    return (
        <div
            className="space-y-3 py-2"
            role="status"
            aria-label="Loading memories"
        >
            {[75, 95, 60].map((width) => (
                <Skeleton
                    key={width}
                    className="h-3"
                    style={{ width: `${width}%` }}
                />
            ))}
        </div>
    );
}

/** The bento only reads headers. Opening a preview fetches its Markdown body. */
export function MemoriesPreview({
    memory,
    now,
    onOpen,
}: {
    memory: CoordinatorMemoryState;
    now: string;
    onOpen: (id?: string) => void;
}) {
    const entries = memory.memories.slice(0, 3);
    return (
        <div data-testid="memories-preview">
            {memory.loading ? (
                <MemoryLoading />
            ) : memory.error ? (
                <div className="flex items-center justify-between gap-3 py-3">
                    <p role="alert" className="text-sm text-muted-foreground">
                        Memories couldn’t load.
                    </p>
                    <TextLink onClick={memory.reload} icon={false}>
                        Try again
                    </TextLink>
                </div>
            ) : entries.length ? (
                <div
                    className={cn(
                        'grid gap-2',
                        entries.length === 2 && 'md:grid-cols-2',
                        entries.length >= 3 && 'md:grid-cols-3'
                    )}
                >
                    {entries.map((entry) => (
                        <button
                            key={entry.id}
                            type="button"
                            onClick={() => onOpen(entry.id)}
                            data-testid="memory-preview-entry"
                            className="group flex min-w-0 flex-col rounded-lg border border-border/30 bg-foreground/[0.01] p-3 text-left transition-colors hover:border-border/60 hover:bg-foreground/[0.025] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        >
                            <span className="flex items-center gap-2.5">
                                <span className="min-w-0 flex-1 truncate text-[13px] font-medium">
                                    {memoryTitle(entry.name)}
                                </span>
                                <ChevronRight
                                    className="h-3.5 w-3.5 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-60 group-focus-visible:opacity-60"
                                    aria-hidden="true"
                                />
                            </span>
                            <span className="mt-2 line-clamp-2 text-[12px] leading-relaxed text-muted-foreground">
                                {entry.description}
                            </span>
                            <span className="mt-auto flex flex-wrap items-center gap-2 pt-3 text-[10.5px] text-muted-foreground">
                                <MemoryKind type={entry.memory_type} />
                                <span aria-hidden="true">·</span>
                                Updated {relTime(entry.updated_at, now)}
                            </span>
                        </button>
                    ))}
                </div>
            ) : (
                <div className="py-5 text-center">
                    <EmptyState
                        title="No memories yet"
                        hint="Preferences and context for future conversations."
                        className="py-0 mb-3"
                    />
                    <TextLink
                        onClick={() => {
                            onOpen();
                            memory.create();
                        }}
                    >
                        Add your first memory
                    </TextLink>
                </div>
            )}
        </div>
    );
}

function MemoryDetail({ memory }: { memory: CoordinatorMemoryState }) {
    const entry = memory.selected!;
    const [editing, setEditing] = useState(entry === 'new');
    const existing = entry === 'new' ? null : entry;
    return (
        <article
            className="min-w-0 max-w-3xl space-y-8 pb-8 pt-3"
            data-testid="memory-detail"
        >
            <header>
                {existing && (
                    <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                        <MemoryKind type={existing.memory_type} />
                        <Button
                            variant="ghost"
                            size="sm"
                            className="text-muted-foreground"
                            disabled={memory.busy}
                            onClick={() => setEditing(!editing)}
                        >
                            {!editing && (
                                <Pencil className="mr-2 h-3.5 w-3.5" />
                            )}
                            {editing ? 'Cancel editing' : 'Edit memory'}
                        </Button>
                    </div>
                )}
                <h2 className="m-0 break-words text-[22px] font-semibold leading-snug tracking-tight">
                    {existing ? memoryTitle(existing.name) : 'Add a memory'}
                </h2>
                <p className="mb-0 mt-2.5 text-xs leading-relaxed text-muted-foreground">
                    {existing
                        ? `Updated ${memoryDate(existing.updated_at)} · ${existing.origin_conversation_id ? 'From a conversation' : 'Added by you'}`
                        : 'Give your coordinator context to use in future conversations.'}
                </p>
            </header>
            <div>
                {editing ? (
                    <MemoryEditor
                        key={memory.editorRevision}
                        entry={entry}
                        busy={memory.busy}
                        onSave={memory.save}
                        onDelete={memory.forget}
                        onReload={memory.select}
                    />
                ) : (
                    existing && (
                        <>
                            <div className="mb-9 max-w-[72ch] space-y-2">
                                <p className="m-0 text-xs font-medium text-muted-foreground/70">
                                    When this is useful
                                </p>
                                <p className="mb-0 mt-2 text-sm leading-relaxed text-muted-foreground">
                                    {existing.description}
                                </p>
                            </div>
                            <div
                                className="prose prose-sm max-w-[72ch] overflow-x-auto break-words text-foreground prose-headings:font-semibold prose-headings:tracking-tight prose-headings:text-foreground prose-p:leading-7 prose-a:text-foreground prose-strong:text-foreground prose-code:text-foreground prose-pre:bg-muted dark:prose-invert [&>:first-child]:mt-0"
                                data-testid="memory-content-preview"
                            >
                                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                                    {existing.content}
                                </ReactMarkdown>
                            </div>
                        </>
                    )
                )}
            </div>
        </article>
    );
}

/** The full dashboard drill-down shares the bento's live state, so edits and
 * deletions are reflected in its preview as soon as the user returns. */
export function CoordinatorMemoriesView({
    memory,
}: {
    memory: CoordinatorMemoryState;
}) {
    const hasSelection = memory.selected !== null;
    return (
        <div
            data-testid="coordinator-memories"
            className="space-y-5 text-foreground"
        >
            <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="space-y-1.5">
                    <p className="m-0 text-sm text-muted-foreground">
                        Context that carries across conversations.
                    </p>
                    <p className="m-0 flex items-center gap-1.5 text-[11px] text-muted-foreground/80">
                        <LockKeyhole className="h-3 w-3" />
                        Private to you
                    </p>
                </div>
                {memory.selected !== 'new' && (
                    <Button
                        variant="ghost"
                        size="sm"
                        className="text-muted-foreground hover:text-foreground"
                        onClick={memory.create}
                        disabled={memory.busy}
                    >
                        <Plus className="mr-2 h-4 w-4" />
                        Add memory
                    </Button>
                )}
            </div>
            {memory.error && (
                <div
                    role="alert"
                    className="rounded-lg border border-destructive/40 p-3 text-sm text-destructive"
                >
                    {memory.error}
                </div>
            )}
            {memory.notice && (
                <p role="status" className="text-sm text-muted-foreground">
                    {memory.notice}
                </p>
            )}
            <div
                className={cn(
                    'grid items-start gap-6',
                    hasSelection && 'lg:grid-cols-[288px_minmax(0,1fr)]'
                )}
            >
                <aside
                    className={cn(
                        'min-w-0 space-y-3',
                        hasSelection && 'hidden lg:sticky lg:top-4 lg:block'
                    )}
                    aria-label="Memory library"
                >
                    <div className="flex items-center gap-2 pl-1">
                        <h2 className="m-0 text-xs font-medium text-muted-foreground">
                            {memory.query ? 'Search results' : 'Library'}
                        </h2>
                        {!memory.loading && !memory.error && (
                            <span className="text-[11px] tabular-nums text-muted-foreground/70">
                                {memory.memories.length}
                                {memory.has_more ? '+' : ''}
                            </span>
                        )}
                        <Button
                            variant="ghost"
                            size="icon"
                            onClick={memory.reload}
                            disabled={memory.loading}
                            aria-label="Refresh memories"
                            className="ml-auto h-7 w-7 rounded-lg text-muted-foreground/60 hover:text-foreground"
                        >
                            <RefreshCw
                                className={cn(
                                    'h-3 w-3',
                                    memory.loading && 'animate-spin'
                                )}
                            />
                        </Button>
                    </div>
                    <div className="flex items-center gap-2 rounded-xl bg-foreground/[0.035] px-3 py-2.5 transition-colors focus-within:bg-foreground/[0.06]">
                        <Search
                            className="h-3.5 w-3.5 shrink-0 text-muted-foreground/70"
                            aria-hidden="true"
                        />
                        <input
                            aria-label="Search memories"
                            placeholder="Search memories"
                            value={memory.query}
                            onChange={(e) => memory.search(e.target.value)}
                            maxLength={300}
                            className="min-w-0 flex-1 bg-transparent text-xs text-foreground outline-none placeholder:text-muted-foreground/55"
                        />
                        {memory.query && (
                            <button
                                type="button"
                                onClick={() => memory.search('')}
                                aria-label="Clear memory search"
                                className="rounded-md p-0.5 text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                            >
                                <X className="h-3 w-3" />
                            </button>
                        )}
                    </div>
                    {memory.loading ? (
                        <MemoryLoading />
                    ) : !memory.memories.length ? (
                        <EmptyState
                            title={
                                memory.query
                                    ? 'No matching memories'
                                    : 'No memories yet'
                            }
                            hint={
                                memory.query
                                    ? 'Try different keywords.'
                                    : 'Add a preference, a decision, or a useful reference.'
                            }
                        />
                    ) : (
                        <ul
                            className={cn(
                                'm-0 space-y-2 p-0',
                                hasSelection &&
                                    'scrollbar-subtle lg:max-h-[calc(100dvh-21rem)] lg:overflow-y-auto'
                            )}
                        >
                            {memory.memories.map((entry) => (
                                <li key={entry.id} className="list-none">
                                    <button
                                        type="button"
                                        disabled={memory.busy}
                                        onClick={() =>
                                            void memory.select(entry.id)
                                        }
                                        aria-pressed={
                                            memory.selected !== 'new' &&
                                            memory.selected?.id === entry.id
                                        }
                                        className="group flex w-full items-start gap-3 rounded-xl border border-transparent p-3.5 text-left transition-colors hover:bg-foreground/[0.035] aria-pressed:border-foreground/[0.08] aria-pressed:bg-foreground/[0.055] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring disabled:opacity-50"
                                        data-testid="memory-entry"
                                    >
                                        <MemoryMark type={entry.memory_type} />
                                        <div className="min-w-0 flex-1">
                                            <div
                                                className="truncate text-[13px] font-medium"
                                                title={memoryTitle(entry.name)}
                                            >
                                                {memoryTitle(entry.name)}
                                            </div>
                                            <p className="mb-0 mt-1 line-clamp-2 text-xs leading-relaxed text-muted-foreground">
                                                {entry.description}
                                            </p>
                                            <div className="mt-2 text-[11px] text-muted-foreground/80">
                                                {
                                                    MEMORY_KINDS[
                                                        entry.memory_type
                                                    ].label
                                                }
                                            </div>
                                        </div>
                                        {!hasSelection && (
                                            <time
                                                dateTime={entry.updated_at}
                                                title={new Date(
                                                    entry.updated_at
                                                ).toLocaleString()}
                                                className="hidden shrink-0 pt-0.5 text-[11px] text-muted-foreground sm:block"
                                            >
                                                {memoryDate(entry.updated_at)}
                                            </time>
                                        )}
                                        <ChevronRight
                                            className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground/40 transition-colors group-hover:text-foreground"
                                            aria-hidden="true"
                                        />
                                    </button>
                                </li>
                            ))}
                        </ul>
                    )}
                    {(memory.offset > 0 || memory.has_more) && (
                        <div className="flex justify-between border-t border-border pt-2">
                            <Button
                                variant="ghost"
                                size="sm"
                                disabled={memory.offset === 0 || memory.loading}
                                onClick={() =>
                                    memory.setOffset(
                                        Math.max(0, memory.offset - 40)
                                    )
                                }
                            >
                                Previous
                            </Button>
                            <Button
                                variant="ghost"
                                size="sm"
                                disabled={!memory.has_more || memory.loading}
                                onClick={() =>
                                    memory.setOffset(memory.offset + 40)
                                }
                            >
                                Next
                            </Button>
                        </div>
                    )}
                </aside>
                {(hasSelection || memory.busy) && (
                    <div className="min-w-0 lg:pl-4 xl:pl-8">
                        {memory.busy && !memory.selected ? (
                            <MemoryLoading />
                        ) : memory.selected ? (
                            <>
                                <Button
                                    type="button"
                                    variant="ghost"
                                    size="sm"
                                    disabled={memory.busy}
                                    onClick={memory.back}
                                    className="mb-3 -ml-3 text-muted-foreground"
                                >
                                    <ArrowLeft className="mr-2 h-4 w-4" />
                                    All memories
                                </Button>
                                <MemoryDetail
                                    key={
                                        memory.selected === 'new'
                                            ? 'new'
                                            : memory.selected.id
                                    }
                                    memory={memory}
                                />
                            </>
                        ) : null}
                    </div>
                )}
            </div>
        </div>
    );
}

export function CoordinatorMemories({
    transport,
}: {
    transport?: MemoryTransport;
}) {
    return (
        <CoordinatorMemoriesView memory={useCoordinatorMemories(transport)} />
    );
}
