// A channel's history, edge to edge across the pane as in Slack: where it
// starts with its agents and their jobs, and its schedules (or the way to read
// further back), then each day under a hairline whose pill stays pinned while
// you read that day (and jumps between days). Consecutive messages from one
// author share a header; words render as markdown with their files under them,
// then their reactions. An agent that @-mentions another hands it the work, a
// row of its own; what an agent posted for you is signed by it; NoClick's
// notes in the room (why it halted) read as NoClick's, and an app's event as
// that app's. NoClick's answers to your commands are yours alone, and
// dismissable. Who joined is a quiet line as in Slack (a run of adds is one), as is
// who the channel started with. Where the page takes threads and pins (Work), a message's hover
// bar adds quick reactions, Reply in thread and Pin, a message with replies
// wears Slack's replies bar, and a pinned one says who pinned it.
import { Fragment, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { ArrowRight, ChevronDown, ChevronRight, EyeOff, Hash, Link2, MessageSquareText, MoreHorizontal, Pin, PinOff, Plug, SmilePlus, UserMinus, UserPlus } from 'lucide-react';
import type { AccountMenuUser } from '~/components/nav/AccountMenu';
import { LogoMark, MARK_IN_A_SHAPE } from '~/components/shared/LogoMark';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuTrigger } from '~/components/ui/dropdown-menu';
import { Popover, PopoverContent, PopoverTrigger } from '~/components/ui/popover';
import { Tooltip, TooltipContent, TooltipTrigger } from '~/components/ui/tooltip';
import { cn } from '~/lib/utils';
import { MessageAttachments } from './attachments';
import { MemberAvatar, MENTION_HUE } from './avatars';
import { EmojiPicker } from './EmojiPicker';
import { MessageBody } from './MessageBody';
import { AGENT_HUES, authorMember, byNoClick, handoffsOf, modeLine, NOCLICK_NAME, postedForYou } from './model';
import { ScheduleLines } from './schedules';
import type { Channel, ChannelAuthor, ChannelMember, ChannelMessage, ChannelReaction, ChannelSchedule } from './types';

/** Consecutive messages from one author inside this window share a header. */
const GROUP_WINDOW_MS = 5 * 60 * 1000;

/** The pane's side gutter: messages, the intro and the header all start here. */
const GUTTER = 'px-5';

const pad = (n: number) => String(n).padStart(2, '0');

