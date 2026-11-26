// An agent's machine, in its session's place: its one sandbox (or the agent's machine), shared by everyone talking to
// it, as one filesystem in resizable columns, each folder read as it's opened, the files the agent changed this session
// marked and opened on its change, a file read in full (a secrets file by name only) and written there (a secrets file
// a value at a time, never shown), what the machine is and costs, and a shell of your own in a drawer under the file,
// beside the agent's work. Read through `agent.sandbox(session)`: get, filesPage, read, write, setEnv, shell.
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { toast } from 'sonner';
import { ChevronRight, Copy, Download, File, FilePlus, Folder, FolderOpen, GitBranch, KeyRound, Pencil, Plus, Server, SquareTerminal, X } from 'lucide-react';
import { Agent, NotFound, Secret, type JsonObject, type MachineHostName, type NoClick, type SandboxFilesPage } from 'noclick';
import { invalidateV1, peekV1 } from '@/sdk/useV1';
import { HAIRLINE } from '@/ui/primitives';
import { PhoneBarBack } from '@/ui/phoneBar';
import { BUTTON_GHOST, BUTTON_PRIMARY, BUTTON_SECONDARY } from '@/ui/buttons';
import { FIELD } from '@/ui/fields';
import { createPanelWidth } from '@/ui/panelWidth';
import { ResizeEdge } from '@/ui/ResizeEdge';
import { CodeView, MarkdownDoc, languageFor } from '@/screens/resources/CodeView';
import { DiffView } from '@/screens/resources/DiffView';
import { ShortcutTooltip } from '@/ui/ShortcutTooltip';
import { cn } from '@/ui/utils';
import { useWorkClient } from '../client';
import { nameOf as agentNameOf, useSpaceNoClicks, useWorkV1 } from '../agents/reads';
import { HarnessMark, harnessName } from '../agents/harness';
import { MachineDot, upFor } from '../profile/facts';
import { useAgent, useConversationSandbox, useMachine } from '../profile/reads';
import { useActiveSession } from '../conversation/sessions';
import { placeName } from './machineView';
import { HOST_NAMES } from './offers';
import { ShellDrawer } from './ShellDrawer';
import { buildTree, changedFiles, isSecretFile, nameOf, secretNames, sizeText, type Changed, type Dir, type FileNode } from './tree';

export interface MachinePageProps {
    agentId: string;
    onBack(): void;
    /** The file open, where the host keeps it (Work's URL, so the agent can link to one); local when left out. */
    file?: string | null;
    onFile?(path: string | null): void;
}

const ICON_BUTTON =
    'grid h-8 w-8 shrink-0 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-foreground/[0.05] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-40';
const SMALL_SECONDARY = BUTTON_SECONDARY.replace('h-9', 'h-8').replace('px-4', 'px-3');
const SMALL_PRIMARY = BUTTON_PRIMARY.replace('h-9', 'h-8').replace('px-4', 'px-3');
const SMALL_GHOST = BUTTON_GHOST.replace('h-9', 'h-8').replace('px-3.5', 'px-3');
const SMALL_FIELD = FIELD.replace('h-10', 'h-9').replace('text-[14px]', 'text-[13px]');
/** The page's two side columns, each dragged to width and remembered per device. */
const FILES_COLUMN = createPanelWidth({ key: 'nc-work-machine-files', initial: 260, min: 200, max: 480 });
const FACTS_PANEL = createPanelWidth({ key: 'nc-work-machine-facts', initial: 280, min: 240, max: 480 });
/** Past this a file is named, not read. */
const READ_LIMIT = 2 * 1024 * 1024;
/** A folder lists this many entries at most: a checkout's node_modules is for the shell. */
const LIST_LIMIT = 500;
/** What the daemon puts where a secret the sandbox holds was: a file showing it can't be written back as read. */
const REDACTED = '[redacted]';
const ENV_KEY = /^[A-Za-z_][A-Za-z0-9_]*$/;

const key = (agentId: string, conversation: string, what: string) => `work:agent:${agentId}:machine:${conversation}:${what}`;
const listKey = (agentId: string, conversation: string, folder: string) => key(agentId, conversation, `list:${folder}`);
const readKey = (agentId: string, conversation: string, path: string) => key(agentId, conversation, `read:${path}`);
const sandboxOf = (client: NoClick, agentId: string, conversation: string) => Agent.fromId(agentId, { client }).sandbox(conversation);
const folderOf = (path: string) => path.slice(0, path.lastIndexOf('/')) || '/';
const messageOf = (error: unknown) => (error instanceof Error ? error.message : String(error));

/** Each folder from `root` down to each path's own, so a changed or opened file's folders open. */
function foldersTo(root: string, paths: Iterable<string>): string[] {
    const out = [root];
    for (const path of paths) {
        if (!path.startsWith(`${root}/`)) continue;
        const parts = path.slice(root.length + 1).split('/').slice(0, -1);
        parts.forEach((_, i) => out.push(`${root}/${parts.slice(0, i + 1).join('/')}`));
    }
    return out;
}

