// Every thread you follow in the space, as Slack's Threads view lists them: where it is, what started it, the latest
// reply and what's new; one opens its channel with the thread beside it. Read with the space and again when a frame
// says a thread moved (Home's list counts what's new from the same read).
import { HAIRLINE } from '@/ui/primitives';
import { timeLabel } from '@/screens/channels/MessageList';
import { PhoneBarBack } from '@/ui/phoneBar';
import type { ChannelAuthor, ChannelMessage } from '@/screens/channels/types';
import { cn } from '@/ui/utils';
import type { ChannelShelf, FollowedThread } from '../channels/shelf';
import { useWorkV1 } from '../agents/reads';
import { useWorkFrames } from '@/sdk/live';

const plain = (text: string) => text.replace(/[`*_~>#]/g, '').split('\n')[0];

export interface FollowedThreads {
    threads: FollowedThread[] | null;
    error: string | null;
    /** Replies you haven't read, across them. */
    unread: number;
}

/** The threads you follow in a space, kept per client (whose eyes the shelf reads through) and space, so a return
 *  shows them at once. */
export const threadsKey = (workspaceId: string | null) => `work:threads:${workspaceId ?? 'all'}`;

export function useFollowedThreads(shelf: ChannelShelf, workspaceId: string | null): FollowedThreads {
    const read = useWorkV1(threadsKey(workspaceId), () => shelf.threads(workspaceId));
    useWorkFrames('platform:channel', (frame) => {
        if (frame.kind === ('thread' as typeof frame.kind)) void read.refresh();
    });
    const threads = read.data ?? null;
    return { threads, error: read.error ? (read.error instanceof Error ? read.error.message : String(read.error)) : null, unread: (threads ?? []).reduce((n, t) => n + t.unread, 0) };
}

export function ThreadsPane({
    followed: { threads, error },
    nameOf,
    phone,
    onBack,
    onOpen,
}: {
    followed: FollowedThreads;
    /** How an author reads here (you, a person, an agent). */
    nameOf: (author: ChannelAuthor) => string;
    phone: boolean;
    onBack: () => void;
    onOpen: (channelId: string, parentId: string) => void;
}) {
    const line = (m: ChannelMessage) => (
        <>
            <span className="font-semibold text-foreground">{nameOf(m.author)}:</span> {plain(m.text) || (m.attachments.length ? `${m.attachments.length} file${m.attachments.length > 1 ? 's' : ''}` : '')}
        </>
    );
    return (
        <section className="flex min-h-0 min-w-0 flex-1 flex-col" data-testid="threads-pane">
            {phone ? (
                <PhoneBarBack label="Home" title={<span className="truncate">Threads</span>} onBack={onBack} />
            ) : (
                <header className={cn('flex h-12 shrink-0 items-center border-b px-5', HAIRLINE)}>
                    <h1 className="text-sm font-semibold">Threads</h1>
                </header>
            )}
            <div className="min-h-0 flex-1 overflow-y-auto scrollbar-subtle">
                <div className="mx-auto max-w-[760px] space-y-3 px-4 py-6 sm:px-6">
                    {error && (
                        <p role="alert" className="text-sm text-muted-foreground">
                            {error}
                        </p>
                    )}
                    {!threads && !error && [0, 1, 2].map((i) => <div key={i} className="h-24 animate-pulse rounded-2xl bg-foreground/[0.04]" />)}
                    {threads?.map((t) => (
                        <button
                            key={t.parent.id}
                            type="button"
                            onClick={() => onOpen(t.channelId, t.parent.id)}
                            className={cn('block w-full rounded-2xl border p-4 text-left transition-colors hover:bg-foreground/[0.03]', HAIRLINE)}
                        >
                            <p className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
                                #{t.channelName}
                                {t.unread > 0 && <span className="rounded-full bg-foreground px-1.5 text-[11px] font-semibold leading-[18px] text-background">{t.unread} new</span>}
                            </p>
                            <p className="mt-1.5 line-clamp-2 text-sm text-foreground/90">{line(t.parent)}</p>
                            {t.latest && <p className="mt-2 line-clamp-2 text-sm text-muted-foreground">{line(t.latest)}</p>}
                            <p className="mt-2.5 text-xs text-muted-foreground">
                                {t.count} {t.count === 1 ? 'reply' : 'replies'}
                                {t.lastAt && ` · last ${timeLabel(t.lastAt)}`}
                            </p>
                        </button>
                    ))}
                    {threads && !threads.length && <p className="text-sm text-muted-foreground">No threads yet. Reply in a thread on any message and it shows here.</p>}
                </div>
            </div>
        </section>
    );
}
