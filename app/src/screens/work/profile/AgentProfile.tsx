// An agent's profile beside its session, as Slack opens a person's from their name: who it is (its name renamed in
// place) and what it's doing (its state as the ring round its avatar), Message and its menu (stop, pause its triggers, change how it works, leave
// this space, delete it), then where it runs and on what, its triggers in a line, its sessions (resuming an earlier
// one), its MCP servers, its budget, the channels it's in, its skills and memories. What triggers it is its Triggers tab, what it can use (app by app) its
// Tools tab, its one /workspace its Files tab, every time it woke its Activity tab, each in the URL. The page's side panel frames it (width, resize edge).
import { useState, type ReactNode } from 'react';
import { toast } from 'sonner';
import { Bell, BellOff, ChevronRight, MessageCircle, MoreHorizontal, Pencil, Settings, Square, Trash2, X } from 'lucide-react';
import { Agent, Operation, Workspace } from 'noclick';
import { invalidateV1 } from '@/sdk/useV1';
import { useReportHeld } from '@/sdk/held';
import { HAIRLINE } from '@/ui/primitives';
import { BUTTON_PRIMARY } from '@/ui/buttons';
import { MENU_SURFACE } from '@/ui/menus';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/ui/dropdown-menu';
import { Popover, PopoverContent, PopoverTrigger } from '@/ui/popover';
import { useInPhoneShell } from '@/ui/phoneBar';
import { useWork } from '../context';
import { cn } from '@/ui/utils';
import { ICON_BUTTON } from '../ui';
import { useWorkClient } from '../client';
import { useWorkNav } from '../nav';
import { useWorkPlace, HOME_SPACE, type ProfileTab } from '../place';
import { AgentRing } from '../agents/AgentRing';
import { useDeleteAgent } from '../agents/DeleteAgent';
import { EditableAgentName } from '../agents/rename';
import { AGENTS_KEY, factsOf, nameOf, STATES_KEY, useAgentFaces, useAgentFrames, useAgentStates, useSpaceNoClicks } from '../agents/reads';
import { agoText, byAttention, entryOf } from '../agents/states';
import { BudgetBody, type BudgetValue } from '../newAgent/footer';
import { AgentKnowledge } from '../resources/knowledge/AgentKnowledge';
import { useKnowledgeFrames } from '../resources/knowledge/store';
import { AgentActivity } from './activity';
import { AppTestingSetting } from './AppTesting';
import { AgentCarried } from './carried';
import { AgentFacts } from './facts';
import { ToolServers } from './toolServers';
import { rereadAgent, useAgent, useAgentChannels, useAgentProfileFrames, useAgentSpaces, useMonthSpend } from './reads';
import { TriggersTab } from '../triggers/TriggersTab';
import { ToolsTab } from '../tools/ToolsTab';
import { AgentFiles } from '../files/AgentFiles';
import type { AddSeed, AddKind } from '../triggers/AddTrigger';
import { useTriggerFrames, useTriggerItems } from '../triggers/data';
import { useSessionControls } from '../conversation/sessionControls';

export interface AgentProfileProps {
    agentId: string;
    onClose(): void;
    onOpenMachine(): void;
    onOpenChannel(channelId: string): void;
}

type Tab = 'about' | ProfileTab;
const TABS: Tab[] = ['about', 'triggers', 'tools', 'files', 'activity'];
const TAB_LABEL: Record<Tab, string> = { about: 'Profile', triggers: 'Triggers', tools: 'Tools', files: 'Files', activity: 'Activity' };
const ADD_KINDS: readonly string[] = ['cron', 'event', 'email', 'channel', 'call', 'webhook', 'platform'];
// A finger's height on a phone.
const SMALL_PRIMARY = BUTTON_PRIMARY.replace('h-9', 'h-8 max-md:h-10');
const ITEM = 'gap-2.5 rounded-lg px-2.5 py-2 text-[14px]';