/** The local calendar day a moment falls on, as YYYY-MM-DD. */
export function localDay(iso: string): string {
    const d = new Date(iso);
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function dayLabel(day: string, today: string): string {
    if (day === today) return 'Today';
    // Local noon and local fields: an ISO round trip shifts the date east of UTC.
    const d = new Date(`${today}T12:00:00`);
    d.setDate(d.getDate() - 1);
    if (day === localDay(d.toISOString())) return 'Yesterday';
    return new Date(`${day}T12:00:00`).toLocaleDateString('en-US', { weekday: 'long', month: 'short', day: 'numeric' });
}

/** A message's time as Slack writes it: the reader's own clock ("9:24 AM"). */
export function timeLabel(iso: string): string {
    return new Date(iso).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
}

/** The same clock with no AM or PM ("9:29", "21:29"), short enough for the gutter beside a grouped message. */
export function clockLabel(iso: string, locale?: string): string {
    const parts = new Intl.DateTimeFormat(locale, { hour: 'numeric', minute: '2-digit' }).formatToParts(new Date(iso));
    const from = parts.findIndex((p) => p.type === 'hour');
    const to = parts.findIndex((p) => p.type === 'minute');
    return parts
        .slice(from, to + 1)
        .map((p) => p.value)
        .join('');
}

/** A key that says who wrote a message, for grouping. */
const authorKey = (m: ChannelMessage) => `${m.author.type}:${m.author.id ?? m.author.name}`;

function Intro({
    channel,
    schedules,
    members,
    older,
    loadingOlder,
    onLoadOlder,
    mark,
    after,
}: {
    channel: Channel;
    schedules: ChannelSchedule[];
    members: ChannelMember[];
    older: boolean;
    loadingOlder: boolean;
    onLoadOlder: () => void;
    mark?: ReactNode;
    after?: ReactNode;
}) {
    const agents = members.filter((m) => m.kind === 'agent');
    // Who it started with, as one line: its people, then NoClick, then the other agents.
    const order = (m: ChannelMember) => (m.kind === 'human' ? 0 : m.noclick ? 1 : m.kind === 'agent' ? 2 : 3);
    const here = members.filter((m) => m.kind !== 'you').sort((a, b) => order(a) - order(b));
    if (older) {
        return (
            <div className={cn('flex justify-center pb-2 pt-6', GUTTER)}>
                <button
                    type="button"
                    onClick={onLoadOlder}
                    disabled={loadingOlder}
                    data-testid="load-older"
                    className="inline-flex h-8 items-center rounded-full px-3.5 text-[13px] text-muted-foreground ring-1 ring-inset ring-border transition-colors hover:bg-foreground/[0.04] hover:text-foreground disabled:opacity-60 dark:ring-foreground/[0.1]"
                >
                    {loadingOlder ? 'Loading…' : 'Earlier messages'}
                </button>
            </div>
        );
    }
    return (
        <div className={cn('pb-4 pt-10', GUTTER)}>
            <span className="grid h-12 w-12 place-items-center rounded-2xl bg-foreground/[0.05] ring-1 ring-inset ring-foreground/[0.06]">
                {mark ?? <Hash className="h-6 w-6 text-foreground/70" strokeWidth={1.75} />}
            </span>
            <h2 className="mt-4 font-brand text-[24px] font-semibold tracking-[-0.02em] text-foreground">{channel.name}</h2>
            <p className="mt-1 max-w-[80ch] text-[14.5px] leading-relaxed text-muted-foreground">{channel.topic ? channel.topic : `This is the very beginning of #${channel.name}.`}</p>
            {after}
            {here.length > 0 && (
                <JoinLine verb="joined" names={here.map((m) => m.name)} where={`#${channel.name}`} className="mt-4 px-0" testId="channel-intro-members" />
            )}
            {agents.length > 0
                ? channel.mode === 'mentions' && <p className="mt-4 text-[13px] text-muted-foreground">{modeLine(channel.mode, agents, { named: false })}.</p>
                : <p className="mt-4 text-[13px] text-muted-foreground">No agents here yet: add one from the members menu, or with /invite.</p>}
            <ScheduleLines schedules={schedules} />
        </div>
    );
}

/** NoClick's mark where a member's avatar would be. */
function NoClickAvatar() {
    return (
        <span aria-hidden className="grid h-8 w-8 place-items-center rounded-full bg-foreground/[0.07]">
            <LogoMark alt="" className={cn('h-4 w-4', MARK_IN_A_SHAPE)} />
        </span>
    );
}

function AppAvatar() {
    return (
        <span aria-hidden className="grid h-8 w-8 place-items-center rounded-full bg-foreground/[0.07]">
            <Plug className="h-4 w-4 text-foreground/70" strokeWidth={1.75} />
        </span>
    );
}

type JumpTarget = 'latest' | 'start' | { day: string };

/** A day's label on its hairline; it stays pinned while you read that day and jumps between days. */
function DayPill({ label, earlier, onJump }: { label: string; earlier: { day: string; label: string }[]; onJump: (target: JumpTarget) => void }) {
    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                aria-label={`${label}, jump to another day`}
                className="pointer-events-auto relative inline-flex h-7 items-center gap-1 rounded-full bg-background pl-3 pr-2 text-[12.5px] font-medium text-foreground/80 shadow-[0_1px_2px_rgba(0,0,0,0.05)] ring-1 ring-inset ring-border transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring data-[state=open]:bg-muted data-[state=open]:text-foreground dark:ring-foreground/[0.12]"
            >
                {label}
                <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" strokeWidth={2} />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="center" sideOffset={6} className="min-w-[200px] rounded-xl p-1">
                <DropdownMenuLabel className="px-2.5 pb-1 pt-1.5 text-[12px] font-medium text-muted-foreground">Jump to</DropdownMenuLabel>
                <DropdownMenuItem onSelect={() => onJump('latest')} className="rounded-lg px-2.5 py-1.5 text-[13.5px]">
                    Most recent
                </DropdownMenuItem>
                {earlier.map((d) => (
                    <DropdownMenuItem key={d.day} onSelect={() => onJump({ day: d.day })} className="rounded-lg px-2.5 py-1.5 text-[13.5px]">
                        {d.label}
                    </DropdownMenuItem>
                ))}
                <DropdownMenuItem onSelect={() => onJump('start')} className="rounded-lg px-2.5 py-1.5 text-[13.5px]">
                    The earliest loaded
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    );
}

