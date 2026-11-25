// A memory's page under its head: the agents it's attached to (each reading it, or reading and writing it), then its
// entries, searched and filtered by who wrote them, each opening to its body to edit or forget. A save lands only
// over the version read, as an agent's does, so two writers never overwrite each other.
import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { Pencil, Trash2 } from 'lucide-react';
import { useWorkClient } from '../../client';
import { useWorkV1 } from '../../agents/reads';
import { invalidateV1 } from '@/sdk/useV1';
import { forgetEntry, memoryEntries, readEntry, saveEntry, type MemoryEntry, type MemoryItem } from '@/screens/resources/knowledge';
import { BUTTON_GHOST } from '@/ui/buttons';
import { FIELD_LABEL } from '@/ui/fields';
import { relTime } from '@/ui/primitives';
import { SearchField } from '@/ui/SearchField';
import { cn } from '@/ui/utils';
import { AREA, list, PageSection, PILL_FIELD, SMALL_PRIMARY, UsedByList, WriterFace, writerName, XS } from './parts';
import { MEMORIES_KEY, useKnowledge } from './store';
import { setMode, useMode } from './mode';

type EntryFilter = 'all' | 'agents' | 'people';
const FILTERS: [EntryFilter, string][] = [
    ['all', 'All'],
    ['agents', 'Learned'],
    ['people', 'By people'],
];

const entriesKey = (id: string) => `${MEMORIES_KEY}/${id}/entries`;

export function useMemoryEntries(memory: MemoryItem) {
    return useWorkV1(entriesKey(memory.id), (client) => memoryEntries(client, memory.id));
}

/** Who wrote it and where, in a line. */
function byLine(e: MemoryEntry): string {
    const who = e.writtenBy;
    if (who?.type === 'agent') return `Learned by ${writerName(who)}${who.conversation ? `, in its conversation ${who.conversation}` : ''}`;
    return `Written by ${who?.type === 'api' ? 'your code' : 'a person'}`;
}