export function MachinePage(props: MachinePageProps) {
    const session = useActiveSession(props.agentId);
    return session ? <SessionMachine {...props} conversation={session} /> : null;
}

function SessionMachine({ agentId, conversation, onBack, file, onFile }: MachinePageProps & { conversation: string }) {
    const client = useWorkClient();
    const agent = useAgent(agentId);
    const noclicks = useSpaceNoClicks();
    const sandbox = useConversationSandbox(agentId, conversation);
    const machine = useMachine(agent.data?.machineId);
    const root = sandbox.data?.workspace ?? '/workspace';
    // A folder is read as it's opened: a checkout holds too much to read all at once (and a machine's keeps its files
    // on its own disk). A key reaches them with the agents:terminal scope, and the API says when one hasn't it.
    const rootPage = useWorkV1(sandbox.data ? listKey(agentId, conversation, root) : null, (c) => sandboxOf(c, agentId, conversation).filesPage(root, { limit: LIST_LIMIT }));
    const history = useWorkV1(key(agentId, conversation, 'history'), (c) => Agent.fromId(agentId, { client: c }).history(conversation, { limit: 200 }));
    const changed = useMemo(() => changedFiles(history.data ?? []), [history.data]);
    const changedHere = useMemo(() => [...changed.keys()].filter((p) => p.startsWith(`${root}/`) && changed.get(p)!.how !== 'deleted'), [changed, root]);
    const [ownPick, setOwnPick] = useState<string | null>(null);
    const picked = onFile ? (file ?? null) : ownPick;
    const pick = (path: string | null) => (onFile ? onFile(path) : setOwnPick(path));
    const firstOnTop = rootPage.data?.data.find((e) => e.type === 'file' && e.path.endsWith('.md'))?.path;
    const shownPath = picked ?? changedHere.find((p) => p.endsWith('.md')) ?? changedHere[0] ?? firstOnTop ?? null;
    const shown: FileNode | null = shownPath
        ? {
              path: shownPath,
              size: peekV1<SandboxFilesPage>(client, listKey(agentId, conversation, folderOf(shownPath)))?.data.find((e) => e.path === shownPath)?.size ?? null,
              changed: changed.get(shownPath) ?? null,
              secret: isSecretFile(shownPath),
          }
        : null;
    const [onlyChanged, setOnlyChanged] = useState(false);
    const [naming, setNaming] = useState(false);
    const [shell, setShell] = useState(false);
    const treeWidth = FILES_COLUMN.useWidth();
    const running = sandbox.data?.status === 'running';
    const onMachine = sandbox.data?.place === 'machine';
    // As Work names it everywhere: the account's own NoClick is "Your NoClick", never its name.
    const name = agent.data ? agentNameOf(agent.data, noclicks) : '';
    const title = onMachine ? (machine.data?.name ?? 'Its machine') : `${name}’s sandbox`;
    const saved = (path: string) => {
        invalidateV1(readKey(agentId, conversation, path));
        invalidateV1(listKey(agentId, conversation, folderOf(path)));
    };

    const header = (
        <div className="flex items-center gap-1 px-3 pb-1 pt-2.5">
            {changedHere.length > 0 && (
                <div className="flex shrink-0 items-center gap-1" role="group" aria-label="Show">
                    {[
                        [false, 'All files'],
                        [true, `Changed ${changedHere.length}`],
                    ].map(([value, label]) => (
                        <button
                            key={String(value)}
                            type="button"
                            aria-pressed={onlyChanged === value}
                            onClick={() => setOnlyChanged(value as boolean)}
                            className={cn('inline-flex h-7 items-center whitespace-nowrap rounded-full px-2.5 text-[12.5px] transition-colors', onlyChanged === value ? 'bg-foreground/[0.08] font-medium text-foreground' : 'text-muted-foreground hover:text-foreground')}
                        >
                            {label as string}
                        </button>
                    ))}
                </div>
            )}
            <span className="flex-1" />
            <ShortcutTooltip label={running ? 'New file' : 'A new file can be made while it runs'}>
                <button type="button" aria-label="New file" disabled={!running} onClick={() => setNaming(true)} className={cn(ICON_BUTTON, 'h-7 w-7')}>
                    <FilePlus className="h-4 w-4" strokeWidth={1.75} />
                </button>
            </ShortcutTooltip>
        </div>
    );

    return (
        <div className="flex h-full min-h-0 flex-1 flex-col" data-testid="machine-page">
            {/* A phone's way back is its bar's, as on every screen Work opens there: back to its session. */}
            <PhoneBarBack label={name || 'Back'} onBack={onBack} />
            <div className={cn('flex min-h-[60px] shrink-0 items-center gap-3 border-b px-5 py-2.5 max-sm:px-4', HAIRLINE)}>
                <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-foreground/[0.06] max-sm:hidden">
                    <Server className="h-4 w-4 text-foreground/75" strokeWidth={1.75} />
                </span>
                <div className="min-w-0 flex-1">
                    <p className="flex items-center gap-2 text-[14.5px] font-semibold leading-tight">
                        <span className="truncate">{title}</span>
                        {sandbox.data && <MachineDot running={running} />}
                        {sandbox.data && <span className="shrink-0 text-[12.5px] font-normal tabular-nums text-muted-foreground">{running ? (onMachine ? 'Up' : `Running ${upFor(sandbox.data.startedAt)}`) : 'Asleep'}</span>}
                    </p>
                    <p className="mt-0.5 truncate text-[12.5px] text-muted-foreground">{onMachine ? 'One machine, always on, for everyone talking to it' : 'One session, shared by everyone talking to it'}</p>
                </div>
                <button type="button" aria-label="Close" onClick={onBack} className={cn(ICON_BUTTON, 'max-sm:hidden')}>
                    <X className="h-[18px] w-[18px]" />
                </button>
            </div>
            {sandbox.data && !running && (
                <div className={cn('flex items-center gap-3 border-b px-4 py-2.5 text-[13px]', HAIRLINE)}>
                    <span className="min-w-0 flex-1 text-muted-foreground">Asleep. These are its files as it left them; it starts with its next turn.</span>
                </div>
            )}
            {sandbox.error !== undefined && !sandbox.data ? (
                <p className="p-6 text-[13.5px] text-muted-foreground">Couldn’t reach its machine: {messageOf(sandbox.error)}</p>
            ) : (
                <div className="flex min-h-0 flex-1">
                    <div className={cn('relative flex shrink-0 flex-col border-r max-sm:hidden', HAIRLINE)} style={{ width: treeWidth }}>
                        <ResizeEdge panel={FILES_COLUMN} label="Resize the files" />
                        {header}
                        {naming && (
                            <NewFile
                                root={root}
                                onCancel={() => setNaming(false)}
                                onName={(path) => {
                                    setNaming(false);
                                    pick(path);
                                }}
                            />
                        )}
                        <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-4 pt-1 scrollbar-subtle">
                            {!sandbox.data ? null : onlyChanged ? (
                                <ChangedTree tree={buildTree(root, changedHere.map((path) => ({ path, type: 'file' as const, size: null, updatedAt: null, raw: {} })), changed)} selected={shownPath} onFile={pick} />
                            ) : (
                                <Files.Provider value={{ agentId, conversation, changed, selected: shownPath, onFile: pick }}>
                                    <LazyTree root={root} />
                                </Files.Provider>
                            )}
                        </div>
                    </div>
                    <div className="flex min-w-0 flex-1 flex-col">
                        <div className="flex min-h-0 flex-1 flex-col">
                            {shown ? (
                                <FileView key={shown.path} agentId={agentId} conversation={conversation} file={shown} agentName={name} writable={running} onSaved={saved} />
                            ) : (
                                <p className="p-6 text-[13.5px] text-muted-foreground">{rootPage.data ? 'Pick a file.' : ''}</p>
                            )}
                        </div>
                        {shell && (
                            <ShellDrawer
                                label={`Your shell on ${title}, beside its work`}
                                running={running}
                                open={() => Agent.fromId(agentId, { client }).sandbox(conversation).shell()}
                                asleep="It starts with its next turn."
                                onClose={() => setShell(false)}
                            />
                        )}
                    </div>
                    {agent.data && (
                        <Facts agent={agent.data} sandbox={sandbox.data ?? null} machineName={machine.data?.name ?? null} machineHost={machine.data?.host ?? null} shell={shell} onShell={() => setShell(!shell)} root={root} client={client} />
                    )}
                </div>
            )}
        </div>
    );
}

