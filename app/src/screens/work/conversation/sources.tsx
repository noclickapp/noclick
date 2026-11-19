// Where each message of an agent's one session came from, where that isn't the session's own box: one texted or
// emailed draws as that app did (the coordinator's WhatsAppTurn, IMessageTurn, EmailTurn) with the app its reply went
// back on (RepliedOn); one from a channel, a shared page's visitor, an app's code or another conversation carries a
// small chip naming it; and the agent's quiet work (a check-in, an event it looked into) folds to one card, never a
// message to anyone. Work's agent view and the Chat page both draw a session with these.
import { useState, type ReactNode } from 'react';
import { AppWindow, ChevronRight, Hash, Link2, Mail, MessageCircle, MoonStar } from 'lucide-react';
import { EmailTurn, IMessageTurn, WhatsAppTurn, type TurnMessage } from './turns';
import { cn } from '@/ui/utils';
import { stepsOf, type Thread, type TurnEntry, type UserEntry } from '@/lib/agentThread/thread';
import { clockOf } from './styles';
import { channelOfChat } from './sessions';

/** The chat an agent's quiet work runs in (the platform's `wakeups.QUIET_CHAT`): its reply reaches no one. */
export const QUIET_CHAT = 'background';

// A message that came by an app, as that app's bubble draws it; and a reply's caption for the app it went back on.
const CHANNEL: Record<string, string> = { whatsapp: 'whatsapp_text', imessage: 'imessage_text', email: 'email', call: 'voice' };
const REPLIED: Record<string, 'whatsapp' | 'imessage' | 'email'> = { whatsapp: 'whatsapp', imessage: 'imessage', email: 'email' };

export const bubbleOf = (e: UserEntry): TurnMessage & { isUser: true; isComplete: true; channel?: string } => ({ isUser: true, text: e.text, isComplete: true, sentAt: e.at, channel: e.via ? CHANNEL[e.via] : undefined });

/** A person's message that came by text or email, as that app drew it; undefined for any other. */
export function viaBubble(e: UserEntry): ReactNode | undefined {
    if (e.trigger && !e.author) return undefined;
    if (e.via === 'whatsapp') return <WhatsAppTurn msg={bubbleOf(e)} />;
    if (e.via === 'imessage') return <IMessageTurn msg={bubbleOf(e)} />;
    if (e.via === 'email') return <EmailTurn msg={bubbleOf(e)} />;
    return undefined;
}

/** The app each turn's message came by, by the turn's key. */
export function cameByOf(thread: Thread): Map<string, UserEntry['via']> {
    const by = new Map<string, UserEntry['via']>();
    let via: UserEntry['via'] = null;
    for (const e of thread.entries) {
        if (e.kind === 'user') via = e.trigger ? null : e.via;
        else if (e.kind === 'turn') by.set(e.key, via);
    }
    return by;
}

/** The app a turn's reply went back out on: the newest message it took's (one that joined it, else the one that
 *  started it); none for a turn that said nothing. */
export function repliedOn(turn: TurnEntry, cameBy: ReadonlyMap<string, UserEntry['via']>): 'whatsapp' | 'imessage' | 'email' | undefined {
    const joined = [...turn.parts].reverse().find((p) => p.kind === 'user');
    const via = joined?.kind === 'user' ? joined.entry.via : cameBy.get(turn.key);
    return turn.reply ? REPLIED[via ?? ''] : undefined;
}

const CHIP = 'inline-flex h-5 max-w-full items-center gap-1 rounded-full bg-foreground/[0.05] px-2 text-[11px] leading-4 text-muted-foreground';

/** Where a person's message came from when it isn't the session's own box nor an app's bubble: a channel (opening it),
 *  a shared page's visitor, an app's code, another conversation. Null for the session's own. */
