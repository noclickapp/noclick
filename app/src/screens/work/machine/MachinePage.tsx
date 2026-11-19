// An agent's machine, in its session's place: its one sandbox (or the agent's machine), shared by everyone talking to
// it, as one filesystem in resizable columns, the files the agent changed this session marked and opened on its
// change, a file read in full (a secrets file by name only), what the machine is and costs, and a shell of your own in
// a drawer under the file, beside the agent's work. Read through `agent.sandbox(session)`: get, files, read, shell.
import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { toast } from 'sonner';
import { ChevronRight, Copy, Download, File, Folder, FolderOpen, GitBranch, KeyRound, Server, SquareTerminal, X } from 'lucide-react';
import { Agent, Secret, type JsonObject, type MachineHostName } from 'noclick';
import { HAIRLINE } from '@/ui/primitives';
import { PhoneBarBack } from '@/ui/phoneBar';
import { BUTTON_SECONDARY } from '@/ui/buttons';
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
import { buildTree, changedFiles, changedIn, filesOf, nameOf, secretNames, sizeText, type Dir, type FileNode } from './tree';

export interface MachinePageProps {
    agentId: string;
    onBack(): void;
}

const ICON_BUTTON =
    'grid h-8 w-8 shrink-0 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-foreground/[0.05] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring';
const SMALL_SECONDARY = BUTTON_SECONDARY.replace('h-9', 'h-8').replace('px-4', 'px-3');
/** The page's two side columns, each dragged to width and remembered per device. */
const FILES_COLUMN = createPanelWidth({ key: 'nc-work-machine-files', initial: 260, min: 200, max: 480 });
const FACTS_PANEL = createPanelWidth({ key: 'nc-work-machine-facts', initial: 280, min: 240, max: 480 });
/** Past this a file is named, not read. */
const READ_LIMIT = 2 * 1024 * 1024;

const key = (agentId: string, conversation: string, what: string) => `work:agent:${agentId}:machine:${conversation}:${what}`;

export function MachinePage({ agentId, onBack }: MachinePageProps) {
    const session = useActiveSession(agentId);
    return session ? <SessionMachine agentId={agentId} conversation={session} onBack={onBack} /> : null;
}