/** A new file's name, under its workspace (or anywhere, given from /). */
function NewFile({ root, onName, onCancel }: { root: string; onName: (path: string) => void; onCancel: () => void }) {
    const [value, setValue] = useState('');
    const path = value.startsWith('/') ? value : `${root}/${value.replace(/^\.?\/+/, '')}`;
    return (
        <form
            className="px-3 pb-2"
            onSubmit={(e) => {
                e.preventDefault();
                if (value.trim() && !value.endsWith('/')) onName(path.trim());
            }}
        >
            <input
                autoFocus
                aria-label="New file’s name"
                value={value}
                onChange={(e) => setValue(e.target.value)}
                onKeyDown={(e) => e.key === 'Escape' && onCancel()}
                onBlur={() => !value && onCancel()}
                placeholder=".env, or src/notes.md"
                className={cn(SMALL_FIELD, 'font-mono')}
            />
        </form>
    );
}

/** What every folder of the tree reads from, and how a file is opened. */
const Files = createContext<{ agentId: string; conversation: string; changed: ReadonlyMap<string, Changed>; selected: string | null; onFile: (path: string) => void } | null>(null);
const OpenFolders = createContext<{ open: ReadonlySet<string>; toggle: (path: string) => void }>({ open: new Set(), toggle: () => undefined });

/** Its files from its workspace down, each folder read the first time it opens; the folders holding a change and the
 *  open file's folders open by themselves. */