/** The emoji picker for a reaction, from a message's hover bar or the end of its reactions. */
function ReactionPicker({ onPick, className, label, onOpenChange }: { onPick: (emoji: string) => void; className?: string; label: string; onOpenChange?: (open: boolean) => void }) {
    const [open, setOpenState] = useState(false);
    const setOpen = (next: boolean) => {
        setOpenState(next);
        onOpenChange?.(next);
    };
    return (
        <Popover open={open} onOpenChange={setOpen}>
            <Tooltip>
                <TooltipTrigger asChild>
                    <PopoverTrigger aria-label={label} className={className}>
                        <SmilePlus className="h-4 w-4" strokeWidth={1.75} />
                    </PopoverTrigger>
                </TooltipTrigger>
                <TooltipContent side="top" sideOffset={6} className="rounded-lg px-2 py-1 text-[12.5px]">
                    {label}
                </TooltipContent>
            </Tooltip>
            <PopoverContent side="top" align="start" sideOffset={8} collisionPadding={12} className="w-auto rounded-2xl p-0">
                <EmojiPicker
                    onPick={(emoji) => {
                        onPick(emoji.char);
                        setOpen(false);
                    }}
                />
            </PopoverContent>
        </Popover>
    );
}

/** Who reacted, you first with how to take yours back, as Slack lists them. */
function reactedBy(r: ChannelReaction): string[] {
    const others = r.names.filter((n) => n !== 'You');
    return r.mine ? ['You (click to remove)', ...others] : others;
}

function Reactions({ reactions, onReact }: { reactions: ChannelReaction[]; onReact: (emoji: string) => void }) {
    return (
        <div className="mt-1.5 flex flex-wrap items-center gap-1" data-testid="message-reactions">
            {reactions.map((r) => (
                <Tooltip key={r.emoji}>
                    <TooltipTrigger asChild>
                        <button
                            type="button"
                            onClick={() => onReact(r.emoji)}
                            aria-pressed={r.mine}
                            aria-label={`${r.emoji} ${r.count}${r.mine ? ', yours' : ''}`}
                            className={cn(
                                'inline-flex h-7 items-center gap-1 rounded-full px-2 text-[13px] tabular-nums ring-1 ring-inset transition-colors',
                                r.mine ? 'bg-foreground/[0.08] text-foreground ring-foreground/30' : 'bg-foreground/[0.03] text-foreground/75 ring-foreground/[0.08] hover:bg-foreground/[0.06]'
                            )}
                        >
                            <span className="text-[15px] leading-none">{r.emoji}</span>
                            {r.count}
                        </button>
                    </TooltipTrigger>
                    <TooltipContent side="top" sideOffset={6} className="w-max max-w-[15rem] rounded-2xl border-border px-3 pb-3 pt-3 text-center shadow-xl dark:border-foreground/[0.1]">
                        <span className="mx-auto mb-2 grid h-12 w-12 place-items-center rounded-xl bg-foreground/[0.06] text-[28px] leading-none" aria-hidden>
                            {r.emoji}
                        </span>
                        <span className="block text-[13px] leading-snug text-muted-foreground">
                            {reactedBy(r).map((n, i, all) => (
                                <Fragment key={`${n}:${i}`}>
                                    {i > 0 && (i === all.length - 1 ? ' and ' : ', ')}
                                    <span className="font-semibold text-foreground">{n}</span>
                                </Fragment>
                            ))}{' '}
                            reacted with {r.emoji}
                        </span>
                    </TooltipContent>
                </Tooltip>
            ))}
            <ReactionPicker
                onPick={onReact}
                label="Add a reaction"
                className="grid h-7 w-7 place-items-center rounded-full text-muted-foreground ring-1 ring-inset ring-foreground/[0.08] transition-colors hover:bg-foreground/[0.06] hover:text-foreground"
            />
        </div>
    );
}

/** An agent passing the work on, as a row of its own under its message: its face to the next one's, and that agent's
 *  name in the colour its @-mention reads in, working while it is. */
function Handoffs({ from, to, user }: { from: ChannelMember; to: ChannelMember[]; user: AccountMenuUser }) {
    return (
        <div className="mt-2.5 flex flex-wrap gap-1.5">
            {to.map((h) => (
                <span
                    key={h.id}
                    className="inline-flex h-8 max-w-full items-center gap-2 rounded-full bg-foreground/[0.05] pl-1 pr-3.5 text-[13.5px] ring-1 ring-inset ring-foreground/[0.08]"
                    data-testid="channel-handoff"
                >
                    <span className="flex shrink-0 items-center">
                        <MemberAvatar member={from} user={user} size={24} />
                        <ArrowRight className="mx-1 h-3.5 w-3.5 text-muted-foreground" strokeWidth={2} />
                        <MemberAvatar member={h} user={user} size={24} />
                    </span>
                    <span className="shrink-0 text-foreground/75">Handed off to</span>
                    <span className={cn('min-w-0 truncate font-semibold', h.kind === 'agent' ? MENTION_HUE[h.hue ?? AGENT_HUES[0]] : 'text-foreground')}>{h.name}</span>
                    {h.busy && <span className="shrink-0 text-muted-foreground">· working</span>}
                </span>
            ))}
        </div>
    );
}