export function SourceChip({ chat, channelName, onOpenChannel }: { chat: string | null; channelName?: (id: string) => string | null; onOpenChannel?: (id: string) => void }) {
    if (!chat || chat === QUIET_CHAT) return null;
    const channel = channelOfChat(chat);
    if (channel) {
        const name = channelName?.(channel);
        const label = (
            <>
                <Hash className="h-3 w-3 shrink-0" strokeWidth={2} />
                <span className="truncate">{name ?? 'a channel'}</span>
            </>
        );
        return onOpenChannel ? (
            <button type="button" onClick={() => onOpenChannel(channel)} className={cn(CHIP, 'transition-colors hover:bg-foreground/[0.08] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/70')} data-source="channel">
                {label}
            </button>
        ) : (
            <span className={CHIP} data-source="channel">
                {label}
            </span>
        );
    }
    const [Icon, label, kind] = chat.startsWith('share:')
        ? [Link2, 'On its shared page', 'share']
        : chat.startsWith('app:')
          ? [AppWindow, 'From your app', 'app']
          : chat.startsWith('inbox:')
            ? [Mail, 'By email', 'email']
            : chat === 'owner'
              ? [MessageCircle, 'In Chat', 'owner']
              : [MessageCircle, `In “${chat}”`, 'conversation'];
    return (
        <span className={CHIP} data-source={kind}>
            <Icon className="h-3 w-3 shrink-0" strokeWidth={2} />
            <span className="truncate">{label}</span>
        </span>
    );
}

/** What a quiet turn did, in words after the agent's name: the event it looked into, or a check-in. */
export function quietWhat(entry: UserEntry): string {
    const trigger = entry.trigger;
    const data = trigger?.event?.data;
    const of = typeof data?.workflow_name === 'string' && data.workflow_name ? ` of ${data.workflow_name}` : '';
    if (trigger?.kind === 'platform' && trigger.event?.type === 'workflow.run.failed') return `checked a failed run${of}`;
    if (trigger?.kind === 'platform' && trigger.event?.type === 'agent.asked_owner') return 'looked at what an agent asked you';
    if (trigger?.kind === 'wakeup' || trigger?.kind === 'loop') return 'checked in';
    if (trigger) return `looked into ${trigger.title || 'an event'}`;
    return 'worked quietly';
}

/** A quiet turn folded to one line ("NoClick checked a failed run · 2 calls"), opening to the turn itself. */
export function QuietTurn({ entry, turn, name, children }: { entry: UserEntry; turn: TurnEntry | null; name: string; children: ReactNode }) {
    const [open, setOpen] = useState(false);
    const calls = turn ? stepsOf(turn).length : 0;
    const state = turn?.status === 'running' ? 'working' : turn?.status === 'failed' ? 'didn’t finish' : null;
    return (
        <div className="px-1 pt-3" data-row="quiet">
            <button
                type="button"
                onClick={() => setOpen(!open)}
                aria-expanded={open}
                disabled={!turn}
                className="flex w-full min-w-0 items-center gap-2 rounded-full bg-foreground/[0.03] py-1.5 pl-3 pr-2.5 text-left text-[13px] text-muted-foreground transition-colors hover:bg-foreground/[0.06] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/70 disabled:pointer-events-none"
            >
                <MoonStar className="h-3.5 w-3.5 shrink-0" strokeWidth={2} />
                <span className="min-w-0 flex-1 truncate">
                    <span className="text-foreground/85">{name}</span> {quietWhat(entry)}
                    {calls > 0 && ` · ${calls} ${calls === 1 ? 'call' : 'calls'}`}
                    {state && <span className={cn(state === 'working' && 'work-shine')}> · {state}</span>}
                </span>
                <time className="shrink-0 text-xs tabular-nums" dateTime={new Date(entry.at).toISOString()}>
                    {clockOf(entry.at)}
                </time>
                {turn && <ChevronRight className={cn('h-3.5 w-3.5 shrink-0 transition-transform duration-200', open && 'rotate-90')} strokeWidth={2} />}
            </button>
            {open && turn && <div className="mt-1 border-l border-border pl-3 dark:border-foreground/[0.08]">{children}</div>}
        </div>
    );
}