function LazyTree({ root }: { root: string }) {
    const files = useContext(Files)!;
    const [open, setOpen] = useState<Set<string>>(() => new Set(foldersTo(root, [...files.changed.keys(), ...(files.selected ? [files.selected] : [])])));
    useEffect(() => {
        setOpen((prev) => {
            const next = new Set(prev);
            for (const f of foldersTo(root, [...files.changed.keys(), ...(files.selected ? [files.selected] : [])])) next.add(f);
            return next.size === prev.size ? prev : next;
        });
    }, [root, files.changed, files.selected]);
    const toggle = (path: string) =>
        setOpen((prev) => {
            const next = new Set(prev);
            if (next.has(path)) next.delete(path);
            else next.add(path);
            return next;
        });
    return (
        <OpenFolders.Provider value={{ open, toggle }}>
            <ul aria-label="Its files">
                <FolderRow path={root} name={root} depth={0} root />
            </ul>
        </OpenFolders.Provider>
    );
}

function FolderRow({ path, name, depth, root = false }: { path: string; name: string; depth: number; root?: boolean }) {
    const { open, toggle } = useContext(OpenFolders);
    const isOpen = open.has(path);
    return (
        <li>
            <FolderButton name={name} depth={depth} open={isOpen} root={root} onClick={() => toggle(path)} />
            {isOpen && <FolderContents folder={path} depth={depth + 1} />}
        </li>
    );
}

function FolderContents({ folder, depth }: { folder: string; depth: number }) {
    const files = useContext(Files)!;
    const page = useWorkV1(listKey(files.agentId, files.conversation, folder), (c) => sandboxOf(c, files.agentId, files.conversation).filesPage(folder, { limit: LIST_LIMIT }));
    const pad = { paddingLeft: 6 + depth * 14 + 18 };
    if (!page.data)
        return (
            <p className="py-1 pr-2 text-[12.5px] text-muted-foreground" style={pad} role={page.error !== undefined ? 'alert' : undefined}>
                {page.error !== undefined ? `Couldn’t list ${depth === 1 ? 'its files' : 'it'}: ${messageOf(page.error)}` : depth === 1 ? 'Reading its files…' : 'Reading…'}
            </p>
        );
    const byName = (a: { path: string }, b: { path: string }) => nameOf(a.path).localeCompare(nameOf(b.path));
    const dirs = page.data.data.filter((e) => e.type === 'directory').sort(byName);
    const shown = page.data.data.filter((e) => e.type === 'file').sort(byName);
    return (
        <ul>
            {dirs.map((d) => (
                <FolderRow key={d.path} path={d.path} name={nameOf(d.path)} depth={depth} />
            ))}
            {shown.map((f) => (
                <FileRow key={f.path} file={{ path: f.path, size: f.size, changed: files.changed.get(f.path) ?? null, secret: isSecretFile(f.path) }} depth={depth} selected={files.selected === f.path} onFile={files.onFile} />
            ))}
            {!dirs.length && !shown.length && (
                <p className="py-1 pr-2 text-[12.5px] text-muted-foreground" style={pad}>
                    Empty
                </p>
            )}
            {page.data.nextCursor && (
                <p className="py-1 pr-2 text-[12.5px] text-muted-foreground" style={pad}>
                    Only the first {LIST_LIMIT} are listed here. Open a shell to see the rest.
                </p>
            )}
        </ul>
    );
}

function FolderButton({ name, depth, open, root, onClick }: { name: string; depth: number; open: boolean; root: boolean; onClick: () => void }) {
    return (
        <button type="button" aria-expanded={open} onClick={onClick} className="flex w-full items-center gap-1.5 rounded-md py-1 pr-2 text-left transition-colors hover:bg-foreground/[0.04]" style={{ paddingLeft: 6 + depth * 14 }}>
            <ChevronRight className={cn('h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform', open && 'rotate-90')} strokeWidth={2} />
            {open ? <FolderOpen className="h-4 w-4 shrink-0 text-muted-foreground" strokeWidth={1.75} /> : <Folder className="h-4 w-4 shrink-0 text-muted-foreground" strokeWidth={1.75} />}
            <span className={cn('min-w-0 flex-1 truncate', root ? 'font-mono text-[12.5px] text-foreground/85' : 'text-[13.5px]')}>{name}</span>
        </button>
    );
}

function FileRow({ file, depth, selected, onFile }: { file: FileNode; depth: number; selected: boolean; onFile: (path: string) => void }) {
    return (
        <li>
            <button
                type="button"
                onClick={() => onFile(file.path)}
                aria-current={selected ? 'true' : undefined}
                className={cn('flex w-full items-center gap-1.5 rounded-md py-1 pr-2 text-left text-[13.5px] transition-colors', selected ? 'bg-foreground/[0.08] text-foreground' : 'text-foreground/80 hover:bg-foreground/[0.04]')}
                style={{ paddingLeft: 6 + depth * 14 + 18 }}
            >
                {file.secret ? <KeyRound className="h-3.5 w-3.5 shrink-0 text-muted-foreground" strokeWidth={1.75} /> : <File className="h-3.5 w-3.5 shrink-0 text-muted-foreground" strokeWidth={1.75} />}
                <span className="min-w-0 flex-1 truncate">{nameOf(file.path)}</span>
                <ChangeMark file={file} />
            </button>
        </li>
    );
}