/** What a page that keeps threads and pins (Work) lets you do with a channel's message. */
export interface MessageActions {
    /** Open its thread beside the channel. */
    onThread?: (messageId: string) => void;
    /** Pin it, or take its pin off. */
    onPin?: (message: ChannelMessage) => void;
    onCopyLink?: (messageId: string) => void;
    /** Pins' own tab, from a pin's line in the timeline. */
    onSeePins?: () => void;
    /** A pin's line opens the message it pinned. */
    onOpenMessage?: (messageId: string) => void;
    /** The message a jump just landed on, lit for a moment. */
    lit?: string | null;
}

/** The emoji a person reaches for most, first in the hover bar as in Slack. */
const QUICK_EMOJI = ['✅', '👀', '🙌'];
const TOOL = 'grid h-8 w-8 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/70';
const LINKISH = 'rounded-full underline decoration-muted-foreground/40 underline-offset-2 transition-colors hover:text-foreground hover:decoration-foreground/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/70';

/** A person's first name, as Slack's quiet lines say it. */
const firstName = (author: ChannelAuthor, members: ChannelMember[]) => (author.type === 'account' && !author.id ? 'You' : (authorMember(author, members)?.name ?? author.name).split(' ')[0]);

/** How far above its message the hover bar rises (`-top-4`). */
const BAR_RISE = 16;

/** What scrolls `el`: the nearest ancestor whose overflow scrolls. */
function scrollerOf(el: HTMLElement): HTMLElement | null {
    for (let up = el.parentElement; up; up = up.parentElement) if (/(auto|scroll)/.test(getComputedStyle(up).overflowY)) return up;
    return null;
}

/** Whether a bar above `row` shows whole: below the top of what scrolls it, and below its day's pill stuck there. */
function roomAbove(row: HTMLElement): boolean {
    const top = row.getBoundingClientRect().top - BAR_RISE;
    const day = row.closest('section')?.querySelector<HTMLElement>('[data-testid="day-divider"]');
    return top >= Math.max(scrollerOf(row)?.getBoundingClientRect().top ?? -Infinity, day?.getBoundingClientRect().bottom ?? -Infinity);
}

/** A message's hover bar, as Slack's: quick emoji, more emoji, reply in thread, more (pin, copy link). Above the
 *  message, or in its top corner where nothing shows above it (the first of a day, or one at the top of the list). */
function HoverBar({ msg, actions, onReact }: { msg: ChannelMessage; actions: MessageActions; onReact: (emoji: string) => void }) {
    // Stays up while one of its menus is open, which takes the focus away from it.
    const [held, setHeld] = useState(false);
    const [inside, setInside] = useState(false);
    const bar = useRef<HTMLDivElement>(null);
    // Placed as it shows: when the pointer comes onto its message or focus goes into it, and as the list scrolls under it.
    useEffect(() => {
        const row = bar.current?.parentElement;
        if (!row) return;
        const place = () => setInside(!roomAbove(row));
        let scroller: HTMLElement | null = null;
        const leave = () => scroller?.removeEventListener('scroll', place);
        const enter = () => {
            place();
            leave();
            scroller = scrollerOf(row);
            scroller?.addEventListener('scroll', place, { passive: true });
        };
        row.addEventListener('pointerenter', enter);
        row.addEventListener('pointerleave', leave);
        row.addEventListener('focusin', place);
        return () => {
            row.removeEventListener('pointerenter', enter);
            row.removeEventListener('pointerleave', leave);
            row.removeEventListener('focusin', place);
            leave();
        };
    }, []);
    const threads = !!actions.onThread && !msg.threadId;
    return (
        <div
            ref={bar}
            className={cn(
                'absolute right-5 z-20 items-center gap-0.5 rounded-full bg-popover p-0.5 shadow-sm ring-1 ring-border dark:ring-foreground/[0.12]',
                inside ? 'top-1' : '-top-4',
                held ? 'flex' : 'hidden group-focus-within:flex group-hover:flex'
            )}
            data-placement={inside ? 'inside' : 'above'}
            data-testid="message-actions"
        >
            {threads &&
                QUICK_EMOJI.map((e) => (
                    <button key={e} type="button" aria-label={`React ${e}`} onClick={() => onReact(e)} className={cn(TOOL, 'text-[16px]')}>
                        {e}
                    </button>
                ))}
            {threads && <span className="mx-0.5 h-4 border-l border-foreground/15" aria-hidden />}
            <ReactionPicker onPick={onReact} label="More emoji" className={TOOL} onOpenChange={setHeld} />
            {threads && (
                <button type="button" aria-label="Reply in thread" title="Reply in thread" onClick={() => actions.onThread?.(msg.id)} className={TOOL}>
                    <MessageSquareText className="h-[17px] w-[17px]" strokeWidth={2} />
                </button>
            )}
            {(actions.onPin || actions.onCopyLink) && (
                <DropdownMenu onOpenChange={setHeld}>
                    <DropdownMenuTrigger aria-label="More" title="More" className={cn(TOOL, 'data-[state=open]:bg-foreground/[0.06] data-[state=open]:text-foreground')}>
                        <MoreHorizontal className="h-[17px] w-[17px]" />
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" sideOffset={6} className="w-[220px] rounded-xl p-1">
                        {actions.onPin && !msg.threadId && (
                            <DropdownMenuItem onSelect={() => actions.onPin?.(msg)} className="gap-2.5 rounded-lg px-2.5 py-2 text-sm">
                                {msg.pinned ? <PinOff className="h-4 w-4 text-muted-foreground" strokeWidth={1.9} /> : <Pin className="h-4 w-4 text-muted-foreground" strokeWidth={1.9} />}
                                {msg.pinned ? 'Unpin from channel' : 'Pin to channel'}
                            </DropdownMenuItem>
                        )}
                        {actions.onCopyLink && (
                            <DropdownMenuItem onSelect={() => actions.onCopyLink?.(msg.id)} className="gap-2.5 rounded-lg px-2.5 py-2 text-sm">
                                <Link2 className="h-4 w-4 text-muted-foreground" strokeWidth={1.9} />
                                Copy link
                            </DropdownMenuItem>
                        )}
                    </DropdownMenuContent>
                </DropdownMenu>
            )}
        </div>
    );
}

