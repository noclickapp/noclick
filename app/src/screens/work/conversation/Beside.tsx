// What works beside a session, as one surface: a card at its top right with the session's facts (where it
// runs, its repo and branch, what it changed) ending in "Beside it" ("1 needs you · 3 running", a dot
// each), which grows into the rail. The rail keeps the facts on top, then main (this session) as the anchor, and
// the groups: Needs you, Running, then a Done today fold. A row is a subagent's mark in its status ring, its task over
// its newest moment, and its time over what its task cost (only a NoClick agent's: the platform meters no harness
// subagent on its own); hovered, Open and Stop. Opening a harness subagent puts its log in the pane (`BesideLog`); a NoClick
// agent opens itself. On a phone the card is a pill in the header and the rail a sheet.
// What else needs the person beside it (`asks`: the Chat page's held purchases and deletions, its cap, an account to
// connect) leads the card and the rail as a Needs you group, each with its one action. Marks are ink, as the agent's
// ring is: solid for what needs you, the shimmer while it works, red only for a failure. A loop's row says when it
// runs next, and its Stop ends the loop.
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Link } from 'react-router';
import { ArrowLeft, ArrowUpRight, Box, Check, ChevronRight, CircleAlert, CornerDownRight, FileDiff, FolderGit2, GitBranch, Monitor, Repeat, Square, X } from 'lucide-react';
import type { Agent, AgentStepDiff, HarnessName, HarnessRequest, RequestDecision } from 'noclick';
import { HAIRLINE } from '@/ui/primitives';
import { BUTTON_DANGER, BUTTON_GHOST } from '@/ui/buttons';
import { MemberAvatar } from '@/screens/channels/avatars';
import type { AgentState as FaceState, ChannelMember } from '@/screens/channels/types';
import { MENU_SURFACE } from '@/ui/menus';
import { ShellDialog } from '@/ui/ShellDialog';
import { Popover, PopoverContent, PopoverTrigger } from '@/ui/popover';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/ui/tooltip';
import { cn } from '@/ui/utils';
import { BesideBrowserRail, BesideBrowserTile } from '../browser/pieces';
import { AgentRing } from '../agents/AgentRing';
import { HarnessMark, harnessLabel } from '../agents/harness';
import type { RingStatus } from '../agents/states';
import { useConversationSandbox, useMachine } from '../profile/reads';
import { DiffStat, diffStat, Elapsed, StepList } from './Activity';
import { clockOf, grouped, isLive, type BesideItem } from './besideItems';
import { ApprovalRow, PlanCard, QuestionSummary, UserRow } from './Rows';
import type { UserEntry } from '@/lib/agentThread/thread';

/** The card's width, and the room the open rail takes from the conversation. */
export const CARD_WIDTH = 260;
export const RAIL_ROOM = 344;
/** The narrowest pane the card floats over (below it, a pill), and the narrowest column the open rail leaves the
 *  conversation beside it (on a narrower pane it floats over it instead). */
export const CARD_MIN_PANE = 900;
export const MIN_COLUMN = 480;
const CARD_SPAN = CARD_WIDTH + 24;

/** What a reading lane gives up on its right so its text (`laneText` at its widest) clears the card: none where its
 *  margin holds it, else as much as centres it clear of it, never more than the card's span past the lane's padding. */
export const cardReserve = (pane: number, laneText: number) => Math.min(Math.max(0, laneText + 2 * CARD_SPAN - pane), CARD_SPAN - 20);

/** The open rail on a laptop, floating at the pane's right under its header. */
export function RailPanel({ children }: { children: ReactNode }) {
    return (
        <div className={cn('wc-panel absolute bottom-3 right-3 top-[60px] z-20 flex flex-col overflow-hidden rounded-[22px]', MENU_SURFACE)} style={{ width: RAIL_ROOM - 24 }}>
            {children}
        </div>
    );
}

/** The rail on a phone: a sheet from the bottom. */
export function RailSheet({ onClose, children }: { onClose: () => void; children: ReactNode }) {
    return (
        <div className="fixed inset-0 z-50 flex flex-col justify-end">
            {/* The page dimmed and the sheet raised off it, as the model picker's sheet is: on black, a sheet of the
                page's own black under a faint dim read as part of the page. */}
            <button type="button" aria-label="Close" onClick={onClose} className="absolute inset-0 bg-black/50" />
            <div role="dialog" aria-label="Beside it" className="wc-drawer relative flex max-h-[82vh] flex-col overflow-hidden rounded-t-[26px] bg-composer pb-[max(env(safe-area-inset-bottom),16px)] ring-1 ring-border dark:ring-foreground/[0.1]">
                <span aria-hidden className="mx-auto mb-1 mt-2 h-1 w-9 shrink-0 rounded-full bg-foreground/20" />
                {children}
            </div>
        </div>
    );
}