/** Only what the agent changed this session, as one tree (nothing to read: its turns kept every path). */
function ChangedTree({ tree, selected, onFile }: { tree: Dir; selected: string | null; onFile: (path: string) => void }) {
    const render = (d: Dir, depth: number, root: boolean): ReactNode => (
        <li key={d.path}>
            <FolderButton name={d.name} depth={depth} open root={root} onClick={() => undefined} />
            <ul>
                {d.dirs.map((x) => render(x, depth + 1, false))}
                {d.files.map((f) => (
                    <FileRow key={f.path} file={f} depth={depth + 1} selected={selected === f.path} onFile={onFile} />
                ))}
            </ul>
        </li>
    );
    return <ul aria-label="Its changed files">{render(tree, 0, true)}</ul>;
}

function ChangeMark({ file }: { file: FileNode }) {
    if (!file.changed) return null;
    const added = file.changed.how === 'added';
    return (
        <ShortcutTooltip label={added ? 'Added in this session' : 'Changed in this session'}>
            <span className={cn('shrink-0 font-mono text-[11px] font-semibold', added ? 'text-emerald-600 dark:text-emerald-400' : 'text-foreground/60')}>{added ? 'A' : 'M'}</span>
        </ShortcutTooltip>
    );
}

/** One file: read in full, or the change the agent made to it, and written where it runs. A secrets file shows its
 *  names and never a value, and takes a value at a time. A file that isn't there yet opens to be made. */
