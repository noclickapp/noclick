// An agent in Work: one terminal window with Claude, t3code's CLI chat on NoClick's tokens, showing the agent's one
// session, which everyone talking to it shares. Its header (the agent, its session menu: clear for everyone, resume an
// earlier session; the harness it runs on and its machine), its one timeline (your messages as bubbles, every chat's,
// channel's and visitor's turns each named by where it came from, its replies as plain text, each turn's work as its
// activity log, what its harness asks you answered in place) and the box, with a turn's changed files opening beside
// it. Everything reads and writes through the platform client Work is given (useWorkClient), live through the
// session's own event stream.
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { toast } from 'sonner';
import { ChevronDown, ChevronRight, ClipboardCopy, MoreHorizontal, PanelRightClose, RotateCcw, SquarePen } from 'lucide-react';
import { Operation, type AgentStepDiff, type HarnessRequest } from 'noclick';
import { RepliedOn } from '@/ui/chat/channels';
import { BUTTON_GHOST, BUTTON_PRIMARY, BUTTON_SECONDARY } from '@/ui/buttons';
import { MemberAvatar } from '@/screens/channels/avatars';
import type { ChannelMember } from '@/screens/channels/types';
import { MENU_SURFACE } from '@/ui/menus';
import { useInPhoneShell } from '@/ui/phoneBar';
import { ShellDialog } from '@/ui/ShellDialog';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuRadioGroup, DropdownMenuRadioItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/ui/dropdown-menu';
import { ShortcutTooltip } from '@/ui/ShortcutTooltip';
import { cn } from '@/ui/utils';
import { AgentRing, WorkMotion } from '../agents/AgentRing';
import { HarnessMark, harnessLabel, harnessName } from '../agents/harness';
import { nameOf, roleOf, useAgentFaces, useAgents, useSpaceNoClicks } from '../agents/reads';
import { renamable, useRenameAgent } from '../agents/rename';
import { useWorkViewer, wroteIt } from '../viewer';
import { useWorkNav } from '../nav';
import { useWorkClient } from '../client';
import { doing, Elapsed, TOOL_CALL_MODES, type ToolCalls } from './Activity';
import { ConnectSend } from '../newAgent/ConnectSend';
import { PickerSheetHost, usePickerSheets } from '../newAgent/ModelPicker';
import { useConversationAccount } from './account';
import { accountFiles, Composer } from './Composer';
import { CONTROL_NAMES, type Control, type Mentionable } from './menus';
import { ModelControl } from './ModelControl';
import { ChangesPanel, ContextPanel, HelpPanel, RenamePanel, UsagePanel } from './Panels';
import { ConversationIntro } from './Rows';
import { CONVERSATION_CSS, ICON_BUTTON, LANE } from './styles';
import { ConversationFooter } from './footer';
import { MachineChip } from '../profile/facts';
import { useAgentChannels } from '../profile/reads';
import { changedFiles, flatSteps, isSubagentCall, liveTurn, pendingRequests, stepsOf, subagentsOf, type Entry, type Step, type Thread, type TurnEntry, type UserEntry } from '@/lib/agentThread/thread';
import { useConversation } from './useConversation';
import { STOP_FIRST, useSessionControls } from './sessionControls';
import { cameByOf, repliedOn, SourceChip, viaBubble } from './sources';
import { BesideCard, BesideLog, BesidePill, BesideRail, CARD_MIN_PANE, cardReserve, ConversationFacts, MIN_COLUMN, RAIL_ROOM, RailPanel, RailSheet, StopBeside, useFresh, type RowLook, type SaidTo } from './Beside';
import { SubagentBox } from './SubagentBox';
import { isLive, type BesideItem } from './besideItems';
import { BrowserMotion } from '../browser/pieces';
import { ConversationBrowserView } from '../browser/BrowserView';
import { ConversationBrowserProvider, useConversationBrowser } from '../browser/useConversationBrowser';
import { useBeside } from './useBeside';
import { useLoops } from './useLoops';
import { runLoop } from './loops';
import { ThreadCards } from './cards';
import { timelineRows, useToolCalls } from './Timeline';
import { ToolsDrawer } from '../tools/ToolsPanel';

export interface AgentConversationProps {
    agentId: string;
    /** Its session, the one everyone talking to it shares now. */
    conversation: string;
    onOpenProfile(): void;
    onOpenMachine(): void;
    /** Where it opens beside another page (the Chat page's side column): its header ends in Close. */
    onClose?(): void;
}