const sum = (items: readonly BesideItem[]) => {
    const live = items.filter(isLive);
    return { live, needs: live.filter((b) => b.status === 'needs').length, running: live.filter((b) => b.status === 'running').length };
};

/** "1 needs you · 3 running", what needs you first and in full ink; "2 done today" once none works. `asks`: what else
 *  needs you beside it, counted with its own. */
function Count({ items, asks = 0 }: { items: readonly BesideItem[]; asks?: number }) {
    const { running, needs: own } = sum(items);
    const needs = own + asks;
    if (!needs && !running) return <>{items.length === 1 ? '1 done today' : `${items.length} done today`}</>;
    return (
        <>
            {needs > 0 && <span className="font-medium text-foreground">{needs} needs you</span>}
            {needs > 0 && running > 0 && ' · '}
            {running > 0 && `${running} running`}
        </>
    );
}

/** The dot a live one carries on the card: solid ink when it needs you, a breathing one while it runs. */
function LiveDot({ needs }: { needs: boolean }) {
    return <span className={cn('h-1.5 w-1.5 rounded-full', needs ? 'bg-foreground' : 'work-breathe bg-foreground/60')} />;
}

/** Something that needs the person beside the conversation, with its one action (Review, Raise cap, Connect …): its
 *  title jumps to where the conversation shows it. */
export interface BesideAsk {
    key: string;
    title: string;
    line: string | null;
    action: { label: string; href?: string; onClick?: () => void } | null;
    onJump?: () => void;
}

const ASK_ACTION =
    'inline-flex h-7 shrink-0 items-center rounded-full bg-primary px-3 text-[12.5px] font-medium text-primary-foreground transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/70 focus-visible:ring-offset-1';

/** An ask's one action: a page of this app in place, anywhere else in a new tab, or what it does here. */
function AskAction({ action, onDone }: { action: NonNullable<BesideAsk['action']>; onDone?: () => void }) {
    if (action.href?.startsWith('/'))
        return (
            <Link to={action.href} onClick={onDone} className={ASK_ACTION}>
                {action.label}
            </Link>
        );
    if (action.href)
        return (
            <a href={action.href} target="_blank" rel="noopener noreferrer" onClick={onDone} className={ASK_ACTION}>
                {action.label}
            </a>
        );
    return (
        <button
            type="button"
            onClick={() => {
                action.onClick?.();
                onDone?.();
            }}
            className={ASK_ACTION}
        >
            {action.label}
        </button>
    );
}

function AskRow({ ask, phone, onDone }: { ask: BesideAsk; phone: boolean; onDone?: () => void }) {
    const jump = ask.onJump;
    return (
        <div data-ask={ask.key} className={cn('flex items-center gap-2.5 rounded-[12px] pl-2.5 pr-1.5 transition-colors', jump && 'hover:bg-foreground/[0.04]', phone ? 'min-h-[56px]' : 'min-h-[44px] py-1')}>
            <button
                type="button"
                disabled={!jump}
                onClick={() => {
                    jump?.();
                    onDone?.();
                }}
                className="min-w-0 flex-1 self-stretch text-left focus-visible:outline-none disabled:cursor-default"
            >
                <span className="line-clamp-2 text-[13px] font-medium leading-snug text-foreground">{ask.title}</span>
                {ask.line && <span className="block truncate text-[11.5px] leading-tight text-muted-foreground">{ask.line}</span>}
            </button>
            {ask.action && <AskAction action={ask.action} onDone={onDone} />}
        </div>
    );
}

/** What needs you, each with its one action, under its head. */
function NeedsGroup({ asks, phone = false, sticky, onDone }: { asks: readonly BesideAsk[]; phone?: boolean; sticky?: string; onDone?: () => void }) {
    return (
        <section data-group="asks" data-testid="beside-needs">
            <p className={cn('flex items-baseline gap-1.5 px-2.5 pb-1 pt-2 text-[11.5px] font-medium text-foreground', sticky && cn('sticky top-0 z-10 pt-3', sticky))}>
                Needs you
                <span className="tabular-nums text-muted-foreground">{asks.length}</span>
            </p>
            {asks.map((a) => (
                <AskRow key={a.key} ask={a} phone={phone} onDone={onDone} />
            ))}
        </section>
    );
}