/** Under a message with a thread, Slack's replies bar: who replied, "N replies", when the last came; hovering it says
 *  "View thread". */
function RepliesBar({ msg, members, user, onOpen }: { msg: ChannelMessage; members: ChannelMember[]; user: AccountMenuUser; onOpen: () => void }) {
    const thread = msg.thread;
    if (!thread?.count) return null;
    return (
        <button
            type="button"
            onClick={onOpen}
            data-testid="replies-bar"
            className="group/replies -ml-1.5 mt-1 flex w-[calc(100%+0.375rem)] max-w-[30rem] items-center gap-2 rounded-full border border-transparent py-[6px] pl-[6px] pr-2.5 text-left text-xs transition-colors hover:border-border hover:bg-foreground/[0.06] focus-visible:border-border focus-visible:bg-foreground/[0.06] focus-visible:outline-none dark:hover:border-foreground/[0.08] dark:focus-visible:border-foreground/[0.08]"
        >
            <span className="flex shrink-0 gap-1">
                {thread.authors.slice(0, 5).map((a, i) => {
                    const face = authorMember(a, members);
                    return face ? <MemberAvatar key={`${a.type}:${a.id ?? a.name}:${i}`} member={face} user={user} size={24} className="h-[22px] w-[22px] text-[10px]" /> : null;
                })}
            </span>
            <span className="shrink-0 font-semibold text-foreground">
                {thread.count} {thread.count === 1 ? 'reply' : 'replies'}
            </span>
            {thread.unread > 0 && <span className="shrink-0 rounded-full bg-foreground px-1.5 text-[11px] font-semibold leading-[18px] text-background">{thread.unread} new</span>}
            <span className="relative min-w-0 flex-1 truncate text-muted-foreground">
                <span className="group-hover/replies:hidden group-focus-visible/replies:hidden">{thread.lastAt ? `Last reply ${timeLabel(thread.lastAt)}` : ''}</span>
                <span className="hidden group-hover/replies:inline group-focus-visible/replies:inline">View thread</span>
            </span>
            <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground opacity-0 transition-opacity duration-150 group-hover/replies:opacity-100 group-focus-visible/replies:opacity-100" strokeWidth={2} />
        </button>
    );
}

/** Who pinned: the pinned message's own pin where it's in view (so you read your pin as yours), else NoClick's line,
 *  which names them ("Priya Shah pinned a message…"). */
function pinnerOf(msg: ChannelMessage, target: ChannelMessage | undefined, members: ChannelMember[]): string {
    if (target?.pinned) return firstName(target.pinned.by, members);
    const named = /^(.+?) pinned a message/.exec(msg.text)?.[1];
    return named ? named.split(' ')[0] : firstName(msg.author, members);
}

/** The quiet line pinning leaves in the timeline, as Slack's. */
/** Names as a line reads them: "Priya", "Priya and Tom", "Priya, Tom and Sam", past three "Priya, Tom and 2 others"
 *  (the others named on hover). */
