// Dicts: key-value stores for small state your code and agents share. The drawer (`?dict=`)
// browses keys by prefix with each one's expiry, opens a key's JSON value to edit or delete it,
// adds keys, exports, clears and deletes. App bindings are designed, not built yet: lab only.
import { useEffect, useRef, useState } from 'react';
import { ArrowLeft, Plus, Search } from 'lucide-react';
import { toast } from 'sonner';
import { SearchClearButton } from '@/ui/SearchClearButton';
import { cn } from '@/ui/utils';
import { Dict, type DictItem } from 'noclick';
import type { Snippet } from '@/screens/console/lib/snippets';
import { formatRelative } from '@/screens/console/lib/format';
import { defaultWriteUser, userLabel } from '@/screens/console/lib/userFilter';
import { useConsole } from '@/screens/console/hooks/useConsole';
import { usePaged } from '@/sdk/usePaged';
import { useSearchParam } from '@/screens/console/hooks/useQueryState';
import { recordRecent } from '@/screens/console/hooks/useRecent';
import { invalidateV1, useV1 } from '@/sdk/useV1';
import { ConsoleButton } from '../../ui/Button';
import { ConsoleDialog } from '../../ui/ConsoleDialog';
import { DataTable, type Column } from '../../ui/DataTable';
import { Drawer } from '../../ui/Drawer';
import { EmptyCode } from '../../ui/EmptyCode';
import { ErrorPanel } from '../../ui/ErrorPanel';
import { JsonView } from '../../ui/JsonView';
import { UserField } from '../../ui/UserField';
import { TimeCell } from '../../ui/TimeCell';
import { ConfirmAction, Field, INPUT, LabeledInput, PanelToolbar, Section, type PanelProps } from './shared';
import { JsonField, jsonPreview, parseJson } from './DictsQueuesShared';
import { DeleteByName, ExportSection, formatExact, formatSize, UsedByText } from './StorageShared';

export const DICTS_EMPTY: Snippet = {
    python: [
        'import noclick',
        '',
        'seen = noclick.Dict.from_name("processed-orders", create_if_missing=True)',
        'if seen.put_if_absent("o_1841", {"status": "refunded"}):',
        '    print("First time we handle o_1841")',
        'print(seen.increment("refunds-today"))',
    ].join('\n'),
    typescript: [
        'import { Dict } from "noclick";',
        '',
        'const seen = Dict.fromName("processed-orders", { createIfMissing: true });',
        'if (await seen.putIfAbsent("o_1841", { status: "refunded" })) console.log("First time we handle o_1841");',
        'console.log(await seen.increment("refunds-today"));',
    ].join('\n'),
};

const PAGE = 20;

/** How long a written key lives: kept as it was, never expiring, or a fresh expiry. */
const EXPIRIES = [
    { value: 'never', label: 'Never' },
    { value: '3600', label: 'In 1 hour' },
    { value: '86400', label: 'In 1 day' },
    { value: '604800', label: 'In 7 days' },
] as const;

/** Seconds until `expiresAt`, at least one: how a kept expiry is written back. */
export function dictsRemainingTtl(expiresAt: Date, now: number): number {
    return Math.max(1, Math.round((expiresAt.getTime() - now) / 1000));
}

/** A key's value to edit, pretty-printed. */
const editable = (value: unknown) => JSON.stringify(value, null, 2);

type Edits = Map<string, DictItem | null>;

/** The listed rows with this drawer's writes on top: edited and added keys in key order, removed ones gone. */
export function dictsApplyEdits(rows: readonly DictItem[], edits: Edits, prefix: string): DictItem[] {
    const out = new Map(rows.map((r) => [r.key, r] as const));
    for (const [key, item] of edits) {
        if (item === null) out.delete(key);
        else if (key.startsWith(prefix)) out.set(key, item);
    }
    return [...out.values()].sort((a, b) => (a.key < b.key ? -1 : a.key > b.key ? 1 : 0));
}