export function AgentProfile({ agentId, onClose, onOpenMachine, onOpenChannel }: AgentProfileProps) {
    const [place, go] = useWorkPlace();
    const tab: Tab = place.profileTab ?? 'about';
    const setTab = (t: Tab) => go({ profileTab: t === 'about' ? null : t, trigger: null });
    // Adding one: `add` or `add:<kind>` in the URL; what it starts from (a replacement's app event) kept here.
    const [seed, setSeed] = useState<AddSeed>({});
    const addKind = place.trigger?.startsWith('add:') ? place.trigger.slice(4) : null;
    const adding: AddSeed | null = place.trigger === 'add' || addKind ? { ...(addKind && ADD_KINDS.includes(addKind) ? { kind: addKind as AddKind } : {}), ...seed } : null;
    const phone = useInPhoneShell();
    const agent = useAgent(agentId);
    useAgentFrames();
    useAgentProfileFrames(agentId);
    useKnowledgeFrames();
    const noclicks = useSpaceNoClicks();
    const name = agent.data ? nameOf(agent.data, noclicks) : '';
    return (
        <div className="flex h-full min-h-0 flex-col" data-testid="agent-profile">
            <div className={cn('flex h-12 shrink-0 items-stretch gap-5 border-b px-5', HAIRLINE)} role="tablist">
                {TABS.map((t) => (
                    <button
                        key={t}
                        type="button"
                        role="tab"
                        aria-selected={tab === t}
                        onClick={() => setTab(t)}
                        className={cn('-mb-px flex items-center border-b-2 text-sm transition-colors', tab === t ? 'border-foreground font-semibold text-foreground' : 'border-transparent text-muted-foreground hover:text-foreground')}
                    >
                        {TAB_LABEL[t]}
                    </button>
                ))}
                {/* On a phone the bar above says its name and closes it. */}
                {!phone && (
                    <button type="button" aria-label="Close" onClick={onClose} className={cn(ICON_BUTTON, 'ml-auto self-center')}>
                        <X className="h-[18px] w-[18px]" />
                    </button>
                )}
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto scrollbar-subtle">
                {!agent.data ? (
                    <p className="px-5 py-6 text-sm text-muted-foreground">{agent.error !== undefined ? 'Couldn’t load this agent.' : 'Loading…'}</p>
                ) : tab === 'about' ? (
                    <About agent={agent.data} onOpenMachine={onOpenMachine} onOpenChannel={onOpenChannel} onTriggers={() => setTab('triggers')} />
                ) : tab === 'tools' ? (
                    <ToolsTab agent={agent.data} name={name} />
                ) : tab === 'files' ? (
                    <div className="px-5 pb-8 pt-5">
                        <AgentFiles agentId={agentId} name={name} preview="sheet" />
                    </div>
                ) : tab === 'triggers' ? (
                    <TriggersTab
                        agent={agent.data}
                        name={name}
                        phone={phone}
                        openId={place.trigger && !adding ? place.trigger : null}
                        onOpen={(id) => go({ trigger: id }, { replace: true })}
                        adding={adding}
                        onAdding={(next) => {
                            setSeed(next ?? {});
                            go({ trigger: next ? (next.kind ? `add:${next.kind}` : 'add') : null });
                        }}
                    />
                ) : (
                    <AgentActivity agentId={agentId} name={name} />
                )}
            </div>
        </div>
    );
}

function LiveDot() {
    return (
        <span className="relative h-2 w-2 shrink-0">
            <span className="absolute inset-0 animate-ping rounded-full bg-emerald-500/60 motion-reduce:animate-none" />
            <span className="relative block h-2 w-2 rounded-full bg-emerald-500" />
        </span>
    );
}

