// A review surface for the coordinator's account-private memories. The compact
// retrieval description and full Markdown body are separate, editable fields so
// users can see what the coordinator knows and correct or forget it.
import { useState } from 'react';
import {
    ArrowLeft,
    Brain,
    Loader2,
    Plus,
    RefreshCw,
    Search,
    Trash2,
} from 'lucide-react';
import { Button } from '~/components/ui/button';
import { Input } from '~/components/ui/input';
import { Textarea } from '~/components/ui/textarea';
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogHeader,
    DialogTitle,
} from '~/components/ui/dialog';
import {
    useCoordinatorMemories,
    type MemoryEntry,
    type MemoryTransport,
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

export function CoordinatorMemories({
    transport,
}: {
    transport?: MemoryTransport;
}) {
    const memory = useCoordinatorMemories(transport);
    return (
        <div
            data-testid="coordinator-memories"
            className="space-y-4 text-foreground"
        >
            <p className="text-sm text-muted-foreground">
                Private to your account. These memories carry across coordinator
                chats and calls, including when you start a new chat.
            </p>
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
            {memory.selected ? (
                <>
                    <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        disabled={memory.busy}
                        onClick={memory.back}
                    >
                        <ArrowLeft className="mr-2 h-4 w-4" />
                        All memories
                    </Button>
                    <MemoryEditor
                        key={
                            memory.selected === 'new'
                                ? 'new'
                                : `${memory.selected.id}:${memory.editorRevision}`
                        }
                        entry={memory.selected}
                        busy={memory.busy}
                        onSave={memory.save}
                        onDelete={memory.forget}
                        onReload={memory.select}
                    />
                </>
            ) : (
                <>
                    <div className="flex items-center gap-2">
                        <div className="relative flex-1">
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
                            <RefreshCw className="h-4 w-4" />
                        </Button>
                        <Button onClick={memory.create} disabled={memory.busy}>
                            <Plus className="mr-1 h-4 w-4" />
                            Add
                        </Button>
                    </div>
                    {memory.loading ? (
                        <p
                            role="status"
                            className="py-8 text-center text-sm text-muted-foreground"
                        >
                            Loading memories…
                        </p>
                    ) : memory.memories.length === 0 &&
                      memory.error ? null : memory.memories.length === 0 ? (
                        <div className="space-y-2 py-10 text-center">
                            <Brain className="mx-auto h-8 w-8 text-muted-foreground" />
                            <p className="text-sm font-medium">
                                {memory.query
                                    ? 'No matching memories'
                                    : 'No memories yet'}
                            </p>
                            <p className="text-sm text-muted-foreground">
                                {memory.query
                                    ? 'Try different keywords.'
                                    : 'Tell the coordinator “remember this”, or add a memory here.'}
                            </p>
                        </div>
                    ) : (
                        <ul className="divide-y divide-border rounded-lg border border-border">
                            {memory.memories.map((entry) => (
                                <li key={entry.id}>
                                    <button
                                        type="button"
                                        disabled={memory.busy}
                                        onClick={() =>
                                            void memory.select(entry.id)
                                        }
                                        className="w-full space-y-1 p-3 text-left hover:bg-accent disabled:opacity-50"
                                        data-testid="memory-entry"
                                    >
                                        <div className="flex items-center justify-between gap-3">
                                            <span className="break-all text-sm font-medium">
                                                {entry.name}
                                            </span>
                                            <span className="rounded bg-muted px-2 py-0.5 text-xs capitalize text-muted-foreground">
                                                {entry.memory_type}
                                            </span>
                                        </div>
                                        <p className="text-sm text-muted-foreground">
                                            {entry.description}
                                        </p>
                                    </button>
                                </li>
                            ))}
                        </ul>
                    )}
                    {memory.busy && (
                        <p
                            role="status"
                            className="text-sm text-muted-foreground"
                        >
                            Opening memory…
                        </p>
                    )}
                    <div className="flex justify-between">
                        <Button
                            variant="ghost"
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
                            disabled={!memory.has_more || memory.loading}
                            onClick={() => memory.setOffset(memory.offset + 40)}
                        >
                            Next
                        </Button>
                    </div>
                </>
            )}
        </div>
    );
}

export function CoordinatorMemoriesDialog({
    open,
    onOpenChange,
}: {
    open: boolean;
    onOpenChange: (open: boolean) => void;
}) {
    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="max-h-[85vh] max-w-2xl overflow-y-auto">
                <DialogHeader>
                    <DialogTitle>Coordinator memories</DialogTitle>
                    <DialogDescription>
                        Review, edit, or forget what your coordinator remembers.
                    </DialogDescription>
                </DialogHeader>
                {open && <CoordinatorMemories />}
            </DialogContent>
        </Dialog>
    );
}