/** Where it runs and how long it's been up, its repo and branch, what it changed: only what Work has. */
export function ConversationFacts({ agent, conversation, changes }: { agent: Agent; conversation: string; changes: AgentStepDiff[] }) {
    const sandbox = useConversationSandbox(agent.id, conversation).data;
    const machine = useMachine(sandbox?.place === 'machine' ? sandbox.machineId : null).data;
    const repo = agent.repos[0];
    const repoName = typeof repo?.url === 'string' ? repo.url.replace(/^https?:\/\/[^/]+\//, '').replace(/\.git$/, '') : null;
    const branch = typeof repo?.branch === 'string' ? repo.branch : null;
    const stat = diffStat(changes);
    const row = 'flex h-8 items-center gap-2.5 rounded-[10px] px-2 text-[13px]';
    return (
        <div className="peer flex flex-col empty:hidden" data-testid="conversation-facts">
            {sandbox && (
                <div className={row}>
                    {sandbox.place === 'machine' ? <Monitor className="h-4 w-4 shrink-0 text-muted-foreground" strokeWidth={1.8} /> : <Box className="h-4 w-4 shrink-0 text-muted-foreground" strokeWidth={1.8} />}
                    <span className="min-w-0 flex-1 truncate">{sandbox.place === 'machine' ? (machine?.name ?? 'Its machine') : 'Cloud sandbox'}</span>
                    <span className="shrink-0 text-[12px] tabular-nums text-muted-foreground">
                        {sandbox.status === 'running' && sandbox.startedAt ? (
                            <>
                                Up <Elapsed from={sandbox.startedAt.getTime()} />
                            </>
                        ) : sandbox.status === 'running' ? (
                            'Up'
                        ) : (
                            'Stopped'
                        )}
                    </span>
                </div>
            )}
            {branch && (
                <div className={row}>
                    <GitBranch className="h-4 w-4 shrink-0 text-muted-foreground" strokeWidth={1.8} />
                    <span className="min-w-0 flex-1 truncate">{branch}</span>
                </div>
            )}
            {repoName && (
                <div className={row}>
                    <FolderGit2 className="h-4 w-4 shrink-0 text-muted-foreground" strokeWidth={1.8} />
                    <span className="min-w-0 flex-1 truncate">{repoName}</span>
                </div>
            )}
            {(stat.added > 0 || stat.removed > 0) && (
                <div className={row}>
                    <FileDiff className="h-4 w-4 shrink-0 text-muted-foreground" strokeWidth={1.8} />
                    <span className="min-w-0 flex-1 truncate">Changes</span>
                    <DiffStat {...stat} className="shrink-0 text-[12px]" />
                </div>
            )}
        </div>
    );
}

/** The card's body: what needs you (`asks`), the conversation's facts, then what works beside it, a row that opens the
 *  rail. */
function CardBody({ facts, items, asks = [], onOpen, onDone }: { facts: ReactNode; items: readonly BesideItem[]; asks?: readonly BesideAsk[]; onOpen: () => void; onDone?: () => void }) {
    const { live } = sum(items);
    const browser = items.some((b) => b.kind === 'browser');
    // Facts that come to nothing (no sandbox, repo or change) draw no rule under them.
    const rule = (className?: string) => <div className={cn('mx-1 my-1.5 border-t', HAIRLINE, className)} />;
    return (
        <>
            {asks.length > 0 && <NeedsGroup asks={asks} onDone={onDone} />}
            {asks.length > 0 && (facts || items.length > 0) && rule()}
            {facts}
            {browser && <BesideBrowserTile />}
            {items.length > 0 && (
                <>
                    {(facts || browser) && rule('peer-empty:hidden')}
                    <p className="px-2 pb-0.5 text-[11.5px] text-muted-foreground">Beside it</p>
                    <button type="button" onClick={onOpen} className="group/sub flex h-9 w-full items-center gap-2.5 rounded-[10px] px-2 text-left text-[13px] transition-colors hover:bg-foreground/[0.05] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/70">
                        {live.length > 0 && (
                            <span className="flex shrink-0 items-center gap-0.5" aria-hidden>
                                {[...live.filter((b) => b.status === 'needs'), ...live.filter((b) => b.status === 'running')].slice(0, 5).map((b) => (
                                    <LiveDot key={b.id} needs={b.status === 'needs'} />
                                ))}
                            </span>
                        )}
                        <span className="min-w-0 flex-1 truncate">
                            <Count items={items} />
                        </span>
                        <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform group-hover/sub:translate-x-0.5" strokeWidth={2} />
                    </button>
                </>
            )}
        </>
    );
}

const CARD_SURFACE = cn('rounded-[22px] p-1.5', MENU_SURFACE);

/** The card at the conversation's top right, where the pane is wide enough to float it. */
export function BesideCard({ facts, items, asks, onOpen }: { facts: ReactNode; items: readonly BesideItem[]; asks?: readonly BesideAsk[]; onOpen: () => void }) {
    return (
        <div className={cn('wc-panel absolute right-3 top-[60px] z-20', CARD_SURFACE)} style={{ width: CARD_WIDTH }} data-testid="beside-card">
            <CardBody facts={facts} items={items} asks={asks} onOpen={onOpen} />
        </div>
    );
}

/** The card folded into the header where the pane is too narrow to float it: where it runs and its count ("1 needs you
 *  · 8 running"). On a laptop it opens the card itself, anchored under it; on a phone, the sheet. */
export function BesidePill({
    agentId,
    conversation,
    items,
    asks = [],
    facts,
    phone,
    onOpenRail,
}: {
    agentId: string;
    conversation: string;
    items: readonly BesideItem[];
    asks?: readonly BesideAsk[];
    facts: ReactNode;
    phone: boolean;
    onOpenRail: () => void;
}) {
    const [open, setOpen] = useState(false);
    const place = useConversationSandbox(agentId, conversation).data?.place;
    const Place = place === 'machine' ? Monitor : Box;
    const pill = (
        <button
            type="button"
            onClick={phone ? onOpenRail : undefined}
            data-testid="beside-pill"
            data-state={open ? 'open' : 'closed'}
            className="inline-flex h-7 min-w-0 shrink-0 items-center gap-1.5 rounded-full px-2 text-xs text-muted-foreground transition-colors hover:bg-foreground/[0.04] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/70 data-[state=open]:bg-foreground/[0.06] data-[state=open]:text-foreground"
        >
            <Place className="h-3.5 w-3.5 shrink-0" strokeWidth={1.8} />
            <span className="truncate text-foreground/85">
                <Count items={items} asks={asks.length} />
            </span>
        </button>
    );
    if (phone) return pill;
    return (
        <Popover open={open} onOpenChange={setOpen}>
            <PopoverTrigger asChild>{pill}</PopoverTrigger>
            <PopoverContent align="end" sideOffset={8} collisionPadding={12} className={cn('wc-panel', CARD_SURFACE)} style={{ width: CARD_WIDTH }} data-testid="beside-card">
                <CardBody
                    facts={facts}
                    items={items}
                    asks={asks}
                    onOpen={() => {
                        setOpen(false);
                        onOpenRail();
                    }}
                    onDone={() => setOpen(false)}
                />
            </PopoverContent>
        </Popover>
    );
}

const RING: Record<BesideItem['status'], RingStatus> = { running: 'working', needs: 'needs', failed: 'failed', done: 'idle', stopped: 'idle' };

// The mascot's faces for what the ring has no word for: a done one is glad, a stopped one sleeps.
const FACE: Partial<Record<BesideItem['status'], FaceState>> = { done: 'done', stopped: 'asleep' };

/** Its mark in the agent's ring: the shimmer while it runs, solid ink when it needs you, red if it failed; a tick once
 *  done, a grey dot once stopped. */
function RingMark({ item, face, harness, size = 24 }: { item: BesideItem; face?: ChannelMember; harness: HarnessName | null; size?: 20 | 24 }) {
    return (
        <span className="relative inline-flex shrink-0" data-ring={item.status}>
            <AgentRing member={face} mark={item.kind === 'loop' ? <Repeat className="h-3 w-3" strokeWidth={2} /> : harness ? <HarnessMark harness={harness} className="h-3 w-3" /> : null} status={RING[item.status]} face={FACE[item.status]} size={size} />
            {item.status === 'done' && (
                <span className="absolute -bottom-0.5 -right-0.5 grid h-3 w-3 place-items-center rounded-full bg-foreground text-background">
                    <Check className="h-2 w-2" strokeWidth={3.5} />
                </span>
            )}
            {item.status === 'stopped' && <span className="absolute -bottom-0.5 -right-0.5 h-2.5 w-2.5 rounded-full bg-foreground/40 ring-2 ring-background" />}
        </span>
    );
}

const STATUS_WORD: Record<BesideItem['status'], string> = { needs: 'Needs you', running: 'Running', done: 'Done', failed: 'Failed', stopped: 'Stopped' };

const tookOf = (item: BesideItem) => clockOf((item.endedAt ?? Date.now()) - item.startedAt);
const clock = (at: number) => new Date(at).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });

/** Where a running loop's row tells the time: when it runs next, or that a run of it works now. */
const nextRun = (item: BesideItem) => (item.turnRunning ? 'Now' : item.loop?.nextAt ? clock(item.loop.nextAt) : null);

/** Its hover card: what it runs on, where it stands, how long, and what it spent where that's metered. */
function RowCard({ item, runsOn }: { item: BesideItem; runsOn: string | null }) {
    const fact = (k: string, v: ReactNode) => (
        <div className="flex items-baseline justify-between gap-4">
            <span className="text-muted-foreground">{k}</span>
            <span className="text-right tabular-nums">{v}</span>
        </div>
    );
    return (
        <div className="flex w-[240px] flex-col gap-1 text-[12px] leading-snug">
            <p className="text-[13px] font-medium">{item.title}</p>
            {runsOn && fact(item.kind === 'agent' ? 'Model' : 'Runs on', runsOn)}
            {fact('Status', STATUS_WORD[item.status])}
            {item.loop && fact('Runs', item.loop.every)}
            {item.loop && isLive(item) && fact('Next run', nextRun(item) ?? 'When this run sets it')}
            {item.loop && fact('Runs so far', item.loop.runs)}
            {fact(isLive(item) ? 'Running for' : 'Took', isLive(item) ? <Elapsed from={item.startedAt} /> : tookOf(item))}
            {item.spendUsd !== null && fact('This task', `$${item.spendUsd.toFixed(2)}`)}
            {item.line && <p className="mt-1 border-t pt-1.5 text-muted-foreground dark:border-foreground/[0.1]">{item.line}</p>}
        </div>
    );
}

