// A channel's history, edge to edge across the pane as in Slack: where it
// starts with its agents and their jobs, and its schedules (or the way to read
// further back), then each day under a hairline whose pill stays pinned while
// you read that day (and jumps between days). Consecutive messages from one
// author share a header; words render as markdown with their files under them,
// then their reactions. An agent that @-mentions another hands it the work, a
// row of its own; what an agent posted for you is signed by it; NoClick's
// notes in the room (why it halted) read as NoClick's, and an app's event as
// that app's. NoClick's answers to your commands are yours alone, and
// dismissable.
import { useMemo, useRef, useState } from 'react';
import { ArrowRight, ChevronDown, EyeOff, Hash, Plug, SmilePlus } from 'lucide-react';
import type { AccountMenuUser } from '~/components/nav/AccountMenu';
import { clockLabel } from '~/components/dashboard/primitives';
import { LogoMark } from '~/components/shared/LogoMark';
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
import type { Channel, ChannelMember, ChannelMessage, ChannelReaction, ChannelSchedule } from './types';

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

/** A key that says who wrote a message, for grouping. */
const authorKey = (m: ChannelMessage) => `${m.author.type}:${m.author.id ?? m.author.name}`;

function Intro({
    channel,
    schedules,
    agents,
    user,
    older,
    loadingOlder,
    onLoadOlder,
}: {
    channel: Channel;
    schedules: ChannelSchedule[];
    agents: ChannelMember[];
    user: AccountMenuUser;
    older: boolean;
    loadingOlder: boolean;
    onLoadOlder: () => void;
}) {
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
                <Hash className="h-6 w-6 text-foreground/70" strokeWidth={1.75} />
            </span>
            <h2 className="mt-4 font-brand text-[24px] font-semibold tracking-[-0.02em] text-foreground">{channel.name}</h2>
            <p className="mt-1 max-w-[80ch] text-[14.5px] leading-relaxed text-muted-foreground">{channel.topic ? channel.topic : `This is the very beginning of #${channel.name}.`}</p>
            {agents.length > 0 ? (
                <>
                    {/* Who's here: each agent by name, its job under it. */}
                    <ul className="mt-5 space-y-3" data-testid="channel-intro-agents">
                        {agents.map((a) => (
                            <li key={a.id} className="flex items-start gap-3">
                                <MemberAvatar member={a} user={user} size={28} />
                                <span className="min-w-0">
                                    <span className="block text-[14px] font-medium leading-snug text-foreground">{a.name}</span>
                                    {a.role && <span className="block text-[13px] leading-snug text-muted-foreground">{a.role}</span>}
                                </span>
                            </li>
                        ))}
                    </ul>
                    <p className="mt-4 text-[13px] text-muted-foreground">{modeLine(channel.mode, agents, { named: false })}.</p>
                </>
            ) : (
                <p className="mt-4 text-[13px] text-muted-foreground">No agents here yet: add one from the members menu, or with /invite.</p>
            )}
            <ScheduleLines schedules={schedules} />
        </div>
    );
}

/** NoClick's mark where a member's avatar would be. */
function NoClickAvatar() {
    return (
        <span aria-hidden className="grid h-8 w-8 place-items-center rounded-full bg-foreground/[0.07]">
            <LogoMark alt="" className="h-4 w-4" />
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
function ReactionPicker({ onPick, className, label }: { onPick: (emoji: string) => void; className?: string; label: string }) {
    const [open, setOpen] = useState(false);
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
                    <TooltipContent side="top" sideOffset={6} className="max-w-[240px] rounded-lg px-2 py-1 text-[12.5px]">
                        {new Intl.ListFormat('en', { type: 'conjunction' }).format(r.names)}
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

function MessageRow({
    msg,
    prev,
    members,
    user,
    channels,
    onChannel,
    onReact,
    onDismiss,
}: {
    msg: ChannelMessage;
    prev?: ChannelMessage;
    members: ChannelMember[];
    user: AccountMenuUser;
    channels: ReadonlyMap<string, string>;
    onChannel: (id: string) => void;
    onReact: (messageId: string, emoji: string) => void;
    onDismiss: (messageId: string) => void;
}) {
    const noclick = byNoClick(msg.author);
    const app = msg.author.type === 'app';
    const author = authorMember(msg.author, members);
    const handoffs = handoffsOf(msg.author, msg.mentions, members);
    const continued =
        !!prev &&
        localDay(prev.at) === localDay(msg.at) &&
        authorKey(prev) === authorKey(msg) &&
        !prev.ephemeral &&
        !msg.ephemeral &&
        Date.parse(msg.at) - Date.parse(prev.at) < GROUP_WINDOW_MS;
    const canReact = !msg.ephemeral && !msg.pending;
    return (
        <div
            className={cn('group relative flex gap-3 transition-colors hover:bg-foreground/[0.03]', GUTTER, continued ? 'py-1' : 'mt-1 pb-1.5 pt-2', msg.pending && 'opacity-60')}
            data-testid="channel-message"
        >
            <div className="w-8 shrink-0 pt-0.5">
                {continued ? (
                    <time className="hidden pt-1 text-center text-[10.5px] tabular-nums text-muted-foreground group-hover:block">{clockLabel(msg.at)}</time>
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
                        <time className="text-[12px] tabular-nums text-muted-foreground/80">{msg.pending ? 'Sending…' : clockLabel(msg.at)}</time>
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
            </div>
            {canReact && (
                <div className="absolute -top-3 right-5 hidden rounded-full bg-popover p-0.5 shadow-sm ring-1 ring-border group-focus-within:block group-hover:block dark:ring-foreground/[0.12]">
                    <ReactionPicker
                        onPick={(emoji) => onReact(msg.id, emoji)}
                        label="React"
                        className="grid h-7 w-7 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground"
                    />
                </div>
            )}
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
}) {
    const root = useRef<HTMLDivElement>(null);
    const agents = members.filter((m) => m.kind === 'agent');
    const today = localDay(new Date().toISOString());
    const days = useMemo(() => {
        const out: { day: string; label: string; items: { msg: ChannelMessage; prev?: ChannelMessage }[] }[] = [];
        messages.forEach((msg, i) => {
            const day = localDay(msg.at);
            const item = { msg, prev: messages[i - 1] };
            const last = out[out.length - 1];
            if (last?.day === day) last.items.push(item);
            else out.push({ day, label: dayLabel(day, today), items: [item] });
        });
        return out;
    }, [messages, today]);
    // "Most recent" covers the newest day; the menu lists the ones before it, newest first.
    const earlier = useMemo(() => days.slice(0, -1).reverse(), [days]);

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
            <Intro channel={channel} schedules={schedules} agents={agents} user={user} older={older} loadingOlder={loadingOlder} onLoadOlder={onLoadOlder} />
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
                        <MessageRow key={msg.id} msg={msg} prev={prev} members={members} user={user} channels={channels} onChannel={onChannel} onReact={onReact} onDismiss={onDismiss} />
                    ))}
                </section>
            ))}
        </div>
    );
}