export function MemoryBody({ memory, now }: { memory: MemoryItem; now: string }) {
    const client = useWorkClient();
    const k = useKnowledge();
    const entries = useMemoryEntries(memory);
    const [query, setQuery] = useState('');
    const [filter, setFilter] = useState<EntryFilter>('all');
    const [expanded, setExpanded] = useState<string | null>(null);
    const writing = useMode(memory.id) === 'writing';
    const [changing, setChanging] = useState<MemoryEntry | null>(null);
    const editing: MemoryEntry | 'new' | null = changing ?? (writing ? 'new' : null);
    const setEditing = (next: MemoryEntry | 'new' | null) => {
        setChanging(next === 'new' ? null : next);
        setMode(memory.id, next === 'new' ? 'writing' : null);
    };
    useEffect(() => () => setMode(memory.id, null), [memory.id]);
    const owner = memory.agentId ? k.agent(memory.agentId) : undefined;
    const users = k.usersOf(memory);
    const writers = users.filter((u) => !u.link || u.link.writes).map((u) => u.agent);
    const q = query.trim().toLowerCase();
    const all = entries.data ?? [];
    const shown = all.filter(
        (e) =>
            (filter === 'all' || (filter === 'agents' ? e.writtenBy?.type === 'agent' : e.writtenBy?.type !== 'agent')) &&
            (!q || `${e.name} ${e.description} ${e.content ?? ''}`.toLowerCase().includes(q))
    );
    const reread = () => {
        void entries.refresh();
        invalidateV1(MEMORIES_KEY);
    };
    const forget = async (listed: MemoryEntry) => {
        let e = listed;
        try {
            // Its content too, so Undo puts it back whole.
            e = await readEntry(client, memory.id, listed.name);
            await forgetEntry(client, memory.id, e.name, e.version);
        } catch (error) {
            toast.error(`Couldn’t forget ${e.name}`, { description: error instanceof Error ? error.message : String(error) });
            return;
        }
        reread();
        toast(`Forgot ${e.name}`, {
            description: 'No agent reads it from its next turn.',
            action: {
                label: 'Undo',
                onClick: () => void saveEntry(client, memory.id, e.name, e.content ?? '', { description: e.description }).then(reread),
            },
        });
    };
    return (
        <div data-testid="memory-body">
            <PageSection title="Attached to" meta={users.length}>
                {owner && (
                    <p className="mb-2 text-[13px] leading-snug text-muted-foreground">
                        {owner.name}’s own memory: it always has it and is the only agent that writes it. Attached to another agent, it’s read-only there.
                    </p>
                )}
                <UsedByList item={memory} />
                <p className="mt-2 text-xs text-muted-foreground">
                    {writers.length
                        ? `${list(writers.map((w) => w.name))} ${writers.length === 1 ? 'saves' : 'save'} what ${writers.length === 1 ? 'it learns' : 'they learn'} here.`
                        : 'No agent writes it: it changes only when you or a teammate edit it.'}{' '}
                    Two agents saving the same entry never overwrite each other: the second reads the newer version first.
                </p>
            </PageSection>
            <PageSection title="Entries" meta={entries.data ? all.length : undefined}>
                <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
                    <SearchField value={query} onChange={setQuery} placeholder="Search entries" className="flex-1" />
                    <div className="flex items-center gap-1">
                        {FILTERS.map(([id, label]) => (
                            <button
                                key={id}
                                type="button"
                                onClick={() => setFilter(id)}
                                className={cn('h-8 rounded-full px-3 text-[13px] transition-colors', filter === id ? 'bg-foreground/[0.08] font-medium text-foreground' : 'text-muted-foreground hover:text-foreground')}
                            >
                                {label}
                            </button>
                        ))}
                    </div>
                </div>
                {editing && (
                    <EntryForm
                        memoryId={memory.id}
                        entry={editing === 'new' ? null : editing}
                        taken={all.map((e) => e.name)}
                        onCancel={() => setEditing(null)}
                        onSaved={(name) => {
                            setEditing(null);
                            reread();
                            toast(`Saved ${name}`, { description: users.length ? `${list(users.map((u) => u.agent.name))} see it from the next turn.` : undefined });
                        }}
                    />
                )}
                <ul className="-mx-2.5 mt-3" data-testid="memory-entries">
                    {shown.map((e) => {
                        const open = expanded === e.name;
                        return (
                            <li key={e.name} className="rounded-xl px-2.5 py-2.5 transition-colors hover:bg-foreground/[0.04]">
                                <button type="button" onClick={() => setExpanded(open ? null : e.name)} className="flex w-full items-start gap-3 text-left" aria-expanded={open}>
                                    <span className="mt-0.5">
                                        <WriterFace who={e.writtenBy} size={24} />
                                    </span>
                                    <span className="min-w-0 flex-1">
                                        <span className="flex items-baseline gap-2">
                                            <span className="truncate font-mono text-[12.5px] text-foreground">{e.name}</span>
                                            <span className="ml-auto shrink-0 text-xs text-muted-foreground">{e.updatedAt ? relTime(e.updatedAt, now) : ''}</span>
                                        </span>
                                        <span className="mt-0.5 block text-sm leading-snug">{e.description}</span>
                                        <span className="mt-0.5 block truncate text-xs text-muted-foreground">
                                            {byLine(e)} · v{e.version}
                                        </span>
                                    </span>
                                </button>
                                {open && (
                                    <div className="ml-9 mt-2">
                                        <EntryContent memoryId={memory.id} entry={e} />
                                        <div className="mt-2 flex gap-1">
                                            <button type="button" onClick={() => void readEntry(client, memory.id, e.name).then(setEditing)} className={cn(XS, 'text-muted-foreground hover:bg-foreground/[0.05] hover:text-foreground')}>
                                                <Pencil className="h-3.5 w-3.5" strokeWidth={1.75} />
                                                Edit
                                            </button>
                                            <button type="button" onClick={() => void forget(e)} className={cn(XS, 'text-red-600 hover:bg-red-500/10 dark:text-red-400')}>
                                                <Trash2 className="h-3.5 w-3.5" strokeWidth={1.75} />
                                                Forget
                                            </button>
                                        </div>
                                    </div>
                                )}
                            </li>
                        );
                    })}
                    {entries.data && !shown.length && <li className="px-2.5 py-6 text-sm text-muted-foreground">{q ? `Nothing matches “${query}”.` : 'Nothing here yet.'}</li>}
                    {entries.error !== undefined && !entries.data && <li className="px-2.5 py-6 text-sm text-muted-foreground">Its entries couldn’t be read.</li>}
                </ul>
                <p className="mt-3 text-xs leading-snug text-muted-foreground">
                    Agents see every entry’s name and description each turn, and read one in full when they need it. A session’s own summary isn’t kept here: it belongs to that session.
                </p>
            </PageSection>
        </div>
    );
}