export interface RowLook {
    face?: ChannelMember;
    harness: HarnessName | null;
    /** A NoClick agent's model, a harness subagent's harness. */
    runsOn: string | null;
}

/** One row: its mark in its ring, its task over its newest moment, its time over its spend; hovered, Open and Stop
 *  take that column's place. Selected, it holds a bar at its edge. */
function RailRow({ item, look, selected, phone, fresh, onSelect, onStop }: { item: BesideItem; look: RowLook; selected: boolean; phone: boolean; fresh: boolean; onSelect: () => void; onStop?: () => void }) {
    const [hover, setHover] = useState(false);
    const icon = 'grid h-7 w-7 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-foreground/[0.08] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/70';
    const open = item.kind === 'agent' ? 'Open it' : item.kind === 'subagent' ? 'Open its log' : null;
    return (
        <div
            data-beside={item.id}
            data-status={item.status}
            onMouseEnter={() => setHover(true)}
            onMouseLeave={() => setHover(false)}
            onFocus={() => setHover(true)}
            onBlur={(e) => !e.currentTarget.contains(e.relatedTarget as Node | null) && setHover(false)}
            className={cn('relative flex items-center gap-2.5 rounded-[12px] pl-2.5 pr-2 transition-colors', selected ? 'bg-foreground/[0.07]' : 'hover:bg-foreground/[0.04]', fresh && 'wc-slide-in', phone ? 'min-h-[56px]' : 'min-h-[44px]')}
        >
            {selected && <span aria-hidden className="absolute bottom-2 left-0 top-2 w-[2px] rounded-full bg-foreground" />}
            <Tooltip>
                <TooltipTrigger asChild>
                    <button type="button" onClick={onSelect} aria-current={selected ? 'true' : undefined} aria-label={`${item.title}: ${STATUS_WORD[item.status]}`} className="flex min-w-0 flex-1 items-center gap-2.5 self-stretch text-left focus-visible:outline-none">
                        <RingMark item={item} face={look.face} harness={look.harness} />
                        <span className="min-w-0 flex-1">
                            <span className={cn('block truncate text-[13px] leading-tight', item.status === 'needs' ? 'font-medium text-foreground' : item.status === 'failed' ? 'text-red-700 dark:text-red-300' : 'text-foreground/90')}>{item.title}</span>
                            {item.line && (
                                <span key={item.line} className={cn('wc-tick block truncate text-[11.5px] leading-tight', item.status === 'needs' ? 'text-foreground/80' : 'text-muted-foreground')}>
                                    {item.line}
                                </span>
                            )}
                        </span>
                    </button>
                </TooltipTrigger>
                <TooltipContent side={phone ? 'top' : 'left'} align="start" sideOffset={10} className="p-3">
                    <RowCard item={item} runsOn={look.runsOn} />
                </TooltipContent>
            </Tooltip>
            <span className="relative flex shrink-0 flex-col items-end justify-center" style={{ minWidth: 56 }}>
                <span className={cn('flex flex-col items-end transition-opacity', hover && !phone && 'opacity-0')} data-testid="beside-time">
                    <span className="text-[12px] tabular-nums text-foreground/75">{item.loop && isLive(item) ? nextRun(item) : isLive(item) ? <Elapsed from={item.startedAt} /> : tookOf(item)}</span>
                    {item.spendUsd !== null && <span className="text-[11px] tabular-nums text-muted-foreground">${item.spendUsd.toFixed(2)}</span>}
                </span>
                {!phone && (
                    <span className={cn('absolute inset-y-0 right-0 flex items-center transition-opacity', hover ? 'opacity-100' : 'pointer-events-none opacity-0')}>
                        {open && (
                            <Tooltip>
                                <TooltipTrigger asChild>
                                    <button type="button" aria-label={open} onClick={onSelect} className={icon}>
                                        <ArrowUpRight className="h-3.5 w-3.5" strokeWidth={2} />
                                    </button>
                                </TooltipTrigger>
                                <TooltipContent side="top">Open</TooltipContent>
                            </Tooltip>
                        )}
                        {onStop && (
                            <Tooltip>
                                <TooltipTrigger asChild>
                                    <button type="button" aria-label={`Stop ${item.title}`} onClick={onStop} className={icon}>
                                        <Square className="h-3 w-3 fill-current" strokeWidth={0} />
                                    </button>
                                </TooltipTrigger>
                                <TooltipContent side="top">{item.kind === 'subagent' ? 'Stop the turn' : 'Stop'}</TooltipContent>
                            </Tooltip>
                        )}
                    </span>
                )}
            </span>
        </div>
    );
}