function KeyDialog({
    store,
    item,
    open,
    onOpenChange,
    onSaved,
}: {
    store: Dict;
    /** The key being edited; none to add one. */
    item: DictItem | null;
    open: boolean;
    onOpenChange: (open: boolean) => void;
    onSaved: (item: DictItem) => void;
}) {
    const { now } = useConsole();
    const live = item?.expiresAt && item.expiresAt.getTime() > now() ? item.expiresAt : null;
    const [key, setKey] = useState(item?.key ?? '');
    const [text, setText] = useState(item ? editable(item.value) : '');
    const [expiry, setExpiry] = useState<string>(live ? 'keep' : 'never');
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>(undefined);
    const parsed = parseJson(text);
    const save = async () => {
        if (!parsed.ok) return;
        setBusy(true);
        setError(undefined);
        try {
            const ttlS = expiry === 'keep' && live ? dictsRemainingTtl(live, now()) : expiry === 'never' ? undefined : Number(expiry);
            const name = key.trim();
            await store.put(name, parsed.value, { ttlS });
            onSaved({
                key: name,
                value: parsed.value,
                expiresAt: ttlS ? new Date(now() + ttlS * 1000) : null,
                updatedAt: new Date(now()),
                sizeBytes: new TextEncoder().encode(JSON.stringify(parsed.value)).length,
                raw: {},
            });
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
            title={item ? `Edit ${item.key}` : `Add a key to ${store.name}`}
            description={item ? 'The new value replaces the old one at once, for every reader.' : 'Your code reads it with d[key] or get.'}
            footer={
                <ConsoleButton variant="primary" disabled={busy || !parsed.ok || !key.trim()} onClick={() => void save()}>
                    {busy ? 'Saving…' : 'Save'}
                </ConsoleButton>
            }
        >
            <div className="flex flex-col gap-3">
                {!item && (
                    <LabeledInput label="Key" id="dict-key">
                        <input id="dict-key" className={cn(INPUT, 'font-mono')} value={key} onChange={(e) => setKey(e.target.value)} placeholder="o_1841" autoComplete="off" />
                    </LabeledInput>
                )}
                <JsonField id="dict-value" label="Value (JSON)" value={text} onChange={setText} rows={item ? 8 : 5} hint='An object, a list, "a string", a number, true, false or null.' />
                <LabeledInput label="Expires" id="dict-expiry">
                    <select id="dict-expiry" className={INPUT} value={expiry} onChange={(e) => setExpiry(e.target.value)}>
                        {live && <option value="keep">As it does now ({formatRelative(live, now())})</option>}
                        {EXPIRIES.map((o) => (
                            <option key={o.value} value={o.value}>
                                {o.label}
                            </option>
                        ))}
                    </select>
                </LabeledInput>
                {error !== undefined && <ErrorPanel error={error} />}
            </div>
        </ConsoleDialog>
    );
}

function KeyView({ store, item, onBack, onEdit, onRemoved }: { store: Dict; item: DictItem; onBack: () => void; onEdit: () => void; onRemoved: (key: string) => void }) {
    return (
        <div className="flex flex-col gap-4">
            <div className="flex min-w-0 items-center gap-2">
                <ConsoleButton variant="ghost" size="sm" onClick={onBack} icon={<ArrowLeft className="h-3.5 w-3.5" />}>
                    Keys
                </ConsoleButton>
                <span className="min-w-0 truncate font-mono text-[13px] text-foreground" title={item.key}>
                    {item.key}
                </span>
            </div>
            <dl className="m-0">
                <Field label="Expires">{item.expiresAt ? <TimeCell value={item.expiresAt} /> : <span className="text-muted-foreground">Never</span>}</Field>
                <Field label="Updated">
                    <TimeCell value={item.updatedAt} />
                </Field>
                <Field label="Size">
                    <span className="tabular-nums">{formatSize(item.sizeBytes)}</span>
                </Field>
            </dl>
            <Section title="Value">
                <JsonView value={item.value} />
            </Section>
            <div className="flex flex-wrap items-center gap-2">
                <ConsoleButton size="sm" onClick={onEdit}>
                    Edit value
                </ConsoleButton>
                <ConfirmAction
                    label="Delete key"
                    title={`Delete ${item.key}?`}
                    description={`Every reader sees it gone at once: d["${item.key}"] raises KeyError and get returns its default.`}
                    confirmLabel="Delete key"
                    onConfirm={async () => {
                        await store.remove(item.key);
                        onRemoved(item.key);
                    }}
                />
            </div>
        </div>
    );
}

function KeysSection({ store, onCleared }: { store: Dict; onCleared: () => void }) {
    const [typed, setTyped] = useState('');
    const typedRef = useRef<HTMLInputElement>(null);
    const [prefix, setPrefix] = useState('');
    const [edits, setEdits] = useState<Edits>(new Map());
    const [cleared, setCleared] = useState(false);
    const [open, setOpen] = useState<string | null>(null);
    const [editing, setEditing] = useState<DictItem | 'new' | null>(null);
    useEffect(() => {
        const t = window.setTimeout(() => setPrefix(typed.trim()), 250);
        return () => window.clearTimeout(t);
    }, [typed]);
    const paged = usePaged(
        cleared ? null : `dicts/${store.id}/items?${prefix}`,
        (cursor) => store.itemsPage({ prefix: prefix || undefined, cursor, limit: PAGE }),
        (i) => i.key
    );
    const rows = dictsApplyEdits(cleared ? [] : paged.rows, edits, prefix);
    const current = open ? rows.find((r) => r.key === open) : undefined;
    const saved = (item: DictItem) => {
        setEdits((prev) => new Map(prev).set(item.key, item));
        toast(`Saved ${item.key}`);
    };
    const columns: Column<DictItem>[] = [
        { id: 'key', header: 'Key', cell: (i) => <span className="block truncate font-mono text-[13px] text-foreground" title={i.key}>{i.key}</span> },
        { id: 'value', header: 'Value', width: '48%', priority: 2, cell: (i) => <span className="block truncate font-mono text-[12px] text-muted-foreground">{jsonPreview(i.value)}</span> },
        {
            id: 'expires',
            header: 'Expires',
            width: '6.5rem',
            cell: (i) => (i.expiresAt ? <TimeCell value={i.expiresAt} className="text-[13px]" /> : <span className="text-muted-foreground">Never</span>),
        },
    ];
    if (current) {
        return (
            <>
                <KeyView
                    store={store}
                    item={current}
                    onBack={() => setOpen(null)}
                    onEdit={() => setEditing(current)}
                    onRemoved={(key) => {
                        setEdits((prev) => new Map(prev).set(key, null));
                        setOpen(null);
                        toast(`Deleted ${key}`);
                    }}
                />
                {editing && editing !== 'new' && <KeyDialog key={editing.key} store={store} item={editing} open onOpenChange={(o) => !o && setEditing(null)} onSaved={saved} />}
            </>
        );
    }
    return (
        <section className="flex flex-col gap-4">
            <div>
                <div className="mb-2 flex items-center justify-between gap-2">
                    <h3 className="m-0 text-[14px] font-semibold tracking-[-0.01em] text-foreground">Keys</h3>
                    <ConsoleButton size="sm" onClick={() => setEditing('new')} icon={<Plus className="h-3.5 w-3.5" />}>
                        Add key
                    </ConsoleButton>
                </div>
                <label className="mb-2 flex h-9 items-center gap-2 rounded-md border border-input bg-background px-3 focus-within:ring-2 focus-within:ring-ring">
                    <Search aria-hidden className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                    <input
                        ref={typedRef}
                        type="search"
                        aria-label="Keys starting with"
                        value={typed}
                        onChange={(e) => setTyped(e.target.value)}
                        placeholder="Keys starting with… (o_, lock:)"
                        autoComplete="off"
                        spellCheck={false}
                        className="h-full min-w-0 flex-1 bg-transparent font-mono text-[13px] text-foreground outline-none placeholder:font-sans placeholder:text-[hsl(var(--placeholder))]"
                    />
                    <SearchClearButton value={typed} onClear={() => setTyped('')} inputRef={typedRef} className="-mr-2" />
                </label>
                <DataTable
                    label="Keys"
                    columns={columns}
                    rows={rows}
                    getRowId={(i) => i.key}
                    loading={!cleared && paged.loading}
                    error={cleared ? undefined : paged.error}
                    onRetry={() => void paged.refresh()}
                    loadMoreError={paged.loadMoreError}
                    onRowClick={(i) => setOpen(i.key)}
                    nextCursor={cleared ? null : paged.nextCursor}
                    onLoadMore={() => void paged.loadMore()}
                    loadingMore={paged.loadingMore}
                    skeletonRows={4}
                    className="[&_thead]:bg-card dark:[&_thead]:bg-sunken"
                    empty={
                        <p className="m-0 py-3 text-[13px] text-muted-foreground">
                            {prefix ? `No keys start with ${prefix}.` : 'No keys yet. Your code writes them with d[key] = value or put, or add one here.'}
                        </p>
                    }
                />
                {!cleared && rows.length > 0 && store.keyCount !== null && store.keyCount > rows.length && !prefix && (
                    <p className="m-0 mt-2 text-[12px] text-muted-foreground">
                        In key order: {formatExact(rows.length)} of {formatExact(store.keyCount)} keys shown. Type a prefix to jump to the ones you want.
                    </p>
                )}
            </div>
            <Section title="Clear">
                <div className="flex flex-wrap items-center gap-3">
                    <p className="m-0 min-w-0 flex-1 text-[13px] text-muted-foreground">Remove every key at once. The dict stays, empty, with its bindings.</p>
                    <ConfirmAction
                        label="Clear dict"
                        title={`Clear ${store.name}?`}
                        description={`All ${formatExact(store.keyCount)} keys are removed now, for every reader, and can't be brought back. Export it first to keep a copy.`}
                        confirmLabel="Clear every key"
                        onConfirm={async () => {
                            await store.clear();
                            setCleared(true);
                            setEdits(new Map());
                            invalidateV1('dicts');
                            toast(`Cleared ${store.name}`);
                            onCleared();
                        }}
                    />
                </div>
            </Section>
            {editing === 'new' && (
                <KeyDialog
                    store={store}
                    item={null}
                    open
                    onOpenChange={(o) => !o && setEditing(null)}
                    onSaved={(item) => {
                        saved(item);
                        setOpen(item.key);
                    }}
                />
            )}
        </section>
    );
}

function DictDrawer({ dictId, row, onClose }: { dictId: string | null; row?: Dict; onClose: () => void }) {
    const { client, lab } = useConsole();
    const fetched = useV1(dictId && !row ? `dicts/${dictId}` : null, () => Dict.fromId(dictId!, { client }).hydrate());
    const store = row ?? fetched.data;
    const [cleared, setCleared] = useState(false);
    useEffect(() => setCleared(false), [dictId]);
    useEffect(() => {
        if (store) recordRecent({ type: 'dict', id: store.id, label: store.name, path: 'resources/dicts', params: { dict: store.id } });
    }, [store?.id]); // eslint-disable-line react-hooks/exhaustive-deps
    return (
        <Drawer
            open={dictId !== null}
            onOpenChange={(o) => !o && onClose()}
            kind="dict"
            title={store?.name}
            id={dictId ?? undefined}
            footer={
                store ? (
                    <DeleteByName
                        label="Delete dict"
                        name={store.name}
                        description={
                            store.usedBy.length
                                ? `${store.usedBy.map((u) => u.name).join(', ')} binds it, so the delete is refused until you unbind it.`
                                : `Its ${formatExact(store.keyCount)} keys are deleted with it. This can't be undone.`
                        }
                        onConfirm={async () => {
                            await store.delete();
                            invalidateV1('dicts');
                            invalidateV1('account');
                            toast(`Deleted ${store.name}`);
                            onClose();
                        }}
                    />
                ) : undefined
            }
        >
            {!store && fetched.error !== undefined && <ErrorPanel error={fetched.error} onRetry={() => void fetched.refresh()} />}
            {!store && fetched.error === undefined && <div aria-busy className="h-40 animate-pulse rounded-lg bg-foreground/[0.04]" />}
            {store && (
                <div key={store.id} className="flex flex-col gap-6">
                    <dl className="m-0">
                        <Field label="Keys">
                            <span className="tabular-nums">{cleared ? '0' : formatExact(store.keyCount)}</span>
                        </Field>
                        <Field label="Size">
                            <span className="tabular-nums">{cleared ? '0 B' : formatSize(store.sizeBytes)}</span>
                        </Field>
                        {lab && (
                            <Field label="Bound to">
                                <UsedByText users={store.usedBy} />
                            </Field>
                        )}
                        <Field label="User">{userLabel(store.userId)}</Field>
                        <Field label="Created">
                            <TimeCell value={store.createdAt} tier="absolute" />
                        </Field>
                    </dl>
                    <KeysSection store={store} onCleared={() => setCleared(true)} />
                    <ExportSection what="JSON Lines: one key, its value and its expiry per line, as of one moment." start={() => store.export()} />
                </div>
            )}
        </Drawer>
    );
}

function CreateDict({ defaultUser }: { defaultUser: string | null }) {
    const { client } = useConsole();
    const [open, setOpen] = useState(false);
    const [user, setUser] = useState<string | null>(defaultUser);
    const [name, setName] = useState('');
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>(undefined);
    const create = async () => {
        setBusy(true);
        setError(undefined);
        try {
            const store = await Dict.create(name.trim(), { client, user });
            setOpen(false);
            invalidateV1('dicts');
            invalidateV1('account');
            toast(`Created ${store.name}`);
        } catch (e) {
            setError(e);
        } finally {
            setBusy(false);
        }
    };
    return (
        <>
            <ConsoleButton
                variant="primary"
                onClick={() => {
                    setUser(defaultUser);
                    setName('');
                    setError(undefined);
                    setOpen(true);
                }}
            >
                New store
            </ConsoleButton>
            <ConsoleDialog
                open={open}
                onOpenChange={setOpen}
                title="New key-value store"
                description="Your code reaches it by name, as its user: Dict.from_name."
                footer={
                    <ConsoleButton variant="primary" disabled={busy || !name.trim()} onClick={() => void create()}>
                        {busy ? 'Creating…' : 'Create'}
                    </ConsoleButton>
                }
            >
                <div className="flex flex-col gap-3">
                    <LabeledInput label="Name" id="dict-name">
                        <input id="dict-name" className={cn(INPUT, 'font-mono')} value={name} onChange={(e) => setName(e.target.value)} placeholder="processed-orders" autoComplete="off" />
                    </LabeledInput>
                    <UserField value={user} onChange={setUser} />
                    {error !== undefined && <ErrorPanel error={error} />}
                </div>
            </ConsoleDialog>
        </>
    );
}

export function DictsPanel({ user, setUser }: PanelProps) {
    const { client } = useConsole();
    const [dictId, setDict] = useSearchParam('dict');
    const paged = usePaged(`dicts?${user}`, (cursor) => Dict.listPage({ client, userFilter: user, cursor, limit: 50 }), (d) => d.id);
    const columns: Column<Dict>[] = [
        { id: 'name', header: 'Name', cell: (d) => <span className="truncate font-medium text-foreground">{d.name}</span> },
        { id: 'keys', header: 'Keys', width: '6rem', cell: (d) => <span className="tabular-nums">{formatExact(d.keyCount)}</span> },
        { id: 'size', header: 'Size', width: '6rem', priority: 2, cell: (d) => <span className="tabular-nums">{formatSize(d.sizeBytes)}</span> },
        { id: 'bound', header: 'Used by', priority: 3, cell: (d) => <UsedByText users={d.usedBy} /> },
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
            <PanelToolbar user={user} setUser={setUser} action={<CreateDict defaultUser={defaultWriteUser(user)} />} />
            <DataTable
                rowMenu="store"
                label="Key-value stores"
                columns={columns}
                rows={paged.rows}
                getRowId={(d) => d.id}
                loading={paged.loading}
                error={paged.error}
                onRetry={() => void paged.refresh()}
                onRowClick={(d) => setDict(d.id, { push: true })}
                selectedId={dictId}
                nextCursor={paged.nextCursor}
                onLoadMore={() => void paged.loadMore()}
                loadingMore={paged.loadingMore}
                empty={<EmptyCode title="No dicts yet." hint="Small shared state: what's been handled, counters, locks, a cache that empties itself." snippet={DICTS_EMPTY} />}
            />
            <DictDrawer dictId={dictId} row={paged.rows.find((d) => d.id === dictId)} onClose={() => setDict(null)} />
        </>
    );
}
