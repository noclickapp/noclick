// A review surface for the coordinator's account-private memories. The compact
// retrieval description and full Markdown body are separate, editable fields so
// users can see what the coordinator knows and correct or forget it.
import { useState } from 'react';
import {
    ArrowLeft,
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
} from 'lucide-react';
import { Button } from '~/components/ui/button';
import { Input } from '~/components/ui/input';
import { Textarea } from '~/components/ui/textarea';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Skeleton } from '~/components/ui/skeleton';
import { cn } from '~/lib/utils';
import { EmptyState, relTime, ROWS, TextLink } from './primitives';
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
            className="space-y-4"
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
            <div className="grid grid-cols-[1fr_auto] gap-3">
                <label className="space-y-1 text-sm font-medium">
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
                    />
                </label>
                <label className="space-y-1 text-sm font-medium">
                    <span>Type</span>
                    <select
                        name="memory-type"
                        value={type}
                        onChange={(e) => setType(e.target.value as typeof type)}
                        disabled={busy}
                        className="flex h-10 w-full rounded-md border border-input bg-background px-3 text-sm capitalize"
                    >
                        {types.map((value) => (
                            <option key={value} value={value}>
                                {value}
                            </option>
                        ))}
                    </select>
                </label>
            </div>
            <label className="block space-y-1 text-sm font-medium">
                <span>Retrieval description</span>
                <Textarea
                    name="memory-description"
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    placeholder="What this memory covers and when it is useful"
                    required
                    maxLength={600}
                    rows={3}
                    disabled={busy}
                />
                <span className="block text-xs font-normal text-muted-foreground">
                    The coordinator uses this summary to decide when to read the
                    full memory. Update it when the details change.
                </span>
            </label>
            <label className="block space-y-1 text-sm font-medium">
                <span>Full memory</span>
                <Textarea
                    name="memory-content"
                    value={content}
                    onChange={(e) => setContent(e.target.value)}
                    placeholder="Details, context, and references…"
                    required
                    maxLength={16000}
                    rows={9}
                    disabled={busy}
                    className="font-mono text-sm"
                />
                <span className="block text-xs font-normal text-muted-foreground">
                    Markdown supported. Read only when needed.
                </span>
            </label>
            {existing && (
                <p className="text-xs text-muted-foreground">
                    Updated {new Date(existing.updated_at).toLocaleString()}
                    {existing.origin_conversation_id
                        ? ' · From a coordinator conversation'
                        : ' · Added here'}
                </p>
            )}
            <div className="flex flex-wrap items-center gap-2">
                <Button
                    type="submit"
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
                            variant="outline"
                            disabled={busy}
                            onClick={() => void onReload(existing.id)}
                        >
                            Reload saved version
                        </Button>
                        <Button
                            type="button"
                            variant="ghost"
                            className="ml-auto text-destructive"
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
                    className="space-y-2 rounded-lg border border-destructive/40 p-3"
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
                            disabled={busy}
                            onClick={() => void onDelete(existing)}
                        >
                            Forget memory
                        </Button>
                        <Button
                            type="button"
                            variant="ghost"
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
                        'grid divide-y divide-border md:divide-y-0 md:[&>*+*]:border-l md:[&>*+*]:border-border md:[&>*+*]:pl-6',
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
                            className="group flex min-w-0 flex-col py-2 text-left transition-colors hover:bg-foreground/[0.02] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring md:pr-6"
                        >
                            <span className="line-clamp-1 text-[13px] font-medium">
                                {memoryTitle(entry.name)}
                            </span>
                            <span className="mt-1.5 line-clamp-2 text-[12px] leading-relaxed text-muted-foreground">
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
            className="min-w-0 lg:border-l lg:border-border lg:pl-8"
            data-testid="memory-detail"
        >
            <div className="border-b border-border pb-5">
                <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
                    {existing ? (
                        <MemoryKind type={existing.memory_type} />
                    ) : (
                        <span className="text-xs text-muted-foreground">
                            New memory
                        </span>
                    )}
                    {existing && (
                        <Button
                            variant="ghost"
                            size="sm"
                            disabled={memory.busy}
                            onClick={() => setEditing(!editing)}
                        >
                            {!editing && (
                                <Pencil className="mr-2 h-3.5 w-3.5" />
                            )}
                            {editing ? 'Cancel editing' : 'Edit memory'}
                        </Button>
                    )}
                </div>
                <h2 className="m-0 break-words text-xl font-semibold tracking-tight">
                    {existing ? memoryTitle(existing.name) : 'Add a memory'}
                </h2>
                <p className="mb-0 mt-2 text-xs leading-relaxed text-muted-foreground">
                    {existing
                        ? `Updated ${new Date(existing.updated_at).toLocaleString()} · ${existing.origin_conversation_id ? 'From a conversation' : 'Added by you'}`
                        : 'Give your coordinator context to use in future conversations.'}
                </p>
            </div>
            <div className="py-6">
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
                            <div className="mb-8">
                                <p className="m-0 text-[10.5px] font-semibold uppercase tracking-wider text-muted-foreground">
                                    When this is useful
                                </p>
                                <p className="mb-0 mt-2 text-sm leading-relaxed text-muted-foreground">
                                    {existing.description}
                                </p>
                            </div>
                            <div
                                className="prose prose-sm max-w-none break-words text-foreground prose-headings:text-foreground prose-p:leading-7 prose-a:text-foreground prose-strong:text-foreground prose-code:text-foreground prose-pre:bg-muted dark:prose-invert"
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
    return (
        <div
            data-testid="coordinator-memories"
            className="space-y-5 text-foreground"
        >
            <div className="flex flex-wrap items-center justify-between gap-4">
                <div>
                    <p className="m-0 text-sm text-muted-foreground">
                        Preferences, project context, and references that carry
                        across conversations.
                    </p>
                    <p className="mb-0 mt-2 flex items-center gap-1.5 text-xs text-muted-foreground">
                        <LockKeyhole className="h-3 w-3" />
                        Private to you · Kept when you start a new chat
                    </p>
                </div>
                <Button
                    variant="outline"
                    size="sm"
                    onClick={memory.create}
                    disabled={memory.busy}
                >
                    <Plus className="mr-2 h-4 w-4" />
                    Add memory
                </Button>
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
            <div className="grid items-start gap-6 lg:grid-cols-[300px_minmax(0,1fr)]">
                <aside
                    className={cn(
                        'min-w-0 space-y-3',
                        memory.selected && 'hidden lg:block'
                    )}
                    aria-label="Memory library"
                >
                    <div className="flex items-center gap-1">
                        <div className="relative min-w-0 flex-1">
                            <Search className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
                            <Input
                                aria-label="Search memories"
                                placeholder="Search memories"
                                value={memory.query}
                                onChange={(e) => memory.search(e.target.value)}
                                maxLength={300}
                                className="pl-9"
                            />
                        </div>
                        <Button
                            variant="ghost"
                            size="icon"
                            onClick={memory.reload}
                            disabled={memory.loading}
                            aria-label="Refresh memories"
                        >
                            <RefreshCw className="h-3.5 w-3.5" />
                        </Button>
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
                        <ul className={cn(ROWS, 'm-0 p-0')}>
                            {memory.memories.map((entry) => (
                                <li key={entry.id} className="list-none py-1">
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
                                        className="w-full space-y-2 rounded-md p-3 text-left transition-colors hover:bg-foreground/[0.03] aria-pressed:bg-foreground/[0.06] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
                                        data-testid="memory-entry"
                                    >
                                        <div className="truncate text-sm font-medium">
                                            {memoryTitle(entry.name)}
                                        </div>
                                        <p className="m-0 line-clamp-2 text-xs leading-relaxed text-muted-foreground">
                                            {entry.description}
                                        </p>
                                        <MemoryKind type={entry.memory_type} />
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
                <div
                    className={cn(
                        'min-w-0',
                        !memory.selected && !memory.busy && 'hidden lg:block'
                    )}
                >
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
                                className="mb-3 lg:hidden"
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
                    ) : (
                        <div className="flex min-h-[280px] flex-col items-center justify-center px-8 text-center lg:border-l lg:border-border">
                            <BookOpen className="mb-4 h-5 w-5 text-muted-foreground/60" />
                            <h2 className="m-0 text-sm font-medium">
                                Select a memory
                            </h2>
                            <p className="mt-2 max-w-xs text-sm leading-relaxed text-muted-foreground">
                                Read its details or make a correction.
                            </p>
                        </div>
                    )}
                </div>
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