export interface BesideRailProps {
    items: readonly BesideItem[];
    /** What else needs the person, leading the rail with its actions. */
    asks?: readonly BesideAsk[];
    facts: ReactNode;
    /** The agent the conversation is with: main's row. */
    face: ChannelMember;
    look: (item: BesideItem) => RowLook;
    selected: string | null;
    onSelect: (item: BesideItem | null) => void;
    /** What stops it, where anything can: a NoClick agent's task, or the turn a harness subagent runs in. */
    stoppable: (item: BesideItem) => boolean;
    onStop: (item: BesideItem) => void;
    onClose?: () => void;
    /** In the phone's sheet: taller rows, no hover. */
    phone?: boolean;
    /** Its head: "Subagents" in Work, where it lists the conversation's own. */
    title?: string;
    /** Just arrived, or just finished: they slide in, and a finished one shows in Done today a moment. */
    fresh: ReadonlySet<string>;
}

/** The rail: its facts, main, then Needs you, Running and Done today, each head sticking as it scrolls. */
export function BesideRail({ items, asks = [], facts, face, look, selected, onSelect, stoppable, onStop, onClose, phone = false, fresh, title = 'Subagents' }: BesideRailProps) {
    const [doneOpen, setDoneOpen] = useState(false);
    // The browser heads the rail as its own block, never a row.
    const browser = items.some((b) => b.kind === 'browser');
    const { needs, running, done } = grouped(items.filter((b) => b.kind !== 'browser'));
    const live = needs.length + running.length + asks.length;
    const stickyBg = 'bg-composer';
    const head = (label: string, n: number, tone?: 'needs') => (
        <p className={cn('sticky top-0 z-10 flex items-baseline gap-1.5 px-2.5 pb-1 pt-3 text-[11.5px] font-medium', stickyBg, tone === 'needs' ? 'text-foreground' : 'text-muted-foreground')}>
            {label}
            <span className="tabular-nums">{n}</span>
        </p>
    );
    const row = (b: BesideItem) => <RailRow key={b.id} item={b} look={look(b)} selected={selected === b.id} phone={phone} fresh={fresh.has(b.id)} onSelect={() => onSelect(b)} onStop={stoppable(b) ? () => onStop(b) : undefined} />;
    const settling = done.filter((b) => fresh.has(b.id));
    return (
        <div className="flex min-h-0 flex-1 flex-col" data-testid="beside-rail">
            {!phone && (
                <div className="flex h-12 shrink-0 items-center gap-2 px-3">
                    <p className="text-[14px] font-semibold">{title}</p>
                    <span className="rounded-full bg-foreground/[0.07] px-1.5 text-[11px] font-medium leading-[18px] tabular-nums text-muted-foreground">{live}</span>
                    {onClose && (
                        <button type="button" aria-label="Close" onClick={onClose} className="ml-auto grid h-8 w-8 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground">
                            <X className="h-4 w-4" />
                        </button>
                    )}
                </div>
            )}
            <div className="min-h-0 flex-1 overflow-y-auto px-1.5 pb-3 scrollbar-subtle">
                {asks.length > 0 && <NeedsGroup asks={asks} phone={phone} sticky={stickyBg} onDone={onClose} />}
                <div className="px-1 pb-1">
                    {facts}
                    {browser && <BesideBrowserRail />}
                    <div className={cn('mx-1 mt-1.5 border-t', HAIRLINE)} />
                </div>
                <button
                    type="button"
                    onClick={() => onSelect(null)}
                    aria-current={!selected ? 'true' : undefined}
                    className={cn('relative mt-1.5 flex w-full items-center gap-2.5 rounded-[12px] pl-2.5 pr-2 text-left transition-colors', !selected ? 'bg-foreground/[0.07]' : 'hover:bg-foreground/[0.04]', phone ? 'min-h-[56px]' : 'min-h-[44px]')}
                >
                    {!selected && <span aria-hidden className="absolute bottom-2 left-0 top-2 w-[2px] rounded-full bg-foreground" />}
                    <MemberAvatar member={face} size={24} />
                    <span className="min-w-0 flex-1">
                        <span className="block text-[13px] font-medium leading-tight">main</span>
                        <span className="block truncate text-[11.5px] leading-tight text-muted-foreground">{face.name} · this conversation</span>
                    </span>
                </button>
                {needs.length > 0 && (
                    <section data-group="needs">
                        {head('Needs you', needs.length, 'needs')}
                        {needs.map(row)}
                    </section>
                )}
                {running.length > 0 && (
                    <section data-group="running">
                        {head('Running', running.length)}
                        {running.map(row)}
                    </section>
                )}
                {done.length > 0 && (
                    <section className="mt-1" data-group="done">
                        <button type="button" onClick={() => setDoneOpen(!doneOpen)} aria-expanded={doneOpen} className={cn('sticky top-0 z-10 flex w-full items-center gap-1.5 px-2.5 pb-1 pt-3 text-left text-[11.5px] font-medium text-muted-foreground transition-colors hover:text-foreground', stickyBg)}>
                            Done today
                            <span className="tabular-nums">{done.length}</span>
                            <ChevronRight className={cn('h-3 w-3 transition-transform', doneOpen && 'rotate-90')} strokeWidth={2.25} />
                        </button>
                        {(doneOpen || settling.length > 0) && <div className="opacity-80">{(doneOpen ? done : settling).map(row)}</div>}
                    </section>
                )}
            </div>
        </div>
    );
}