function Names({ names }: { names: string[] }) {
    const shown = names.length > 3 ? names.slice(0, 2) : names;
    const rest = names.slice(shown.length);
    const parts: ReactNode[] = shown.map((name, i) => (
        <span key={i} className="font-medium text-foreground/80">
            {name}
        </span>
    ));
    if (rest.length)
        parts.push(
            <Tooltip key="rest">
                <TooltipTrigger asChild>
                    <button type="button" className={cn(LINKISH, 'font-medium text-foreground/80')}>
                        {rest.length} others
                    </button>
                </TooltipTrigger>
                <TooltipContent side="top" sideOffset={6} className="rounded-lg px-2 py-1 text-[12.5px]">
                    {new Intl.ListFormat('en', { type: 'conjunction' }).format(rest)}
                </TooltipContent>
            </Tooltip>
        );
    return (
        <>
            {parts.map((part, i) => (
                <Fragment key={i}>
                    {i > 0 && (i === parts.length - 1 ? ' and ' : ', ')}
                    {part}
                </Fragment>
            ))}
        </>
    );
}

/** Who joined, as Slack draws it: a quiet line, its mark under the faces. "Priya, Tom and 2 others joined #launch",
 *  "You added Growth and Support". */
function JoinLine({
    verb,
    names,
    where,
    at,
    className,
    testId = 'join-line',
}: {
    verb: 'joined' | 'added' | 'removed';
    names: string[];
    /** Where they joined (`#launch`), for `joined`. */
    where?: string;
    at?: string;
    className?: string;
    testId?: string;
}) {
    const Mark = verb === 'removed' ? UserMinus : UserPlus;
    return (
        <div className={cn('flex items-center gap-3 py-1.5 text-xs text-muted-foreground', GUTTER, className)} data-testid={testId}>
            <span className="grid w-8 shrink-0 place-items-center">
                <Mark className="h-3.5 w-3.5" strokeWidth={2} />
            </span>
            <span className="min-w-0">
                {verb === 'joined' ? (
                    <>
                        <Names names={names} /> joined {where}
                    </>
                ) : (
                    <>
                        You {verb} <Names names={names} />
                    </>
                )}
                {at && (
                    <>
                        {' '}
                        · <time className="tabular-nums">{timeLabel(at)}</time>
                    </>
                )}
            </span>
        </div>
    );
}

function PinLine({ msg, target, members, actions }: { msg: ChannelMessage; target?: ChannelMessage; members: ChannelMember[]; actions: MessageActions }) {
    const pinned = msg.event?.messageId;
    return (
        <div className={cn('flex items-center gap-3 py-1.5 text-xs text-muted-foreground', GUTTER)} data-testid="pin-line">
            <span className="grid w-8 shrink-0 place-items-center">
                <Pin className="h-3.5 w-3.5" strokeWidth={2} />
            </span>
            <span className="min-w-0 truncate">
                <span className="font-medium text-foreground/80">{pinnerOf(msg, target, members)}</span> pinned{' '}
                {pinned && actions.onOpenMessage ? (
                    <button type="button" onClick={() => actions.onOpenMessage?.(pinned)} className={LINKISH}>
                        a message
                    </button>
                ) : (
                    'a message'
                )}{' '}
                to this channel · <time className="tabular-nums">{timeLabel(msg.at)}</time>
            </span>
            {actions.onSeePins && (
                <button type="button" onClick={actions.onSeePins} className={cn(LINKISH, 'ml-auto shrink-0')}>
                    See all pins
                </button>
            )}
        </div>
    );
}