/** Follows the newest row while you're at the bottom; stays where you are once you scroll up. */
function useStuckToEnd(deps: unknown) {
    const ref = useRef<HTMLDivElement>(null);
    const stuck = useRef(true);
    useLayoutEffect(() => {
        const el = ref.current;
        if (el && stuck.current) el.scrollTop = el.scrollHeight;
    }, [deps]);
    const onScroll = () => {
        const el = ref.current;
        if (el) stuck.current = el.scrollHeight - el.scrollTop - el.clientHeight < 48;
    };
    return { ref, onScroll };
}

/** An element's width, as it changes. */
function useWidth() {
    const ref = useRef<HTMLDivElement>(null);
    const [width, setWidth] = useState(0);
    useLayoutEffect(() => {
        const el = ref.current;
        if (!el) return;
        setWidth(el.getBoundingClientRect().width);
        if (typeof ResizeObserver === 'undefined') return;
        const watch = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
        watch.observe(el);
        return () => watch.disconnect();
    }, []);
    return { ref, width };
}

/** The reading lane's widest text (46rem less its padding). */
const LANE_TEXT_PX = 696;
/** The narrowest column whose header has room for the harness's name and the machine's state. */
const TIGHT_PANE = 720;

/** The session as Markdown, for copying out. */
function asMarkdown(title: string, entries: Entry[]): string {
    const lines = [`# ${title}`, ''];
    for (const e of entries) {
        if (e.kind === 'user') lines.push(`**${e.author?.name ?? 'You'}**`, '', e.command ? `/${e.command.name} ${e.command.arguments ?? ''}`.trim() : e.text, '');
        else if (e.kind === 'turn') {
            for (const s of stepsOf(e)) lines.push(`> ${s.kind === 'command' ? `$ ${s.command}` : `${s.kind} ${s.path ?? s.query ?? s.tool}`}`);
            if (e.reply) lines.push('', e.reply, '');
        } else if (e.kind === 'note') lines.push(`_${e.text}_`, '');
    }
    return lines.join('\n');
}

type Beside = { kind: 'changes'; turn: string } | null;
type Drawer = 'usage' | 'context' | 'tools' | 'help' | 'rename' | null;
// A NoClick, and an agent built in the app, keep their names: their / has no /rename.
const KEPT_NAME_CONTROLS = CONTROL_NAMES.filter((c) => c !== 'rename');
const MENU_ROW = 'gap-2.5 rounded-xl px-2.5 py-2 text-sm';