/** What you wrote it, as its log shows it: your message, and how it got there (through main, then read once the turn
 *  that took it is over). */
export interface SaidTo {
    entry: UserEntry;
    read: boolean;
}

/** A harness subagent's own log in the pane: the way back to main, where it is ("main › its task"), what it was
 *  asked, its steps, what you wrote it and what it asks you, then what it found or why it failed. */
export function BesideLog({
    item,
    face,
    harness,
    said = [],
    requests = [],
    onAnswer,
    onBack,
    onStop,
}: {
    item: BesideItem;
    face: ChannelMember;
    harness: HarnessName | null;
    said?: SaidTo[];
    requests?: HarnessRequest[];
    onAnswer?: (request: HarnessRequest, decision: RequestDecision) => void;
    onBack: () => void;
    onStop?: () => void;
}) {
    const call = item.call!;
    const prompt = typeof call.arguments.prompt === 'string' ? call.arguments.prompt : null;
    const words = call.output.trim();
    return (
        <>
            <header className="flex h-12 shrink-0 items-center gap-2 pl-3 pr-3" data-testid="beside-log">
                <button type="button" aria-label="Back to main" onClick={onBack} className="grid h-8 w-8 shrink-0 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-foreground/[0.05] hover:text-foreground">
                    <ArrowLeft className="h-4 w-4" strokeWidth={2} />
                </button>
                <nav aria-label="Where you are" className="flex min-w-0 items-center gap-1.5 text-sm">
                    <button type="button" onClick={onBack} className="flex shrink-0 items-center gap-1.5 rounded-full py-1 pl-1 pr-2 text-muted-foreground transition-colors hover:bg-foreground/[0.05] hover:text-foreground">
                        <MemberAvatar member={face} size={20} />
                        <span className="max-sm:hidden">{face.name}</span>
                        <span className="text-muted-foreground/70 max-sm:hidden">main</span>
                    </button>
                    <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground/70" strokeWidth={2} />
                    <RingMark item={item} harness={harness} size={20} />
                    <span className="truncate font-medium">{item.title}</span>
                </nav>
                <span className="ml-auto flex shrink-0 items-center gap-2 text-[12.5px] tabular-nums text-muted-foreground">
                    {item.status === 'failed' ? <CircleAlert className="h-3.5 w-3.5 text-red-500 dark:text-red-300" strokeWidth={2} /> : null}
                    <span>{isLive(item) ? <Elapsed from={item.startedAt} /> : `${STATUS_WORD[item.status]} · ${tookOf(item)}`}</span>
                    {onStop && (
                        <button type="button" onClick={onStop} aria-label="Stop the turn" className="inline-flex h-8 items-center gap-1.5 rounded-full px-3 text-[13px] text-foreground/85 transition-colors hover:bg-foreground/[0.05] hover:text-foreground max-sm:px-2.5">
                            <Square className="h-3 w-3 fill-current sm:hidden" strokeWidth={0} />
                            <span className="max-sm:hidden">Stop the turn</span>
                        </button>
                    )}
                </span>
            </header>
            <div className="min-h-0 flex-1 overflow-y-auto scrollbar-subtle">
                <div className="mx-auto flex min-h-full w-full max-w-[46rem] flex-col justify-end gap-3 px-5 pb-4 pt-8">
                    <p className="text-[12.5px] leading-relaxed text-muted-foreground">
                        A subagent {face.name} started {harness ? `on ${harnessLabel(harness)} ` : ''}at {new Date(item.startedAt).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })}.
                    </p>
                    {prompt && <p className="whitespace-pre-line rounded-[20px] bg-foreground/[0.04] px-4 py-3 text-[13.5px] leading-relaxed text-foreground/85 [overflow-wrap:anywhere]">{prompt}</p>}
                    {item.status === 'failed' && <p className="text-[13px] leading-relaxed text-red-600 [overflow-wrap:anywhere] dark:text-red-300">{words || 'It failed.'}</p>}
                    <div className="px-1">{call.children.length ? <StepList steps={call.children} live={call.running} /> : <p className="text-sm text-muted-foreground">{call.running ? 'Starting…' : 'No steps kept.'}</p>}</div>
                    {said.map(({ entry, read }) => (
                        <UserRow
                            key={entry.key}
                            entry={entry}
                            mine
                            compact
                            receipt={
                                <p className="me-1 flex items-center gap-1 text-[11.5px] text-muted-foreground" data-receipt>
                                    <CornerDownRight className="h-3 w-3" strokeWidth={2} />
                                    {entry.pending ? `Sending through ${face.name}…` : `Sent through ${face.name}${read ? ' · read' : ''}`}
                                </p>
                            }
                        />
                    ))}
                    {onAnswer &&
                        requests.map((r) => (
                            <div key={r.id} className="px-1">
                                {r.kind === 'question' ? <QuestionSummary request={r} /> : r.action === 'plan' ? <PlanCard request={r} onAnswer={onAnswer} /> : <ApprovalRow request={r} onAnswer={onAnswer} />}
                            </div>
                        ))}
                    {item.status !== 'failed' && !isLive(item) && words && <blockquote className="whitespace-pre-line border-l-2 border-foreground/15 pl-2.5 text-[13.5px] leading-snug text-foreground/85 [overflow-wrap:anywhere]">{words}</blockquote>}
                </div>
            </div>
        </>
    );
}