function About({ agent, onOpenMachine, onOpenChannel, onTriggers }: { agent: Agent; onOpenMachine: () => void; onOpenChannel: (id: string) => void; onTriggers: () => void }) {
    const client = useWorkClient();
    const nav = useWorkNav();
    const { ask } = useWork();
    const [place] = useWorkPlace();
    const states = useAgentStates(null);
    const faces = useAgentFaces();
    const triggers = useTriggerItems(agent.id, agent.paused);
    useTriggerFrames(agent.id);
    const channels = useAgentChannels(agent.id);
    const spaces = useAgentSpaces(agent.id);
    const state = states.data?.find((s) => s.agentId === agent.id);
    const facts = factsOf(agent, useSpaceNoClicks());
    const name = facts.name;
    const entry = state ? entryOf(state, facts, Date.now()) : null;
    // Its job sits under its name, so an idle line says only when it last worked.
    const line = state?.state === 'idle' ? (state.lastActiveAt ? `Worked ${agoText(Date.now() - state.lastActiveAt.getTime())}` : 'Hasn’t worked yet') : entry?.line;
    const face = faces.get(agent.id) ?? { id: agent.id, kind: 'agent' as const, name, ...(facts.noclick ? { noclick: true } : {}) };
    const working = entry?.status === 'working';
    const needs = (entry?.needs ?? 0) > 0;
    const space = place.space && place.space !== HOME_SPACE ? place.space : null;
    // Deleted, you go on to the next agent as the list orders them.
    const order = (states.data ?? []).map((s) => entryOf(s, undefined, Date.now())).sort(byAttention).map((e) => e.id);
    const deleting = useDeleteAgent(order);
    const sessions = useSessionControls(agent, agent.id, name, working);
    const conversation = sessions.sessions?.active ?? null;

    const reportHeld = useReportHeld({ client });
    const act = async (what: string, run: () => Promise<unknown>, done?: string) => {
        try {
            await run();
            if (done) toast(done);
            rereadAgent(agent.id);
            invalidateV1(STATES_KEY);
        } catch (error) {
            if (reportHeld(error, `${what[0].toUpperCase()}${what.slice(1)}`, () => (rereadAgent(agent.id), invalidateV1(STATES_KEY)))) return;
            toast(`Couldn’t ${what}`, { description: error instanceof Error ? error.message : String(error) });
        }
    };
    const stop = () =>
        act(
            'stop it',
            async () => {
                const live = await Operation.list({ client, agent: agent.id, kind: 'agent.message', status: 'live' });
                await Promise.all(live.map((op) => op.cancel()));
            },
            `Stopped what ${name} was doing`
        );
    const pause = () =>
        act(
            agent.paused ? 'resume its triggers' : 'pause its triggers',
            () => (agent.paused ? Agent.fromId(agent.id, { client }).resume() : Agent.fromId(agent.id, { client }).pause()),
            agent.paused ? `${name}’s triggers are back on` : `Paused ${name}’s triggers: messages still reach it`
        );
    const leave = () =>
        act(
            'remove it from this space',
            async () => {
                await Workspace.fromId(space!, { client }).remove(agent);
                invalidateV1(AGENTS_KEY);
            },
            `${name} left this space; it stays yours`
        );

    return (
        <div className="px-5 pb-8 pt-6">
            <AgentRing member={face} status={entry?.status ?? 'idle'} size={80} />
            <EditableAgentName agent={agent} name={name} className="mt-4 text-[21px] font-semibold leading-tight tracking-[-0.01em]" />
            {facts.role && <p className="mt-1 text-sm leading-snug text-muted-foreground">{facts.role}</p>}
            {/* Its old name still reaches it, so it's said once, under the new one. */}
            {!facts.noclick && agent.formerNames.length > 0 && <p className="mt-1 text-xs text-muted-foreground">Formerly {agent.formerNames[0]}</p>}
            {entry && (
                <p className="mt-3 flex items-center gap-2 text-sm">
                    {working ? <LiveDot /> : <span className={cn('h-2 w-2 shrink-0 rounded-full', needs ? 'bg-foreground' : entry.status === 'failed' ? 'bg-red-500' : 'bg-foreground/25')} />}
                    <span className={cn('min-w-0 truncate', entry.status === 'failed' ? 'text-red-600 dark:text-red-400' : 'text-foreground/85')}>{line}</span>
                </p>
            )}
            {agent.paused && (
                <p className="mt-2 flex items-center gap-2 text-[13px] text-muted-foreground">
                    <BellOff className="h-3.5 w-3.5" strokeWidth={2} />
                    Its triggers are paused; messages still reach it.
                </p>
            )}
            <div className="mt-4 flex items-center gap-2">
                <button type="button" onClick={() => nav.openAgent(agent.id)} className={SMALL_PRIMARY}>
                    <MessageCircle className="h-4 w-4" strokeWidth={2} />
                    Message
                </button>
                <DropdownMenu>
                    <DropdownMenuTrigger aria-label="More" className={cn(ICON_BUTTON, 'bg-foreground/[0.05] data-[state=open]:bg-foreground/[0.08] data-[state=open]:text-foreground')}>
                        <MoreHorizontal className="h-[18px] w-[18px]" />
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="start" sideOffset={6} className="min-w-[230px] rounded-xl p-1">
                        {working && (
                            <DropdownMenuItem onSelect={() => void stop()} className={ITEM}>
                                <Square className="h-3.5 w-3.5 fill-current text-muted-foreground" strokeWidth={0} />
                                Stop what it’s doing
                            </DropdownMenuItem>
                        )}
                        <DropdownMenuItem onSelect={() => void pause()} className={ITEM}>
                            {agent.paused ? <Bell className="h-4 w-4 text-muted-foreground" strokeWidth={2} /> : <BellOff className="h-4 w-4 text-muted-foreground" strokeWidth={2} />}
                            {agent.paused ? 'Resume its triggers' : 'Pause its triggers'}
                        </DropdownMenuItem>
                        {ask && (
                            <DropdownMenuItem onSelect={() => ask(`Change how ${name} works: `)} className={ITEM}>
                                <Settings className="h-4 w-4 text-muted-foreground" strokeWidth={2} />
                                Change how it works
                            </DropdownMenuItem>
                        )}
                        {(space || !facts.noclick) && <DropdownMenuSeparator className="mx-1 bg-border dark:bg-foreground/[0.08]" />}
                        {space && (
                            <DropdownMenuItem onSelect={() => void leave()} className={cn(ITEM, 'text-red-600 dark:text-red-400')}>
                                Remove from this space
                            </DropdownMenuItem>
                        )}
                        {/* NoClick keeps its own agent for the account: it's never deleted. */}
                        {!facts.noclick && (
                            <DropdownMenuItem onSelect={() => deleting.ask({ id: agent.id, name })} className={cn(ITEM, 'text-red-600 dark:text-red-400')}>
                                <Trash2 className="h-4 w-4" strokeWidth={2} />
                                Delete agent
                            </DropdownMenuItem>
                        )}
                    </DropdownMenuContent>
                </DropdownMenu>
                {deleting.dialog}
            </div>
            <section className={cn('mt-6 border-t pt-5', HAIRLINE)}>
                <AgentFacts
                    agent={agent}
                    conversation={conversation}
                    triggers={triggers.loading ? undefined : triggers.error ? null : triggers.items}
                    onMachine={onOpenMachine}
                    onTriggers={onTriggers}
                    sessions={
                        sessions.sessions && (
                            <button type="button" onClick={sessions.resume} data-testid="sessions-fact" className="-mx-1.5 flex min-w-0 max-w-full items-center gap-2 rounded-full px-1.5 py-[3px] text-left transition-colors hover:bg-foreground/[0.05]">
                                <span className="min-w-0 truncate">
                                    1 active<span className="text-muted-foreground">, {sessions.earlier.length} you can resume</span>
                                </span>
                                <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" strokeWidth={2} />
                            </button>
                        )
                    }
                />
            </section>
            {sessions.dialogs}
            <AppTestingSetting agent={agent} />
            <ToolServers agent={agent} conversation={conversation} />
            <AgentCarried agent={agent} />
            <AgentKnowledge agentId={agent.id} />
            {(channels.data?.length ?? 0) > 0 && (
                <section className="mt-6">
                    <h3 className="text-xs font-medium text-muted-foreground">In</h3>
                    <p className="mt-1.5 text-sm leading-snug">
                        {channels.data!.map((c, i) => (
                            <span key={c.id}>
                                {i > 0 && ', '}
                                <button type="button" onClick={() => onOpenChannel(c.id)} className="rounded-full font-medium text-foreground underline-offset-2 hover:underline">
                                    #{c.name}
                                </button>
                            </span>
                        ))}
                        {(spaces.data?.length ?? 0) > 0 && <span className="text-muted-foreground"> · {new Intl.ListFormat('en', { type: 'conjunction' }).format(spaces.data!.map((s) => s.name))}</span>}
                    </p>
                </section>
            )}
            <MonthBudget agent={agent} />
        </div>
    );
}