/** An entry's body, read when it's opened (a list leaves content out). */
function EntryContent({ memoryId, entry }: { memoryId: string; entry: MemoryEntry }) {
    const read = useWorkV1(`${entriesKey(memoryId)}/${entry.name}@${entry.version}`, (client) => readEntry(client, memoryId, entry.name));
    const content = entry.content ?? read.data?.content;
    if (!read.data && entry.content === null && read.error === undefined) return <p className="text-[13px] text-muted-foreground">Reading it…</p>;
    return content ? (
        <p className="whitespace-pre-wrap rounded-xl bg-foreground/[0.04] px-3.5 py-3 text-[13px] leading-relaxed text-foreground/90">{content}</p>
    ) : (
        <p className="text-[13px] text-muted-foreground">Its description says it all.</p>
    );
}

/** A new entry, or one edited over the version read. */
function EntryForm({ memoryId, entry, taken, onSaved, onCancel }: { memoryId: string; entry: MemoryEntry | null; taken: string[]; onSaved: (name: string) => void; onCancel: () => void }) {
    const client = useWorkClient();
    const [name, setName] = useState(entry?.name ?? '');
    const [description, setDescription] = useState(entry?.description ?? '');
    const [body, setBody] = useState(entry?.content ?? '');
    const [busy, setBusy] = useState(false);
    const clash = !entry && taken.includes(name);
    // The API keeps an entry's line to 200 characters and asks for its body.
    const valid = /^[a-z0-9._-]{1,64}$/.test(name) && !name.startsWith('context.') && description.trim().length > 0 && description.trim().length <= 200 && body.trim().length > 0 && !clash;
    const save = async () => {
        setBusy(true);
        try {
            // An edit lands only over the version read; a new one's name was checked against the entries listed.
            await saveEntry(client, memoryId, name, body, { description: description.trim(), version: entry?.version });
            onSaved(name);
        } catch (error) {
            toast.error(`Couldn’t save ${name}`, { description: error instanceof Error ? error.message : String(error) });
            setBusy(false);
        }
    };
    return (
        <div className="mt-4 flex flex-col gap-3 border-b pb-5 dark:border-foreground/[0.08]" data-testid="entry-form">
            <div className="grid gap-3 sm:grid-cols-[220px_1fr]">
                <label>
                    <span className={FIELD_LABEL}>Name</span>
                    <input value={name} disabled={!!entry} onChange={(e) => setName(e.target.value.toLowerCase())} placeholder="refunds.over-50" className={cn(PILL_FIELD, 'font-mono text-[13px]')} />
                    {clash && <span className="mt-1.5 block text-[12.5px] text-red-600 dark:text-red-400">There’s an entry called that already.</span>}
                </label>
                <label>
                    <span className={FIELD_LABEL}>The line agents see every turn</span>
                    <input value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Refunds over $50 need the owner’s OK" className={PILL_FIELD} />
                </label>
            </div>
            <label>
                <span className={FIELD_LABEL}>The rest, read when it’s needed</span>
                <textarea value={body} onChange={(e) => setBody(e.target.value)} rows={3} className={AREA} />
            </label>
            <div className="flex gap-2">
                <button type="button" disabled={!valid || busy} onClick={() => void save()} className={SMALL_PRIMARY}>
                    Save entry
                </button>
                <button type="button" onClick={onCancel} className={BUTTON_GHOST.replace('h-9', 'h-8')}>
                    Cancel
                </button>
            </div>
        </div>
    );
}