/** Stopping one, confirmed: a NoClick agent's task stops where it is; a harness subagent stops only with its turn; a
 *  loop runs no more, its run at work finishing. */
export function StopBeside({ item, onClose, onStop }: { item: BesideItem | null; onClose: () => void; onStop: (item: BesideItem) => void }) {
    const kind = item?.kind;
    const say =
        kind === 'agent'
            ? { title: `Stop ${item?.agent?.name ?? 'it'}’s task?`, description: `It stops where it is. What it already changed stays, and so does its conversation.${item?.spendUsd != null ? ` $${item.spendUsd.toFixed(2)} spent on it so far.` : ''}`, stop: 'Stop it' }
            : kind === 'loop'
              ? { title: 'Stop this loop?', description: 'It won’t run again. A run at work now finishes, and what its runs did stays.', stop: 'Stop the loop' }
              : { title: 'Stop the turn?', description: 'A subagent stops only with the turn that started it: the whole turn stops, its other subagents too. What they changed stays.', stop: 'Stop the turn' };
    return (
        <ShellDialog
            open={!!item}
            onOpenChange={(o) => !o && onClose()}
            tone="danger"
            mark={<Square className="h-4 w-4 fill-current" strokeWidth={0} />}
            title={item ? say.title : ''}
            description={item ? say.description : ''}
            footer={
                <>
                    <button type="button" onClick={onClose} className={BUTTON_GHOST}>
                        Keep it running
                    </button>
                    <button type="button" onClick={() => item && onStop(item)} className={BUTTON_DANGER}>
                        {say.stop}
                    </button>
                </>
            }
        />
    );
}

/** Ids that just arrived or just finished, for a moment: they slide in, or settle into Done today. */
export function useFresh(items: readonly BesideItem[], hold = 2600): ReadonlySet<string> {
    // What was there as the conversation opened isn't news.
    const [seen] = useState(() => new Map<string, boolean>(items.map((b) => [b.id, isLive(b)])));
    const [fresh, setFresh] = useState<ReadonlySet<string>>(() => new Set());
    const timers = useRef<number[]>([]);
    const moved = items.filter((b) => !seen.has(b.id) || seen.get(b.id) !== isLive(b));
    const key = moved.map((b) => `${b.id}:${b.status}`).join(',');
    useEffect(() => {
        if (!moved.length) return;
        const ids = moved.map((b) => b.id);
        for (const b of moved) seen.set(b.id, isLive(b));
        setFresh((f) => new Set([...f, ...ids]));
        timers.current.push(window.setTimeout(() => setFresh((f) => new Set([...f].filter((id) => !ids.includes(id)))), hold));
    }, [key]); // eslint-disable-line react-hooks/exhaustive-deps
    useEffect(() => () => timers.current.forEach((t) => window.clearTimeout(t)), []);
    return fresh;
}