/** This month's spend against its budget, the budget changed in place. */
function MonthBudget({ agent }: { agent: Agent }) {
    const client = useWorkClient();
    const spent = useMonthSpend(agent.id);
    const budget = agent.budgetUsdPerMonth;
    const [draft, setDraft] = useState<BudgetValue>(budget);
    const save = async (open: boolean) => {
        if (open) return setDraft(budget);
        if (draft === budget) return;
        try {
            await Agent.fromId(agent.id, { client }).update({ budgetUsdPerMonth: draft });
            rereadAgent(agent.id);
        } catch (error) {
            toast('Couldn’t change its budget', { description: error instanceof Error ? error.message : String(error) });
        }
    };
    const usd = spent.data;
    const pct = budget && usd !== undefined ? Math.min(100, Math.round((usd / budget) * 100)) : 0;
    const amount: ReactNode = usd === undefined ? '…' : `$${usd.toFixed(2)}`;
    return (
        <section className="mt-6" data-testid="agent-budget">
            <div className="flex items-baseline justify-between gap-3">
                <h3 className="text-xs font-medium text-muted-foreground">This month</h3>
                <Popover onOpenChange={(open) => void save(open)}>
                    <PopoverTrigger className="-my-1 inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-xs tabular-nums text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground" aria-label="Its budget">
                        {amount} {budget !== null ? `of $${budget}` : '· no cap of its own'}
                        <Pencil className="h-3 w-3" strokeWidth={2} />
                    </PopoverTrigger>
                    <PopoverContent align="end" sideOffset={6} className={cn('w-[320px] rounded-2xl p-1.5', MENU_SURFACE)}>
                        <BudgetBody value={draft} onChange={setDraft} />
                    </PopoverContent>
                </Popover>
            </div>
            {budget !== null && (
                <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-foreground/[0.08]">
                    <div className="h-full rounded-full bg-foreground/70" style={{ width: `${pct}%` }} />
                </div>
            )}
        </section>
    );
}
