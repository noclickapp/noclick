// A message's thread beside its channel, as Slack's: the message, how many replies, the replies, and a box that
// follows them (right under a short thread, held at the foot while a long one scrolls), whose reply can go to the
// channel too. Read when it opens and again when a frame says a reply landed; opening it marks it read.
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { toast } from 'sonner';
import type { AccountMenuUser } from '@/ui/accountParts';
import { HAIRLINE } from '@/ui/primitives';
import { PhoneBarBack } from '@/ui/phoneBar';
import { ChannelComposer } from '@/screens/channels/ChannelComposer';
import { flipReaction, mergeMessages } from '@/screens/channels/useChannels';
import { YOU } from '@/screens/channels/model';
import type { Channel, ChannelMember, ChannelMessage } from '@/screens/channels/types';
import type { ChannelsTransport } from '@/screens/channels/transport';
import { cn } from '@/ui/utils';
import { useWorkFrames } from '@/sdk/live';
import { ChoiceMark, CloseButton, PanelFrame } from '../ui';
import { sentFiles, type Drafts } from './drafts';
import { PlainMessage } from './ChannelPane';
import type { ChannelShelf } from './shelf';

const errorText = (e: unknown) => (e instanceof Error ? e.message : 'Something went wrong.');

export function ThreadPanel({
    channel,
    parentId,
    parent,
    transport,
    shelf,
    drafts,
    members,
    user,
    byName,
    phone,
    onOpenChannel,
    onClose,
}: {
    channel: Channel;
    parentId: string;
    /** The parent as the channel's timeline holds it, when it does. */
    parent: ChannelMessage | undefined;
    transport: ChannelsTransport;
    shelf: ChannelShelf;
    drafts: Drafts;
    members: ChannelMember[];
    user: AccountMenuUser;
    byName: ReadonlyMap<string, string>;
    phone: boolean;
    onOpenChannel: (id: string) => void;
    onClose: () => void;
}) {
    const [replies, setReplies] = useState<ChannelMessage[]>([]);
    const [older, setOlder] = useState<string | null>(null);
    const [state, setState] = useState<{ loading: boolean; error: string | null }>({ loading: true, error: null });
    const [read, setRead] = useState<ChannelMessage | null>(null);
    const [also, setAlso] = useState(false);
    const textareaRef = useRef<HTMLTextAreaElement>(null);
    const scrollRef = useRef<HTMLDivElement>(null);
    const key = `thread:${parentId}`;
    const draft = drafts.get(key);
    const top = parent ?? read;
    const everyone = [YOU, ...members];

    const readNewest = useCallback(async () => {
        try {
            const page = await shelf.replies(channel.id, parentId);
            setReplies((prev) => mergeMessages(prev, page.messages));
            setOlder((prev) => prev ?? page.older);
            setState({ loading: false, error: null });
            void shelf.markThreadRead(channel.id, parentId).catch((e) => console.warn('[work] thread read failed:', e));
        } catch (e) {
            setState({ loading: false, error: errorText(e) });
        }
    }, [shelf, channel.id, parentId]);

    useEffect(() => {
        setReplies([]);
        setOlder(null);
        setState({ loading: true, error: null });
        void readNewest();
    }, [readNewest]);
    // A thread opened from a link may not be in the loaded timeline: read the message itself.
    useEffect(() => {
        if (parent) return;
        transport.message(channel.id, parentId).then(setRead, (e) => setState({ loading: false, error: errorText(e) }));
    }, [parent, transport, channel.id, parentId]);
    useWorkFrames('platform:channel', (frame) => {
        const thread = (frame as { thread_id?: string | null }).thread_id;
        if (frame.channel_id !== channel.id || thread !== parentId) return;
        if (frame.kind === 'reaction' && frame.message_id) {
            transport.message(channel.id, frame.message_id).then((m) => setReplies((prev) => mergeMessages(prev, [m])), (e) => console.warn('[work] reply failed:', e));
        } else void readNewest();
    });

    // At the newest reply as replies land, unless you scrolled up to read.
    const atEnd = useRef(true);
    useLayoutEffect(() => {
        const el = scrollRef.current;
        if (el && atEnd.current) el.scrollTop = el.scrollHeight;
    }, [replies.length, top]);

    const send = async () => {
        const text = draft.text.trim();
        if (!text && !draft.attachments.length) return;
        const sent = drafts.take(key);
        atEnd.current = true;
        try {
            const reply = await shelf.reply(channel.id, parentId, text, sentFiles(sent).map((a) => a.id), also);
            setReplies((prev) => mergeMessages(prev, [reply]));
        } catch (e) {
            toast.error(errorText(e));
            drafts.restore(key, sent);
        }
    };
    const react = async (message: ChannelMessage, emoji: string) => {
        const on = !message.reactions.some((r) => r.emoji === emoji && r.mine);
        setReplies((prev) => prev.map((m) => (m.id === message.id ? { ...m, reactions: flipReaction(m.reactions, emoji) } : m)));
        try {
            const settled = await transport.react(channel.id, message.id, emoji, on);
            setReplies((prev) => mergeMessages(prev, [settled]));
        } catch (e) {
            toast.error(errorText(e));
            setReplies((prev) => prev.map((m) => (m.id === message.id ? message : m)));
        }
    };
    const loadOlder = async () => {
        if (!older) return;
        try {
            const page = await shelf.replies(channel.id, parentId, older);
            setReplies((prev) => mergeMessages(prev, page.messages));
            setOlder(page.older);
        } catch (e) {
            toast.error(errorText(e));
        }
    };
    const where = channel.kind === 'dm' ? 'the conversation' : `#${channel.name}`;
    const agents = members.filter((m) => m.kind === 'agent');

    return (
        <PanelFrame phone={phone}>
            {phone ? (
                <PhoneBarBack label={`#${channel.name}`} title={<span className="truncate">Thread</span>} onBack={onClose} />
            ) : (
                <div className="flex h-12 shrink-0 items-center gap-2 px-5">
                    <p className="text-sm font-medium">Thread</p>
                    <p className="truncate text-xs text-muted-foreground">{where}</p>
                    <CloseButton onClose={onClose} />
                </div>
            )}
            <div
                ref={scrollRef}
                onScroll={(e) => {
                    const el = e.currentTarget;
                    atEnd.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
                }}
                className={cn('min-h-0 flex-1 overflow-y-auto scrollbar-subtle', phone && 'flex flex-col')}
                data-testid="thread-panel"
            >
                {top ? (
                    <PlainMessage msg={{ ...top, thread: undefined, pinned: null }} members={everyone} user={user} byName={byName} onOpenChannel={onOpenChannel} onReact={(emoji) => void react(top, emoji)} compact />
                ) : (
                    !state.error && <div className="mx-4 my-3 h-12 animate-pulse rounded-xl bg-foreground/[0.04]" />
                )}
                <div className="flex items-center gap-3 px-4 py-3">
                    <span className="text-xs text-muted-foreground">{state.loading ? 'Reading the replies…' : replies.length ? `${replies.length}${older ? '+' : ''} ${replies.length === 1 ? 'reply' : 'replies'}` : 'No replies yet'}</span>
                    <span className={cn('flex-1 border-t', HAIRLINE)} />
                </div>
                {state.error && (
                    <p role="alert" className="mx-4 mb-2 text-[13px] text-muted-foreground">
                        {state.error}
                    </p>
                )}
                {agents.length > 0 && !state.loading && (
                    <p className="mx-4 mb-2 text-xs leading-relaxed text-muted-foreground">
                        {agents.length === 1 ? `${agents[0].name} answers` : 'The agents here answer'} here without stopping what {agents.length === 1 ? 'it’s' : 'they’re'} doing.
                    </p>
                )}
                {older && (
                    <button type="button" onClick={() => void loadOlder()} className="mx-4 mb-2 text-xs font-medium text-muted-foreground underline-offset-2 hover:text-foreground hover:underline">
                        Earlier replies
                    </button>
                )}
                {replies.map((m) => (
                    <PlainMessage key={m.id} msg={m} members={everyone} user={user} byName={byName} onOpenChannel={onOpenChannel} onReact={(emoji) => void react(m, emoji)} compact />
                ))}
                {/* On a phone at the screen's foot, as a channel's is, however short the thread. */}
                <div className={cn('sticky bottom-0 z-[1] bg-background pt-1', phone && 'mt-auto')}>
                    <ChannelComposer
                        channelName={channel.name}
                        placeholder="Reply…"
                        value={draft.text}
                        onChange={(text) => drafts.setText(key, text)}
                        attachments={draft.attachments}
                        onAddFiles={(files) => files.forEach((file) => drafts.attach(key, channel.id, file))}
                        onAddClip={(clip) => drafts.attach(key, channel.id, clip.file, clip)}
                        onRemoveAttachment={(localId) => drafts.remove(key, localId)}
                        onSubmit={() => void send()}
                        members={members}
                        user={user}
                        textareaRef={textareaRef}
                        compact
                        commands={[]}
                        footer={
                            channel.kind !== 'dm' && (
                                <button
                                    type="button"
                                    role="checkbox"
                                    aria-checked={also}
                                    onClick={() => setAlso(!also)}
                                    className="ml-1 flex h-8 min-w-0 items-center gap-2 rounded-full px-2.5 text-xs text-muted-foreground max-md:h-10 transition-colors hover:bg-foreground/[0.05] hover:text-foreground"
                                >
                                    <ChoiceMark on={also} />
                                    <span className="truncate">Also send to {where}</span>
                                </button>
                            )
                        }
                    />
                </div>
            </div>
        </PanelFrame>
    );
}