export function AgentConversation({ agentId, conversation, onOpenProfile, onOpenMachine, onClose }: AgentConversationProps) {
    const c = useConversation(agentId, conversation);
    const { agent, thread } = c;
    const viewer = useWorkViewer();
    const nav = useWorkNav();
    const workClient = useWorkClient();
    const inPhone = useInPhoneShell();
    // A phone opens the model and account pickers as sheets over the page.
    const sheets = usePickerSheets(inPhone);
    const mine = (e: UserEntry) => wroteIt(e.author, viewer);
    const faces = useAgentFaces();
    const { data: agents } = useAgents();
    const noclicks = useSpaceNoClicks();
    const [mode, setMode] = useToolCalls();
    const [beside, setBeside] = useState<Beside>(null);
    const [drawer, setDrawer] = useState<Drawer>(null);
    // What /rename's drawer opens with: a name /rename was refused, and why.
    const [renameDraft, setRenameDraft] = useState<{ draft: string; error: string } | null>(null);
    const rename = useRenameAgent();
    const [picker, setPicker] = useState(false);
    const [putBack, setPutBack] = useState<{ text: string; n: number; subagent?: string } | undefined>();
    const [reverting, setReverting] = useState<UserEntry | null>(null);
    // What works beside it: the card (or its pill), the rail it grows into, the subagent whose log the pane shows.
    const pane = useWidth();
    const [rail, setRail] = useState(false);
    const [picked, setPicked] = useState<string | null>(null);
    const [stopping, setStopping] = useState<BesideItem | null>(null);

    useEffect(() => {
        if (!c.error) return;
        toast(c.error);
        c.clearError();
    }, [c.error]); // eslint-disable-line react-hooks/exhaustive-deps

    useEffect(() => {
        setBeside(null);
        setDrawer(null);
        setRail(false);
        setPicked(null);
    }, [agentId, conversation]);

    const live = liveTurn(thread);
    const requests = pendingRequests(thread);
    // The browser it works in, read once for the card's tile, the turns' cards and the big view.
    const browser = useConversationBrowser(agentId, conversation, c.ready ? agent.name : 'The agent');
    const besideOwn = useBeside(thread, requests, browser?.browser ?? null);
    const loops = useLoops(agentId, conversation, live?.operationId ?? null);
    const besideItems = useMemo(() => [...besideOwn, ...loops], [besideOwn, loops]);
    const besideFresh = useFresh(besideItems);
    const face: ChannelMember = faces.get(agentId) ?? { id: agentId, kind: 'agent', name: c.ready ? agent.name : '', agentId };
    const ring = requests.length ? 'needs' : live ? 'working' : 'idle';
    const harness = c.ready ? agent.harness : null;
    // The account it runs on, checked as it opens: Send asks to connect it again while it can't run a turn.
    const account = useConversationAccount(
        { harness: c.settings?.harness ?? harness, model: c.settings?.model ?? (c.ready ? agent.model : null), connection: c.settings?.modelConnection ?? null },
        (id) => void c.updateSettings({ modelConnection: id }),
        c.rereadSettings
    );
    const controls = useSessionControls(agent, agentId, face.name || 'It', !!live);
    const session = controls.sessions?.all.find((x) => x.conversation === conversation);
    // Named where it has a title; its first words name it only among the others (the resume list).
    const titleShown = c.settings?.title ?? session?.title ?? 'This session';
    const channels = useAgentChannels(agentId);
    const cameBy = useMemo(() => cameByOf(thread), [thread]);
    // What its rows draw: the thread, and what came in on its triggered turns (a reply lands there, not in the thread).
    const drawn = useMemo(() => ({ thread, activity: c.activity.byTurn, ready: c.ready }), [thread, c.activity.byTurn, c.ready]);
    const { ref: scrollRef, onScroll } = useStuckToEnd(drawn);
    // The line above the box shows its subagents: the log goes to the first at work, which lights up a moment.
    const showSubagents = () => {
        const first = subagentsOf(thread)[0];
        const el = first ? [...(scrollRef.current?.querySelectorAll<HTMLElement>('[data-subagent]') ?? [])].find((x) => x.dataset.subagent === first.id) : undefined;
        if (!el) return;
        const still = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
        el.scrollIntoView({ block: 'center', behavior: still ? 'auto' : 'smooth' });
        if (!still) el.animate?.([{ backgroundColor: 'hsl(var(--foreground) / 0.08)' }, { backgroundColor: 'transparent' }], { duration: 1400, easing: 'ease-out' });
    };

    const share = (text: string) => setPutBack((p) => ({ text, n: (p?.n ?? 0) + 1 }));

    const runControl = async (control: Control, args = '') => {
        if (control === 'loop') await runLoop(agent.conversation(conversation), args, face.name || 'It');
        else if (control === 'clear') controls.clear();
        else if (control === 'resume') controls.resume();
        else if (control === 'model' || control === 'effort') setPicker(true);
        else if (control === 'usage' || control === 'context' || control === 'tools' || control === 'help') setDrawer(control);
        else if (control === 'rename') {
            const next = args.trim();
            if (!next) return openRename(null);
            if (next === face.name) return void toast(`It’s already called ${next}`);
            const refused = await rename(agentId, next);
            if (refused) openRename({ draft: next, error: refused });
            else await renamed(next);
        }
    };

    const openRename = (draft: { draft: string; error: string } | null) => {
        setRenameDraft(draft);
        setDrawer('rename');
    };
    // Said in the session as it's kept, so everyone reading it (and the agent, at its next turn) sees the new name.
    const renamed = async (name: string) => {
        try {
            await agent.note(conversation, `Renamed to ${name}`, { data: { renamed_to: name } });
        } catch (e) {
            toast(`Renamed to ${name}`, { description: `The line saying so in this session didn’t save: ${e instanceof Error ? e.message : String(e)}` });
        }
    };

    const revert = async (entry: UserEntry, files: boolean) => {
        setReverting(null);
        if (!entry.id) return;
        try {
            const back = await agent.conversation(conversation).revert(entry.id, { files });
            share(back.text);
            c.retry();
            // Its files are in its sandbox, so their changes are undone there before its next turn.
            const undone = back.files.restored.length ? `${back.files.restored.length} ${back.files.restored.length === 1 ? 'file is' : 'files are'} put back before its next turn.` : '';
            const left = back.files.notRestored.map((f) => `${f.path}: ${f.why}`);
            const commands = back.files.commandsNotUndone ? `What ${back.files.commandsNotUndone} ${back.files.commandsNotUndone === 1 ? 'command' : 'commands'} changed stays: no diff records it.` : '';
            const said = [undone, ...left, commands].filter(Boolean).join('\n');
            if (said) toast(left.length ? 'Some files can’t be put back' : 'Back to before your message', { description: said });
        } catch (e) {
            toast(e instanceof Error ? e.message : 'It didn’t go back.');
        }
    };

    const mentionables = async (): Promise<Mentionable[]> => {
        // Its files, where the client reaches its sandbox; @ still offers agents and people without them.
        const files = await agent
            .sandbox(conversation)
            .files('/workspace', { recursive: true, limit: 200 })
            .catch((e: unknown) => {
                console.warn('[work] its files didn’t read for @:', e);
                return [];
            });
        const people = new Map<string, string>();
        for (const e of thread.entries) if (e.kind === 'user' && e.author && (e.author.type === 'user' || e.author.type === 'account') && !mine(e)) people.set(e.author.name, e.author.name);
        for (const conv of controls.sessions?.all ?? []) for (const p of conv.people) if (p.name && !wroteIt({ type: p.type, id: p.id, name: p.name }, viewer)) people.set(p.name, p.name);
        return [
            ...files.map((f) => ({ kind: f.type === 'directory' ? ('folder' as const) : ('file' as const), name: f.path.slice(f.path.lastIndexOf('/') + 1) + (f.type === 'directory' ? '/' : ''), detail: f.path, text: f.path })),
            // Under its name now, found by the names it went by too.
            ...(agents ?? []).filter((a) => a.id !== agentId).map((a) => ({ kind: 'agent' as const, name: nameOf(a, noclicks), detail: roleOf(a, noclicks) ?? undefined, text: a.name, aliases: a.formerNames })),
            ...[...people.keys()].map((name) => ({ kind: 'person' as const, name, text: name })),
        ];
    };

    const canCompact = !!c.commands?.commands.some((x) => x.name === 'compact');
    const drawerEl =
        drawer === 'usage' ? (
            <UsagePanel agent={agent} conversation={conversation} onClose={() => setDrawer(null)} />
        ) : drawer === 'context' ? (
            <ContextPanel
                agent={agent}
                conversation={conversation}
                canCompact={canCompact}
                working={!!live}
                onCompact={() => {
                    setDrawer(null);
                    void c.send({ text: '', command: { name: 'compact' } });
                }}
                onClose={() => setDrawer(null)}
            />
        ) : drawer === 'tools' ? (
            <ToolsDrawer agent={agent} name={face.name || 'It'} conversation={conversation} onClose={() => setDrawer(null)} />
        ) : drawer === 'help' ? (
            <HelpPanel onClose={() => setDrawer(null)} />
        ) : drawer === 'rename' ? (
            <RenamePanel
                name={face.name}
                draft={renameDraft?.draft}
                error={renameDraft?.error}
                onClose={() => setDrawer(null)}
                onSave={async (name) => {
                    const refused = await rename(agentId, name);
                    if (refused) return refused;
                    setDrawer(null);
                    await renamed(name);
                    return null;
                }}
            />
        ) : null;

    const changesOf = (key: string): AgentStepDiff[] => {
        const turn = thread.entries.find((e): e is TurnEntry => e.kind === 'turn' && e.key === key);
        return turn ? changedFiles(turn) : [];
    };

    const rows = timelineRows({
        thread,
        mode,
        mine,
        agentName: face.name || 'It',
        onAnswer: (r, d) => void c.answer(r, d),
        renderUser: viaBubble,
        source: (e) => <SourceChip chat={e.chat} channelName={(id) => channels.data?.find((x) => x.id === id)?.name ?? null} onOpenChannel={nav.openChannel} />,
        afterReply: (turn) => {
            const app = repliedOn(turn, cameBy);
            return app && <RepliedOn app={app} />;
        },
        onChanges: (e) => setBeside({ kind: 'changes', turn: e.key }),
        onRewind: (u) => setReverting(u),
        onReconnect: (f) => account.reconnect(f),
        onTrigger: (e) => nav.openProfile(agentId, { tab: 'triggers', trigger: e.trigger!.id }),
        onProfile: () => nav.openProfile(agentId),
        chats: { activity: c.activity, agent: { name: face.name || 'It', face } },
    });

    const fact = 'inline-flex h-7 min-w-0 shrink-0 items-center gap-1.5 rounded-full px-2 text-xs max-md:h-10 text-muted-foreground transition-colors hover:bg-foreground/[0.04] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/70';
    const status = requests.length ? 'Waiting on you' : live ? (lineOf(live) ?? 'Working') : '';

    // The card floats over the pane's top right from CARD_MIN_PANE, the lane keeping its text clear of it; below that a
    // pill in the header, and on a phone its rail is a sheet.
    const cardFits = !inPhone && pane.width >= CARD_MIN_PANE;
    const besideShown = c.ready && besideItems.length > 0;
    const pickedItem = besideItems.find((b) => b.id === picked && b.kind === 'subagent') ?? null;
    const railOpen = rail && besideShown && !inPhone;
    const sheetOpen = rail && besideShown && inPhone;
    const railBeside = railOpen && pane.width - RAIL_ROOM >= MIN_COLUMN;
    // A column this narrow (the rail takes its room) keeps the header on one line: the harness as its mark, the
    // machine without its state.
    const tight = pane.width - (railBeside ? RAIL_ROOM : 0) < TIGHT_PANE;
    const allChanges = (() => {
        const byPath = new Map<string, AgentStepDiff>();
        for (const e of thread.entries) if (e.kind === 'turn') for (const d of changedFiles(e)) byPath.set(d.path, d);
        return [...byPath.values()];
    })();
    const facts = c.ready ? <ConversationFacts agent={agent} conversation={conversation} changes={allChanges} /> : null;
    const look = (b: BesideItem): RowLook =>
        b.kind === 'agent'
            ? { face: faces.get(b.id) ?? { id: b.id, kind: 'agent', name: b.agent?.name ?? 'An agent', agentId: b.id }, harness: null, runsOn: agents?.find((a) => a.id === b.id)?.model ?? null }
            : b.kind === 'loop'
              ? { harness: null, runsOn: null }
              : { harness, runsOn: harness ? `${harnessLabel(harness)} subagent` : null };
    // A NoClick agent's task stops on its own, and a loop; a harness subagent only with the turn that started it, while
    // it runs.
    const stoppable = (b: BesideItem) => isLive(b) && (b.kind === 'agent' ? !!b.agent?.jobId : b.kind === 'loop' || b.turnRunning);
    const pickBeside = (b: BesideItem | null) => {
        if (b?.kind === 'loop') return; // its runs are this session's turns
        // Where the rail covers the timeline, a row's log takes the pane from it.
        if (inPhone || !railBeside) setRail(false);
        if (b?.kind === 'agent') return nav.openAgent(b.id);
        setPicked(b?.id ?? null);
    };
    const stopBeside = async (b: BesideItem) => {
        setStopping(null);
        try {
            if (b.kind === 'agent' && b.agent?.jobId) await Operation.fromId(b.agent.jobId, { client: workClient }).cancel();
            else if (b.loop) await b.loop.wakeup.cancel();
            else await c.stop();
            toast(b.kind === 'agent' ? `Stopped ${b.agent?.name ?? 'it'}’s task` : b.loop ? 'Stopped the loop' : 'Stopped the turn');
        } catch (error) {
            toast('Couldn’t stop it', { description: error instanceof Error ? error.message : String(error) });
        }
    };
    // The subagent whose log the pane shows: what it asks you, and what you wrote it.
    const pickedRequests = pickedItem?.call ? requestsWithin(pickedItem.call, requests) : [];
    const pickedSaid = pickedItem ? saidTo(thread, pickedItem.id) : [];
    const askMainAbout = (item: BesideItem) => {
        setPicked(null);
        setPutBack((p) => ({ text: '', n: (p?.n ?? 0) + 1, subagent: item.title }));
    };
    const cardShown = besideShown && cardFits && !railOpen && !pickedItem;
    const reserve = cardShown ? { paddingRight: cardReserve(pane.width, LANE_TEXT_PX) } : undefined;
    const railProps = { items: besideItems, facts, face, look, selected: pickedItem?.id ?? null, onSelect: pickBeside, stoppable, onStop: setStopping, fresh: besideFresh, ...(loops.length ? { title: 'Beside it' } : {}) };

    return (
        <ConversationBrowserProvider value={browser}>
        <PickerSheetHost.Provider value={sheets.host}>
        <div ref={pane.ref} className="relative flex min-h-0 min-w-0 flex-1 bg-background" data-testid="agent-conversation">
            <WorkMotion />
            <BrowserMotion />
            <ConversationBrowserView />
            <style>{CONVERSATION_CSS}</style>
            {/* The timeline steps left for the open rail, where the pane keeps it a column beside it. */}
            <div className="flex min-h-0 min-w-0 flex-1 flex-col transition-[padding] duration-300 motion-reduce:transition-none" style={railBeside ? { paddingRight: RAIL_ROOM } : undefined}>
                {pickedItem ? (
                    <BesideLog
                        item={pickedItem}
                        face={face}
                        harness={harness}
                        said={pickedSaid}
                        requests={pickedRequests}
                        onAnswer={(r, d) => void c.answer(r, d)}
                        onBack={() => setPicked(null)}
                        onStop={stoppable(pickedItem) ? () => setStopping(pickedItem) : undefined}
                    />
                ) : (
                    <>
                        <header className="flex h-12 shrink-0 items-center gap-2 pl-4 pr-3">
                            <button type="button" onClick={onOpenProfile} aria-label={`${face.name || 'Agent'}’s profile`} className="-ml-1.5 flex min-w-0 shrink-0 items-center gap-2 rounded-full px-1.5 py-1 max-md:py-2 text-left transition-colors hover:bg-foreground/[0.04] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/70">
                                <AgentRing member={face} status={ring} size={24} />
                                {/* The phone's top bar already names it. */}
                                {!inPhone && <span className="shrink-0 text-sm font-medium">{face.name}</span>}
                            </button>
                            <DropdownMenu>
                                <DropdownMenuTrigger aria-label="Its session" className="flex min-w-0 items-center gap-1 rounded-full px-1.5 py-1 max-md:py-2.5 text-sm text-muted-foreground transition-colors hover:bg-foreground/[0.04] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/70 data-[state=open]:bg-foreground/[0.06]">
                                    {!inPhone && (
                                        <span aria-hidden className="text-muted-foreground/50">
                                            /
                                        </span>
                                    )}
                                    <span className="min-w-0 max-w-[14rem] truncate">{titleShown}</span>
                                    <ChevronDown className="h-3.5 w-3.5 shrink-0" strokeWidth={2} />
                                </DropdownMenuTrigger>
                                <DropdownMenuContent align="start" sideOffset={6} className={cn('work-rise w-[300px] rounded-2xl p-1.5', MENU_SURFACE)}>
                                    <DropdownMenuLabel className="px-2.5 pb-1 pt-1 text-xs font-normal text-muted-foreground">One session, shared by everyone talking to {face.name || 'it'}</DropdownMenuLabel>
                                    <DropdownMenuItem disabled={!!live} onSelect={controls.clear} className={MENU_ROW}>
                                        <SquarePen className="h-4 w-4 shrink-0 text-muted-foreground" strokeWidth={2} />
                                        <span className="min-w-0 flex-1">Clear for everyone…</span>
                                        {live && <span className="shrink-0 text-xs text-muted-foreground">{STOP_FIRST}</span>}
                                    </DropdownMenuItem>
                                    <DropdownMenuItem disabled={!!live} onSelect={controls.resume} className={MENU_ROW}>
                                        <RotateCcw className="h-4 w-4 shrink-0 text-muted-foreground" strokeWidth={2} />
                                        <span className="min-w-0 flex-1">Resume an earlier session</span>
                                        {live ? <span className="shrink-0 text-xs text-muted-foreground">{STOP_FIRST}</span> : <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" strokeWidth={2} />}
                                    </DropdownMenuItem>
                                </DropdownMenuContent>
                            </DropdownMenu>
                            <span data-testid="turn-status" className={cn('hidden min-w-0 flex-1 truncate text-xs lg:block', requests.length ? 'text-foreground' : 'text-muted-foreground')}>
                                {status}
                                {live && !requests.length && (
                                    <>
                                        {' · '}
                                        <Elapsed from={live.startedAt} />
                                    </>
                                )}
                            </span>
                            <div className="ml-auto flex shrink-0 items-center">
                                {besideShown && !cardFits && !railOpen && (
                                    <span className="mr-1">
                                        <BesidePill agentId={agentId} conversation={conversation} items={besideItems} facts={facts} phone={inPhone} onOpenRail={() => setRail(true)} />
                                    </span>
                                )}
                                {harness && (
                                    <ShortcutTooltip label={`Runs on ${harnessName(harness)}. Pick another harness or model.`}>
                                        <button type="button" onClick={() => setPicker(true)} aria-label={`Runs on ${harnessName(harness)}`} className={cn(fact, 'hidden sm:inline-flex')}>
                                            <HarnessMark harness={harness} className="h-3.5 w-3.5" />
                                            {!tight && harnessLabel(harness)}
                                        </button>
                                    </ShortcutTooltip>
                                )}
                                {/* Once its own fields are in: until then it isn't known whether it has a machine. */}
                                {c.ready && (
                                    <span className="ml-1">
                                        <MachineChip agent={agent} conversation={conversation} onOpen={onOpenMachine} short={tight} />
                                    </span>
                                )}
                                <span aria-hidden className="mx-1.5 hidden h-4 w-px bg-border dark:bg-foreground/[0.1] sm:block" />
                                <DropdownMenu>
                                    <DropdownMenuTrigger aria-label="More" className={cn(ICON_BUTTON, 'max-md:h-10 max-md:w-10')}>
                                        <MoreHorizontal className="h-4 w-4" />
                                    </DropdownMenuTrigger>
                                    <DropdownMenuContent align="end" sideOffset={8} className={cn('work-rise w-[280px] rounded-2xl p-1.5', MENU_SURFACE)}>
                                        <DropdownMenuLabel className="px-2.5 pb-1 pt-1.5 text-xs font-medium text-muted-foreground">Tool calls in chat</DropdownMenuLabel>
                                        <DropdownMenuRadioGroup value={mode} onValueChange={(v) => setMode(v as ToolCalls)}>
                                            {TOOL_CALL_MODES.map((m) => (
                                                <DropdownMenuRadioItem key={m.id} value={m.id} className="items-start rounded-xl py-2 pr-2.5 text-sm">
                                                    <span>
                                                        <span className="block">{m.label}</span>
                                                        <span className="block text-xs text-muted-foreground">{m.note}</span>
                                                    </span>
                                                </DropdownMenuRadioItem>
                                            ))}
                                        </DropdownMenuRadioGroup>
                                        <DropdownMenuSeparator className="-mx-1.5 my-1.5 bg-border dark:bg-foreground/[0.08]" />
                                        <DropdownMenuItem
                                            onSelect={() =>
                                                navigator.clipboard.writeText(asMarkdown(`${face.name}: ${titleShown}`, thread.entries)).then(
                                                    () => toast('Copied as Markdown'),
                                                    () => toast('Couldn’t copy the session', { description: 'The browser refused the clipboard.' })
                                                )
                                            }
                                            className="gap-2.5 rounded-xl px-2.5 py-2 text-sm"
                                        >
                                            <ClipboardCopy className="h-4 w-4 text-muted-foreground" strokeWidth={2} />
                                            Copy as Markdown
                                        </DropdownMenuItem>
                                    </DropdownMenuContent>
                                </DropdownMenu>
                                {onClose && (
                                    <button type="button" onClick={onClose} aria-label="Close" className={cn(ICON_BUTTON, 'ml-0.5')}>
                                        <PanelRightClose className="h-4 w-4" />
                                    </button>
                                )}
                            </div>
                        </header>
                        <div ref={scrollRef} onScroll={onScroll} className="relative min-h-0 flex-1 overflow-y-auto scrollbar-subtle" style={reserve} data-testid="timeline">
                            <div className={cn(LANE, 'flex min-h-full flex-col justify-end px-5 pb-2')}>
                                {c.loadError ? (
                                    <div className="py-16 text-center text-sm text-muted-foreground">
                                        <p>{c.loadError}</p>
                                        <button type="button" onClick={c.retry} className={cn(BUTTON_SECONDARY, 'mt-3')}>
                                            Try again
                                        </button>
                                    </div>
                                ) : !c.ready ? (
                                    <div className="space-y-2 py-10" aria-label="Loading the session">
                                        <div className="h-2.5 w-2/5 animate-pulse rounded-full bg-foreground/[0.06]" />
                                        <div className="h-2.5 w-3/5 animate-pulse rounded-full bg-foreground/[0.06]" />
                                        <div className="h-2.5 w-1/3 animate-pulse rounded-full bg-foreground/[0.06]" />
                                    </div>
                                ) : (
                                    <>
                                        <ConversationIntro face={<MemberAvatar member={face} size={48} />} name={face.name} line={introLine(roleOf(agent, noclicks), harness ? harnessName(harness) : 'An agent', agent.model)}>
                                            {!thread.entries.length && <p className="mt-6 text-sm text-muted-foreground">Send a message to start.</p>}
                                        </ConversationIntro>
                                        <ThreadCards thread={thread} follow={c.followJobs}>
                                            {rows}
                                        </ThreadCards>
                                    </>
                                )}
                            </div>
                        </div>
                    </>
                )}
                {/* The box keeps the lane's edges, clear of the card as the timeline is. A subagent's log has its own,
                    main's kept (with what you were writing there) for when you go back. */}
                {pickedItem && (
                    <SubagentBox
                        item={pickedItem}
                        mainName={face.name || 'main'}
                        harness={harness}
                        requests={pickedRequests}
                        mentionables={mentionables}
                        onTell={c.tellSubagent}
                        onAnswer={(r, d, o) => void c.answer(r, d, o)}
                        onAskMain={() => askMainAbout(pickedItem)}
                    />
                )}
                <div style={reserve} hidden={!!pickedItem}>
                    <Composer
                        key={`${agentId}:${conversation}`}
                        footer={c.ready ? <ConversationFooter agent={agent} chip={account.chip} /> : null}
                        agentName={face.name || 'it'}
                        harnessLabel={harness ? harnessLabel(harness) : 'Its harness'}
                        working={!!live}
                        ready={c.ready}
                        commands={c.commands}
                        queued={c.queued}
                        requests={requests}
                        subagents={subagentsOf(thread)}
                        onShowSubagents={showSubagents}
                        mentionables={mentionables}
                        controls={c.ready && renamable(agent) ? undefined : KEPT_NAME_CONTROLS}
                        listFiles={(query) => accountFiles(workClient, query)}
                        session={controls.menu}
                        model={<ModelControl agent={c.ready ? agent : null} harness={harness} model={c.ready ? agent.model : null} settings={c.settings} open={picker} onOpenChange={setPicker} onChange={(patch) => void c.updateSettings(patch)} onMoved={c.rereadSettings} fundsOwner={`conversation:${agentId}:${conversation}`} />}
                        ask={account.ask ? { button: <ConnectSend ask={account.ask} onClick={() => account.reconnect()} />, open: () => account.reconnect() } : null}
                        onControl={(control, args) => void runControl(control, args)}
                        drawer={drawerEl}
                        onSend={c.send}
                        onStop={() => void c.stop()}
                        onUnqueue={c.unqueue}
                        onAnswer={(r, d, o) => void c.answer(r, d, o)}
                        upload={(file) => agent.upload(file)}
                        putBack={putBack}
                    />
                </div>
            </div>
            {cardShown && <BesideCard facts={facts} items={besideItems} onOpen={() => setRail(true)} />}
            {railOpen && (
                <RailPanel>
                    <BesideRail {...railProps} onClose={() => setRail(false)} />
                </RailPanel>
            )}
            {sheetOpen && (
                <RailSheet onClose={() => setRail(false)}>
                    <BesideRail {...railProps} phone />
                </RailSheet>
            )}
            <StopBeside item={stopping} onClose={() => setStopping(null)} onStop={(b) => void stopBeside(b)} />
            {beside?.kind === 'changes' && <ChangesPanel agentName={face.name} files={changesOf(beside.turn)} onClose={() => setBeside(null)} />}
            {account.dialog}
            {reverting && (
                <ShellDialog
                    open
                    onOpenChange={(o) => !o && setReverting(null)}
                    title="Edit from here"
                    description={`${face.name} goes back to before this message, and your message returns to the box to change and send again.`}
                    mark={<RotateCcw className="h-5 w-5" strokeWidth={2} />}
                    footer={
                        <>
                            <button type="button" onClick={() => setReverting(null)} className={BUTTON_GHOST}>
                                Cancel
                            </button>
                            <button type="button" onClick={() => void revert(reverting, true)} className={BUTTON_SECONDARY}>
                                Undo file changes too
                            </button>
                            <button type="button" onClick={() => void revert(reverting, false)} className={BUTTON_PRIMARY}>
                                Keep its file changes
                            </button>
                        </>
                    }
                />
            )}
            {controls.dialogs}
            {c.fundsDialog}
            {sheets.layer}
        </div>
        </PickerSheetHost.Provider>
        </ConversationBrowserProvider>
    );
}

/** What a subagent's call (and the steps under it) asked a person: its harness names the step it asks from. */
function requestsWithin(call: Step, requests: readonly HarnessRequest[]): HarnessRequest[] {
    const ids = new Set(flatSteps([call]).map((s) => s.id));
    return requests.filter((r) => typeof r.raw.call_id === 'string' && ids.has(r.raw.call_id));
}

/** What the person wrote subagent `id`, wherever the thread holds it (in the turn it joined, or on its own), each read
 *  once the turn that took it is over. */
function saidTo(thread: Thread, id: string): SaidTo[] {
    const ended = new Set(thread.entries.flatMap((e) => (e.kind === 'turn' && e.status !== 'running' && e.operationId ? [e.operationId] : [])));
    const out: SaidTo[] = [];
    for (const e of thread.entries) {
        if (e.kind === 'user' && e.subagent?.id === id) out.push({ entry: e, read: !!e.operationId && ended.has(e.operationId) });
        if (e.kind === 'turn')
            for (const p of e.parts) if (p.kind === 'user' && p.entry.subagent?.id === id) out.push({ entry: p.entry, read: e.status !== 'running' });
    }
    return out;
}

/** Under its name where the conversation starts: its job (ended once, whether or not it ends itself), else what it
 *  runs on. */
export function introLine(role: string | null, runsOn: string, model: string | null): string {
    if (role) return /[.!?…]$/.test(role) ? role : `${role}.`;
    return `${runsOn}${model ? ` on ${model}` : ''}.`;
}

/** What the turn under way is doing, in a line: its running step, else what it's working on. */
function lineOf(turn: TurnEntry): string | null {
    const running = [...stepsOf(turn)].reverse().find((s) => s.running);
    if (!running) return 'Working';
    if (isSubagentCall(running)) {
        const n = stepsOf(turn).filter((s) => s.running && isSubagentCall(s)).length;
        return n === 1 ? 'Running a subagent' : `Running ${n} subagents`;
    }
    // A harness's step as the platform said it ("Running the plan usage tests").
    if (running.label) return running.label.text;
    if (running.kind === 'command') return `Running ${running.command ?? 'a command'}`;
    if (running.kind === 'edit') return `Editing ${running.path?.split('/').pop() ?? 'a file'}`;
    if (running.kind === 'read') return `Reading ${running.path?.split('/').pop() ?? 'a file'}`;
    if (running.kind === 'search') return `Searching ${running.query ?? ''}`.trim();
    return doing(running);
}