function FileView({ agentId, conversation, file, agentName, writable, onSaved }: { agentId: string; conversation: string; file: FileNode; agentName: string; writable: boolean; onSaved: (path: string) => void }) {
    const client = useWorkClient();
    const [view, setView] = useState<'file' | 'change'>(file.changed ? 'change' : 'file');
    const tooBig = (file.size ?? 0) > READ_LIMIT;
    const bytes = useWorkV1(tooBig || (view === 'change' && !file.secret) ? null : readKey(agentId, conversation, file.path), (c) => sandboxOf(c, agentId, conversation).read(file.path));
    const text = useMemo(() => (bytes.data ? new TextDecoder().decode(bytes.data) : null), [bytes.data]);
    const missing = bytes.error instanceof NotFound;
    const binary = !!text && text.includes('\u0000');
    const shownView = file.changed && !file.secret ? view : 'file';
    const [draft, setDraft] = useState<string | null>(null);
    const [saving, setSaving] = useState(false);
    const hidesSecret = !!text && text.includes(REDACTED);
    const editable = writable && !file.secret && shownView === 'file' && !binary && !tooBig && (text !== null || missing);
    const editing = draft !== null || (missing && writable && !file.secret);
    const save = async () => {
        setSaving(true);
        try {
            await sandboxOf(client, agentId, conversation).write(file.path, draft ?? '');
            toast('Saved', { description: file.path });
            setDraft(null);
            onSaved(file.path);
        } catch (error) {
            toast.error('Couldn’t save it', { description: messageOf(error) });
        } finally {
            setSaving(false);
        }
    };
    const download = async (data: Uint8Array) => {
        const url = URL.createObjectURL(new Blob([data as BlobPart]));
        const a = document.createElement('a');
        a.href = url;
        a.download = nameOf(file.path);
        a.click();
        URL.revokeObjectURL(url);
    };
    const note = missing
        ? 'Not there yet'
        : file.changed
          ? `${file.changed.how === 'added' ? 'Added' : 'Changed'} by ${agentName} in this session`
          : file.secret
            ? 'Secrets: names only'
            : sizeText(file.size);
    return (
        <div className="flex min-h-0 flex-1 flex-col" data-testid="file-view">
            <div className={cn('flex shrink-0 items-center gap-2 border-b px-4 py-2', HAIRLINE)}>
                <div className="min-w-0 flex-1">
                    <p className="truncate font-mono text-[12.5px] text-foreground/85">{file.path}</p>
                    <p className="truncate text-[12px] text-muted-foreground">{note}</p>
                </div>
                {editing ? (
                    <>
                        {!missing && (
                            <button type="button" onClick={() => setDraft(null)} className={SMALL_GHOST}>
                                Cancel
                            </button>
                        )}
                        <button type="button" disabled={saving} onClick={() => void save()} className={SMALL_PRIMARY}>
                            {missing ? 'Create it' : 'Save'}
                        </button>
                    </>
                ) : (
                    <>
                        {file.changed && !file.secret && (
                            <span className="flex shrink-0 items-center rounded-full bg-foreground/[0.05] p-0.5" role="group" aria-label="Show">
                                {(['change', 'file'] as const).map((v) => (
                                    <button
                                        key={v}
                                        type="button"
                                        aria-pressed={shownView === v}
                                        onClick={() => setView(v)}
                                        className={cn('h-7 rounded-full px-2.5 text-[12.5px] transition-colors', shownView === v ? 'bg-background font-medium text-foreground shadow-sm dark:bg-foreground/[0.12]' : 'text-muted-foreground hover:text-foreground')}
                                    >
                                        {v === 'change' ? 'Its change' : 'File'}
                                    </button>
                                ))}
                            </span>
                        )}
                        {editable && (
                            <ShortcutTooltip label={hidesSecret ? 'It holds a secret NoClick hides here, so edit it in a shell' : 'Edit'}>
                                <button type="button" aria-label="Edit" disabled={hidesSecret} onClick={() => setDraft(text ?? '')} className={ICON_BUTTON}>
                                    <Pencil className="h-4 w-4" strokeWidth={1.75} />
                                </button>
                            </ShortcutTooltip>
                        )}
                        {!file.secret && !missing && (
                            <>
                                <ShortcutTooltip label="Copy path">
                                    <button
                                        type="button"
                                        aria-label="Copy path"
                                        onClick={() => {
                                            void navigator.clipboard?.writeText(file.path);
                                            toast('Path copied', { description: file.path });
                                        }}
                                        className={ICON_BUTTON}
                                    >
                                        <Copy className="h-4 w-4" strokeWidth={1.75} />
                                    </button>
                                </ShortcutTooltip>
                                {bytes.data && (
                                    <ShortcutTooltip label="Download">
                                        <button type="button" aria-label="Download" onClick={() => void download(bytes.data!)} className={ICON_BUTTON}>
                                            <Download className="h-4 w-4" strokeWidth={1.75} />
                                        </button>
                                    </ShortcutTooltip>
                                )}
                            </>
                        )}
                    </>
                )}
            </div>
            <div className="min-h-0 flex-1 overflow-auto scrollbar-subtle">
                {file.secret ? (
                    <SecretsFile agentId={agentId} conversation={conversation} path={file.path} names={missing ? [] : text === null ? null : secretNames(text)} error={missing ? undefined : bytes.error} writable={writable} onSaved={onSaved} />
                ) : editing ? (
                    <textarea
                        autoFocus
                        aria-label={`${nameOf(file.path)}’s text`}
                        value={draft ?? ''}
                        onChange={(e) => setDraft(e.target.value)}
                        spellCheck={false}
                        placeholder={missing ? `What goes in ${nameOf(file.path)}` : undefined}
                        className="block h-full min-h-[240px] w-full resize-none bg-transparent px-5 py-4 font-mono text-[12.5px] leading-relaxed text-foreground outline-none"
                    />
                ) : missing ? (
                    <p className="p-6 text-[13.5px] text-muted-foreground">No file here yet. It can be made while it runs: it starts with its next turn.</p>
                ) : shownView === 'change' ? (
                    <div className="p-3">
                        <DiffView patch={file.changed!.patch} path={file.path} />
                    </div>
                ) : tooBig ? (
                    <p className="p-6 text-[13.5px] text-muted-foreground">{sizeText(file.size)}: too big to show here.</p>
                ) : bytes.error !== undefined ? (
                    <p className="p-6 text-[13.5px] text-muted-foreground">Couldn’t read it: {messageOf(bytes.error)}</p>
                ) : text === null ? (
                    <p className="p-6 text-[13.5px] text-muted-foreground">Reading…</p>
                ) : binary ? (
                    <p className="p-6 text-[13.5px] text-muted-foreground">A binary file; download it to open it.</p>
                ) : file.path.endsWith('.md') ? (
                    <MarkdownDoc source={text} className="px-8 py-6" />
                ) : (
                    <CodeView code={text} language={languageFor(file.path)} />
                )}
            </div>
        </div>
    );
}

/** A secrets file (`.env`): its names, a value never shown, and values set or taken out one at a time, merged into the
 *  file where it runs (`sandbox.setEnv`), so what's there and unshown stays as it is. */