function SessionMachine({ agentId, conversation, onBack }: MachinePageProps & { conversation: string }) {
    const client = useWorkClient();
    const agent = useAgent(agentId);
    const noclicks = useSpaceNoClicks();
    const sandbox = useConversationSandbox(agentId, conversation);
    const machine = useMachine(agent.data?.machineId);
    const root = sandbox.data?.workspace ?? '/workspace';
    // Its files and a shell on it: a key reaches them with the agents:terminal scope, and the API says when one hasn't it.
    const listing = useWorkV1(sandbox.data ? key(agentId, conversation, `files:${root}`) : null, (c) => Agent.fromId(agentId, { client: c }).sandbox(conversation).files(root, { recursive: true, limit: 2000 }));
    const history = useWorkV1(key(agentId, conversation, 'history'), (c) => Agent.fromId(agentId, { client: c }).history(conversation, { limit: 200 }));
    const changed = useMemo(() => changedFiles(history.data ?? []), [history.data]);
    const tree = useMemo(() => buildTree(root, listing.data ?? [], changed), [root, listing.data, changed]);
    const files = useMemo(() => filesOf(tree), [tree]);
    const firstChanged = files.find((f) => f.changed && f.path.endsWith('.md')) ?? files.find((f) => f.changed) ?? files.find((f) => f.path.endsWith('.md')) ?? files[0];
    const [selected, setSelected] = useState<string | null>(null);
    const [onlyChanged, setOnlyChanged] = useState(false);
    const [shell, setShell] = useState(false);
    const treeWidth = FILES_COLUMN.useWidth();
    const shown = files.find((f) => f.path === (selected ?? firstChanged?.path)) ?? null;
    const changedCount = files.filter((f) => f.changed).length;
    const running = sandbox.data?.status === 'running';
    const onMachine = sandbox.data?.place === 'machine';
    // As Work names it everywhere: the account's own NoClick is "Your NoClick", never its name.
    const name = agent.data ? agentNameOf(agent.data, noclicks) : '';
    const title = onMachine ? (machine.data?.name ?? 'Its machine') : `${name}’s sandbox`;

    const filter = changedCount > 0 && (
        <div className="flex items-center gap-1 px-3 pb-1 pt-2.5" role="group" aria-label="Show">
            {[
                [false, 'All files'],
                [true, `Changed ${changedCount}`],
            ].map(([value, label]) => (
                <button
                    key={String(value)}
                    type="button"
                    aria-pressed={onlyChanged === value}
                    onClick={() => setOnlyChanged(value as boolean)}
                    className={cn('inline-flex h-7 items-center rounded-full px-2.5 text-[12.5px] transition-colors', onlyChanged === value ? 'bg-foreground/[0.08] font-medium text-foreground' : 'text-muted-foreground hover:text-foreground')}
                >
                    {label as string}
                </button>
            ))}
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
                <p className="p-6 text-[13.5px] text-muted-foreground">Couldn’t reach its machine: {sandbox.error instanceof Error ? sandbox.error.message : String(sandbox.error)}</p>
            ) : (
                <div className="flex min-h-0 flex-1">
                    <div className={cn('relative flex shrink-0 flex-col border-r max-sm:hidden', HAIRLINE)} style={{ width: treeWidth }}>
                        <ResizeEdge panel={FILES_COLUMN} label="Resize the files" />
                        {filter}
                        <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-4 pt-1 scrollbar-subtle">
                            {listing.data ? (
                                <Tree tree={tree} selected={shown?.path ?? null} onFile={setSelected} onlyChanged={onlyChanged} />
                            ) : (
                                <p className="px-2 py-3 text-[13px] text-muted-foreground">
                                    {listing.error !== undefined ? `Couldn’t list its files: ${listing.error instanceof Error ? listing.error.message : String(listing.error)}` : 'Reading its files…'}
                                </p>
                            )}
                        </div>
                    </div>
                    <div className="flex min-w-0 flex-1 flex-col">
                        <div className="flex min-h-0 flex-1 flex-col">
                            {shown ? <FileView key={shown.path} agentId={agentId} conversation={conversation} file={shown} agentName={name} /> : <p className="p-6 text-[13.5px] text-muted-foreground">{listing.data ? 'Pick a file.' : ''}</p>}
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

/** Every folder as a tree, open where the agent changed something. */
function Tree({ tree, selected, onFile, onlyChanged }: { tree: Dir; selected: string | null; onFile: (path: string) => void; onlyChanged: boolean }) {
    const [open, setOpen] = useState<Set<string>>(() => new Set([tree.path]));
    // Folders holding a change open as the listing arrives.
    useEffect(() => {
        setOpen((prev) => {
            const next = new Set(prev);
            const walk = (d: Dir) => {
                if (changedIn(d) > 0) next.add(d.path);
                d.dirs.forEach(walk);
            };
            walk(tree);
            next.add(tree.path);
            return next;
        });
    }, [tree]);
    const toggle = (path: string) =>
        setOpen((prev) => {
            const next = new Set(prev);
            if (next.has(path)) next.delete(path);
            else next.add(path);
            return next;
        });
    const render = (d: Dir, depth: number, root: boolean): ReactNode => {
        if (onlyChanged && !changedIn(d)) return null;
        const isOpen = onlyChanged || open.has(d.path);
        return (
            <li key={d.path}>
                <button
                    type="button"
                    aria-expanded={isOpen}
                    onClick={() => toggle(d.path)}
                    className="flex w-full items-center gap-1.5 rounded-md py-1 pr-2 text-left transition-colors hover:bg-foreground/[0.04]"
                    style={{ paddingLeft: 6 + depth * 14 }}
                >
                    <ChevronRight className={cn('h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform', isOpen && 'rotate-90')} strokeWidth={2} />
                    {isOpen ? <FolderOpen className="h-4 w-4 shrink-0 text-muted-foreground" strokeWidth={1.75} /> : <Folder className="h-4 w-4 shrink-0 text-muted-foreground" strokeWidth={1.75} />}
                    <span className={cn('min-w-0 flex-1 truncate', root ? 'font-mono text-[12.5px] text-foreground/85' : 'text-[13.5px]')}>{d.name}</span>
                </button>
                {isOpen && (
                    <ul>
                        {d.dirs.map((x) => render(x, depth + 1, false))}
                        {d.files
                            .filter((f) => !onlyChanged || f.changed)
                            .map((f) => (
                                <li key={f.path}>
                                    <button
                                        type="button"
                                        onClick={() => onFile(f.path)}
                                        aria-current={selected === f.path ? 'true' : undefined}
                                        className={cn('flex w-full items-center gap-1.5 rounded-md py-1 pr-2 text-left text-[13.5px] transition-colors', selected === f.path ? 'bg-foreground/[0.08] text-foreground' : 'text-foreground/80 hover:bg-foreground/[0.04]')}
                                        style={{ paddingLeft: 6 + (depth + 1) * 14 + 18 }}
                                    >
                                        {f.secret ? <KeyRound className="h-3.5 w-3.5 shrink-0 text-muted-foreground" strokeWidth={1.75} /> : <File className="h-3.5 w-3.5 shrink-0 text-muted-foreground" strokeWidth={1.75} />}
                                        <span className="min-w-0 flex-1 truncate">{nameOf(f.path)}</span>
                                        <ChangeMark file={f} />
                                    </button>
                                </li>
                            ))}
                    </ul>
                )}
            </li>
        );
    };
    return <ul aria-label="Its files">{render(tree, 0, true)}</ul>;
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

/** One file: read in full, or the change the agent made to it. A secrets file shows its names and never a value. */
function FileView({ agentId, conversation, file, agentName }: { agentId: string; conversation: string; file: FileNode; agentName: string }) {
    const [view, setView] = useState<'file' | 'change'>(file.changed ? 'change' : 'file');
    const tooBig = (file.size ?? 0) > READ_LIMIT;
    const bytes = useWorkV1(tooBig || (view === 'change' && !file.secret) ? null : key(agentId, conversation, `read:${file.path}`), (c) => Agent.fromId(agentId, { client: c }).sandbox(conversation).read(file.path));
    const text = useMemo(() => (bytes.data ? new TextDecoder().decode(bytes.data) : null), [bytes.data]);
    const binary = !!text && text.includes('\u0000');
    const shownView = file.changed && !file.secret ? view : 'file';
    const download = async (data: Uint8Array) => {
        const url = URL.createObjectURL(new Blob([data as BlobPart]));
        const a = document.createElement('a');
        a.href = url;
        a.download = nameOf(file.path);
        a.click();
        URL.revokeObjectURL(url);
    };
    const note = file.changed ? `${file.changed.how === 'added' ? 'Added' : 'Changed'} by ${agentName} in this session` : file.secret ? 'Secrets: names only' : sizeText(file.size);
    return (
        <div className="flex min-h-0 flex-1 flex-col" data-testid="file-view">
            <div className={cn('flex shrink-0 items-center gap-2 border-b px-4 py-2', HAIRLINE)}>
                <div className="min-w-0 flex-1">
                    <p className="truncate font-mono text-[12.5px] text-foreground/85">{file.path}</p>
                    <p className="truncate text-[12px] text-muted-foreground">{note}</p>
                </div>
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
                {!file.secret && (
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
            </div>
            <div className="min-h-0 flex-1 overflow-auto scrollbar-subtle">
                {file.secret ? (
                    <div className="px-5 py-4">
                        <ul>
                            {secretNames(text ?? '').map((n) => (
                                <li key={n} className={cn('flex items-center gap-3 border-b py-2.5', HAIRLINE)}>
                                    <KeyRound className="h-4 w-4 shrink-0 text-muted-foreground" strokeWidth={1.75} />
                                    <span className="min-w-0 flex-1 truncate font-mono text-[13px]">{n}</span>
                                    <span className="shrink-0 text-[12.5px] text-muted-foreground">Value hidden</span>
                                </li>
                            ))}
                        </ul>
                        <p className="mt-3 text-[12.5px] leading-snug text-muted-foreground">Secret values never show here, to you or to anyone in the space.</p>
                    </div>
                ) : shownView === 'change' ? (
                    <div className="p-3">
                        <DiffView patch={file.changed!.patch} path={file.path} />
                    </div>
                ) : tooBig ? (
                    <p className="p-6 text-[13.5px] text-muted-foreground">{sizeText(file.size)}: too big to show here.</p>
                ) : bytes.error !== undefined ? (
                    <p className="p-6 text-[13.5px] text-muted-foreground">Couldn’t read it: {bytes.error instanceof Error ? bytes.error.message : String(bytes.error)}</p>
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