export function MessageRow({
    msg,
    prev,
    members,
    user,
    channels,
    onChannel,
    onReact,
    onDismiss,
    actions = {},
    compact,
    pinTarget,
}: {
    msg: ChannelMessage;
    prev?: ChannelMessage;
    members: ChannelMember[];
    user: AccountMenuUser;
    channels: ReadonlyMap<string, string>;
    onChannel: (id: string) => void;
    onReact: (messageId: string, emoji: string) => void;
    onDismiss: (messageId: string) => void;
    actions?: MessageActions;
    /** A narrow column (a thread beside its channel): a smaller gutter. */
    compact?: boolean;
    /** For a pin's line, the message it pinned, where it's loaded. */
    pinTarget?: ChannelMessage;
}) {
    if (msg.event?.type === 'pinned') return <PinLine msg={msg} target={pinTarget} members={members} actions={actions} />;
    if (msg.membership) return <JoinLine verb={msg.membership.verb} names={msg.membership.names} at={msg.at} />;
    const noclick = byNoClick(msg.author);
    const app = msg.author.type === 'app';
    const author = authorMember(msg.author, members);
    const handoffs = handoffsOf(msg.author, msg.mentions, members);
    const continued =
        !!prev &&
        !prev.event &&
        !msg.pinned &&
        localDay(prev.at) === localDay(msg.at) &&
        authorKey(prev) === authorKey(msg) &&
        !prev.ephemeral &&
        !msg.ephemeral &&
        Date.parse(msg.at) - Date.parse(prev.at) < GROUP_WINDOW_MS;
    const canReact = !msg.ephemeral && !msg.pending;
    const lit = actions.lit === msg.id;
    return (
        <div
            className={cn(
                'group relative flex gap-3 transition-colors hover:bg-foreground/[0.03]',
                compact ? 'px-4' : GUTTER,
                continued ? 'py-1' : 'mt-1 pb-1.5 pt-2',
                msg.pending && 'opacity-60',
                msg.pinned && 'bg-foreground/[0.035] pt-7 hover:bg-foreground/[0.05]',
                lit && 'bg-foreground/[0.1] duration-1000 hover:bg-foreground/[0.1]'
            )}
            data-testid="channel-message"
            data-message-id={msg.id}
        >
            {msg.pinned && (
                <p className={cn('pointer-events-none absolute left-0 top-1.5 flex items-center gap-1.5 text-xs text-muted-foreground', compact ? 'pl-[60px]' : 'pl-[64px]')}>
                    <Pin className="h-3 w-3" strokeWidth={2} />
                    Pinned by {firstName(msg.pinned.by, members)}
                </p>
            )}
            <div className="w-8 shrink-0 pt-0.5">
                {continued ? (
                    // On the first line's baseline, never wrapping; the whole time on hover.
                    <Tooltip>
                        <TooltipTrigger asChild>
                            <time dateTime={msg.at} className="hidden whitespace-nowrap text-center text-[10.5px] leading-6 tabular-nums text-muted-foreground group-hover:block" data-testid="gutter-time">
                                {clockLabel(msg.at)}
                            </time>
                        </TooltipTrigger>
                        <TooltipContent side="top" sideOffset={6} className="rounded-lg px-2 py-1 text-[12.5px]">
                            {timeLabel(msg.at)}
                        </TooltipContent>
                    </Tooltip>
                ) : noclick ? (
                    <NoClickAvatar />
                ) : app ? (
                    <AppAvatar />
                ) : (
                    author && <MemberAvatar member={author} user={user} />
                )}
            </div>
            <div className="min-w-0 flex-1">
                {!continued && (
                    <div className="mb-0.5 flex flex-wrap items-baseline gap-x-2">
                        <span className="text-[14.5px] font-semibold text-foreground">{noclick ? NOCLICK_NAME : (author?.name ?? msg.author.name)}</span>
                        {app && <span className="text-[12.5px] text-muted-foreground">app</span>}
                        {msg.author.type === 'a2a' && <span className="text-[12.5px] text-muted-foreground">outside agent</span>}
                        {postedForYou(msg.author) && <span className="text-[12.5px] text-muted-foreground">for you</span>}
                        {author?.workflowName && <span className="text-[12.5px] text-muted-foreground">{author.workflowName}</span>}
                        <time className="text-[12px] tabular-nums text-muted-foreground/80">{msg.pending ? 'Sending…' : timeLabel(msg.at)}</time>
                        {msg.ephemeral && (
                            <span className="flex items-center gap-1.5 text-[12px] text-muted-foreground">
                                <EyeOff className="h-3.5 w-3.5 self-center" strokeWidth={1.75} />
                                Only visible to you
                                <span aria-hidden>·</span>
                                <button
                                    type="button"
                                    onClick={() => onDismiss(msg.id)}
                                    className="font-medium text-foreground/70 underline-offset-[3px] transition-colors hover:text-foreground hover:underline"
                                >
                                    Dismiss
                                </button>
                            </span>
                        )}
                    </div>
                )}
                {msg.text && <MessageBody text={msg.text} members={members} channels={channels} onChannel={onChannel} muted={msg.author.type === 'system' && !msg.ephemeral} />}
                {msg.attachments.length ? <MessageAttachments attachments={msg.attachments} /> : null}
                {author && handoffs.length > 0 && <Handoffs from={author} to={handoffs} user={user} />}
                {canReact && msg.reactions.length > 0 && <Reactions reactions={msg.reactions} onReact={(emoji) => onReact(msg.id, emoji)} />}
                {actions.onThread && !msg.threadId && <RepliesBar msg={msg} members={members} user={user} onOpen={() => actions.onThread?.(msg.id)} />}
            </div>
            {canReact && <HoverBar msg={msg} actions={actions} onReact={(emoji) => onReact(msg.id, emoji)} />}
        </div>
    );
}