function SecretsFile({ agentId, conversation, path, names, error, writable, onSaved }: { agentId: string; conversation: string; path: string; names: string[] | null; error: unknown; writable: boolean; onSaved: (path: string) => void }) {
    const client = useWorkClient();
    const [rows, setRows] = useState<{ name: string; value: string }[]>([]);
    const [unset, setUnset] = useState<Set<string>>(new Set());
    // A file with nothing in it yet (or none there) opens on a value to fill in.
    const empty = names?.length === 0 && writable;
    useEffect(() => {
        if (empty) setRows((prev) => (prev.length ? prev : [{ name: '', value: '' }]));
    }, [empty]);
    const [saving, setSaving] = useState(false);
    const set = rows.filter((r) => r.name.trim() || r.value);
    const bad = set.find((r) => !ENV_KEY.test(r.name.trim()) || r.value.includes('\n'));
    const changes = set.length > 0 || unset.size > 0;
    const save = async () => {
        setSaving(true);
        try {
            await sandboxOf(client, agentId, conversation).setEnv(path, { set: Object.fromEntries(set.map((r) => [r.name.trim(), r.value])), unset: [...unset] });
            toast('Saved', { description: `${path}: its values stay hidden here.` });
            setRows([]);
            setUnset(new Set());
            onSaved(path);
        } catch (e) {
            toast.error('Couldn’t save it', { description: messageOf(e) });
        } finally {
            setSaving(false);
        }
    };
    const edit = (i: number, change: Partial<{ name: string; value: string }>) => setRows((prev) => prev.map((r, at) => (at === i ? { ...r, ...change } : r)));
    if (error !== undefined) return <p className="p-6 text-[13.5px] text-muted-foreground">Couldn’t read it: {messageOf(error)}</p>;
    if (names === null) return <p className="p-6 text-[13.5px] text-muted-foreground">Reading…</p>;
    return (
        <div className="px-5 py-4" data-testid="secrets-file">
            <ul>
                {names.map((n) => {
                    const gone = unset.has(n);
                    return (
                        <li key={n} className={cn('group flex items-center gap-3 border-b py-2.5', HAIRLINE)}>
                            <KeyRound className="h-4 w-4 shrink-0 text-muted-foreground" strokeWidth={1.75} />
                            <span className={cn('min-w-0 flex-1 truncate font-mono text-[13px]', gone && 'text-muted-foreground line-through')}>{n}</span>
                            <span className="shrink-0 text-[12.5px] text-muted-foreground">{gone ? 'Taken out on save' : 'Value hidden'}</span>
                            {writable && (
                                <span className="flex shrink-0 items-center gap-1 opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100 max-md:opacity-100">
                                    {!gone && (
                                        <button type="button" onClick={() => setRows((prev) => [...prev.filter((r) => r.name !== n), { name: n, value: '' }])} className={SMALL_GHOST}>
                                            Replace
                                        </button>
                                    )}
                                    <button
                                        type="button"
                                        onClick={() =>
                                            setUnset((prev) => {
                                                const next = new Set(prev);
                                                if (next.has(n)) next.delete(n);
                                                else next.add(n);
                                                return next;
                                            })
                                        }
                                        className={SMALL_GHOST}
                                    >
                                        {gone ? 'Keep' : 'Remove'}
                                    </button>
                                </span>
                            )}
                        </li>
                    );
                })}
            </ul>
            {writable && (
                <div className="mt-4 space-y-2">
                    {rows.map((r, i) => (
                        <div key={i} className="flex items-center gap-2">
                            <input aria-label="Name" value={r.name} onChange={(e) => edit(i, { name: e.target.value })} placeholder="NAME" spellCheck={false} className={cn(SMALL_FIELD, 'w-[40%] font-mono')} />
                            <input aria-label={`${r.name || 'Its'} value`} type="password" autoComplete="off" value={r.value} onChange={(e) => edit(i, { value: e.target.value })} placeholder="Value" className={cn(SMALL_FIELD, 'flex-1 font-mono')} autoFocus={!!r.name && !r.value} />
                            <button type="button" aria-label="Drop this one" onClick={() => setRows((prev) => prev.filter((_, at) => at !== i))} className={ICON_BUTTON}>
                                <X className="h-4 w-4" />
                            </button>
                        </div>
                    ))}
                    <div className="flex items-center gap-2 pt-1">
                        <button type="button" onClick={() => setRows((prev) => [...prev, { name: '', value: '' }])} className={SMALL_GHOST}>
                            <Plus className="h-4 w-4" strokeWidth={1.75} />
                            Add a value
                        </button>
                        <span className="flex-1" />
                        {changes && (
                            <button type="button" disabled={saving || !!bad} onClick={() => void save()} className={SMALL_PRIMARY}>
                                Save
                            </button>
                        )}
                    </div>
                    {bad && <p className="text-[12.5px] text-muted-foreground">{!ENV_KEY.test(bad.name.trim()) ? 'A name is letters, digits and _, and doesn’t start with a digit.' : `${bad.name}’s value is one line.`}</p>}
                </div>
            )}
            <p className="mt-4 text-[12.5px] leading-snug text-muted-foreground">
                {writable
                    ? 'Values go straight into this file where the agent runs. They never show here again, to you or anyone in the space, and NoClick hides them from what it shows of the agent’s work. The agent itself can read the file: ask it to use them from its code, not print them.'
                    : 'Secret values never show here, to you or to anyone in the space. Values can be added while it runs: it starts with its next turn.'}
            </p>
        </div>
    );
}

/** What the machine is and costs, what's on it, and the shell. */
function Facts({
    agent,
    sandbox,
    machineName,
    machineHost,
    shell,
    onShell,
    root,
    client,
}: {
    agent: Agent;
    sandbox: { place: string; cpu: number | null; memoryMb: number | null; usdPerHour: number | null; spentUsdToday: number | null; region: string | null; status: string } | null;
    machineName: string | null;
    /** Who runs it, on a NoClick machine (null on your own). */
    machineHost: MachineHostName | null;
    shell: boolean;
    /** Opens a shell of your own on it; absent where this client can't reach its sandbox. */
    onShell?: () => void;
    root: string;
    client: ReturnType<typeof useWorkClient>;
}) {
    const width = FACTS_PANEL.useWidth();
    const secrets = useWorkV1(agent.secretIds.length ? `work:agent:${agent.id}:secrets` : null, async () => (await Secret.list({ client })).filter((s) => agent.secretIds.includes(s.id)));
    const onMachine = sandbox?.place === 'machine';
    const size = sandbox?.cpu ? `${sandbox.cpu} vCPU · ${Math.round((sandbox.memoryMb ?? 0) / 1024)} GB` : null;
    const rows: [string, ReactNode][] = [
        ['Kind', onMachine ? `${machineName ?? 'A machine'}, always on` : sandbox?.place === 'live' ? 'Its app’s live container' : 'Cloud sandbox, one per agent'],
        ...(size ? [['Size', size] as [string, ReactNode]] : []),
        ...(onMachine && machineHost ? [['Host', HOST_NAMES[machineHost]] as [string, ReactNode]] : []),
        ...(sandbox?.usdPerHour !== null && sandbox?.usdPerHour !== undefined && !onMachine ? [['Price', `$${sandbox.usdPerHour.toFixed(2)} an hour while it works`] as [string, ReactNode]] : []),
        ...(sandbox?.spentUsdToday !== null && sandbox?.spentUsdToday !== undefined ? [['Today', `$${sandbox.spentUsdToday.toFixed(2)}`] as [string, ReactNode]] : []),
        [
            'Runs',
            <span key="h" className="inline-flex items-center gap-1.5">
                <HarnessMark harness={agent.harness ?? 'sdk'} className="h-3.5 w-3.5" />
                {harnessName(agent.harness ?? 'sdk')}
            </span>,
        ],
        ...(sandbox?.region ? [['Region', placeName(sandbox.region)] as [string, ReactNode]] : []),
    ];
    const repos = agent.repos.map((r: JsonObject) => String(r.repo ?? r.name ?? r.repo_id ?? '')).filter(Boolean);
    const running = sandbox?.status === 'running';
    return (
        <aside className={cn('relative shrink-0 overflow-y-auto border-l px-5 py-5 scrollbar-subtle max-md:hidden', HAIRLINE)} style={{ width }} aria-label="Its machine">
            <ResizeEdge panel={FACTS_PANEL} side="left" label="Resize the machine's details" />
            <dl className="space-y-2">
                {rows.map(([k, v]) => (
                    <div key={k} className="flex gap-3 text-[13.5px]">
                        <dt className="w-[52px] shrink-0 text-muted-foreground">{k}</dt>
                        <dd className="min-w-0 flex-1 text-foreground/90">{v}</dd>
                    </div>
                ))}
            </dl>
            <section className="mt-6">
                <h3 className="text-[12.5px] font-medium text-muted-foreground">On it</h3>
                <ul className="mt-1.5 space-y-2.5">
                    <li className="flex gap-2.5">
                        <FolderOpen className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" strokeWidth={1.75} />
                        <span className="min-w-0">
                            <span className="block truncate font-mono text-[12.5px]">{root}</span>
                            <span className="block text-[12.5px] leading-snug text-muted-foreground">Its files, kept across sessions</span>
                        </span>
                    </li>
                    {repos.map((r) => (
                        <li key={r} className="flex gap-2.5">
                            <GitBranch className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" strokeWidth={1.75} />
                            <span className="min-w-0 truncate font-mono text-[12.5px]">{r}</span>
                        </li>
                    ))}
                    {(secrets.data?.length ?? 0) > 0 && (
                        <li className="flex gap-2.5">
                            <KeyRound className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" strokeWidth={1.75} />
                            <span className="min-w-0">
                                <span className="block text-[13.5px]">Environment</span>
                                <span className="block text-[12.5px] leading-snug text-muted-foreground">{secrets.data!.flatMap((s) => (s.keys.length ? s.keys : [s.name])).join(', ')} (values hidden)</span>
                            </span>
                        </li>
                    )}
                </ul>
            </section>
            {onShell && <div className="mt-6 flex flex-col gap-2">
                <button type="button" onClick={onShell} aria-pressed={shell} disabled={!running && !shell} className={cn(SMALL_SECONDARY, 'justify-center disabled:opacity-50', shell && 'bg-foreground/[0.1]')}>
                    <SquareTerminal className="h-4 w-4" strokeWidth={1.75} />
                    {shell ? 'Hide the shell' : 'Open a shell'}
                </button>
                {/* Said under it: a disabled button shows no tooltip. */}
                {!running && <p className="text-center text-[12px] text-muted-foreground">A shell opens while it runs. It starts with its next turn.</p>}
            </div>}
        </aside>
    );
}