export function MessageList({
    channel,
    schedules,
    messages,
    members,
    user,
    channels,
    older,
    loadingOlder,
    onLoadOlder,
    onChannel,
    onReact,
    onDismiss,
    actions,
    intro,
    introMark,
    introAfter,
}: {
    channel: Channel;
    /** The schedules that post in it. */
    schedules: ChannelSchedule[];
    messages: ChannelMessage[];
    members: ChannelMember[];
    user: AccountMenuUser;
    /** The workspace's channels by name, so a #name in a message can open it. */
    channels: ReadonlyMap<string, string>;
    /** Older messages wait to be read. */
    older: boolean;
    loadingOlder: boolean;
    onLoadOlder: () => void;
    onChannel: (id: string) => void;
    onReact: (messageId: string, emoji: string) => void;
    onDismiss: (messageId: string) => void;
    actions?: MessageActions;
    /** Where the conversation starts, in place of a channel's (a DM's: the other person). */
    intro?: ReactNode;
    /** In place of the # on a channel's own start (NoClick's mark on its channel). */
    introMark?: ReactNode;
    /** What follows a channel's own start, under its topic. */
    introAfter?: ReactNode;
}) {
    const root = useRef<HTMLDivElement>(null);
    const today = localDay(new Date().toISOString());
    const days = useMemo(() => {
        const out: { day: string; label: string; items: { msg: ChannelMessage; prev?: ChannelMessage }[] }[] = [];
        messages.forEach((msg, i) => {
            const day = localDay(msg.at);
            const item = { msg, prev: messages[i - 1] };
            const last = out[out.length - 1];
            // A run of adds (or of removals) is one line, as Slack folds joins.
            const before = last?.day === day ? last.items[last.items.length - 1] : undefined;
            const was = before?.msg.membership;
            if (msg.membership && was?.verb === msg.membership.verb) {
                before!.msg = { ...before!.msg, membership: { ...was, names: [...was.names, ...msg.membership.names.filter((n) => !was.names.includes(n))] } };
                return;
            }
            if (last?.day === day) last.items.push(item);
            else out.push({ day, label: dayLabel(day, today), items: [item] });
        });
        return out;
    }, [messages, today]);
    // "Most recent" covers the newest day; the menu lists the ones before it, newest first.
    const earlier = useMemo(() => days.slice(0, -1).reverse(), [days]);
    const byId = useMemo(() => new Map(messages.map((m) => [m.id, m])), [messages]);

    const jump = (target: JumpTarget) => {
        const el = root.current;
        if (!el) return;
        const behavior = window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth';
        if (target === 'latest') el.lastElementChild?.scrollIntoView({ block: 'end', behavior });
        else if (target === 'start') el.firstElementChild?.scrollIntoView({ block: 'start', behavior });
        else el.querySelector(`[data-day="${target.day}"]`)?.scrollIntoView({ block: 'start', behavior });
    };

    return (
        <div ref={root} className="flex flex-1 flex-col justify-end">
            {intro && !older ? intro : <Intro channel={channel} schedules={schedules} members={members} older={older} loadingOlder={loadingOlder} onLoadOlder={onLoadOlder} mark={introMark} after={introAfter} />}
            {days.map(({ day, label, items }) => (
                <section key={day} data-day={day} aria-label={label} className="relative">
                    {/* The day's hairline and its pill pin to the top while the day is on screen, over a band of the
                        page's own colour that fades out below: a line scrolling up passes under it, never behind the pill. */}
                    <div className="pointer-events-none sticky top-0 z-10 flex justify-center pb-2 pt-3" data-testid="day-divider">
                        <span aria-hidden className="absolute inset-0 bg-background after:absolute after:inset-x-0 after:top-full after:h-3 after:bg-gradient-to-b after:from-background after:to-transparent" />
                        <span aria-hidden className="absolute inset-x-0 top-[26px] h-px bg-border dark:bg-foreground/[0.08]" />
                        <DayPill label={label} earlier={earlier} onJump={jump} />
                    </div>
                    {items.map(({ msg, prev }) => (
                        <MessageRow
                            key={msg.id}
                            msg={msg}
                            prev={prev}
                            members={members}
                            user={user}
                            channels={channels}
                            onChannel={onChannel}
                            onReact={onReact}
                            onDismiss={onDismiss}
                            actions={actions}
                            pinTarget={msg.event?.type === 'pinned' ? byId.get(msg.event.messageId) : undefined}
                        />
                    ))}
                </section>
            ))}
        </div>
    );
}
