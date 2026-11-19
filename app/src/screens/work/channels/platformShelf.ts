// A channel's shelf on the platform API, through the TypeScript SDK's `Channel`: thread replies, the threads you
// follow, pins, bookmarks, and the files and links its messages shared, each mapped into the page's shapes; a
// failure becomes the sentence to show.
import { attachmentOf, messageOf, seenBy, type Perspective } from '@/screens/channels/sdkTransport';
import { errorText } from '@/screens/console/pages/resources/shared';
import { Channel, type ChannelAuthor as PlatformAuthor, type NoClick } from 'noclick';
import type { ChannelAuthor } from '@/screens/channels/types';
import type { ChannelShelf } from './shelf';

const REPLIES_LIMIT = 50;
const SHARED_LIMIT = 100;
const THREADS_LIMIT = 50;

const iso = (d: Date | null | undefined) => d?.toISOString() ?? null;
const AUTHORS = new Set<ChannelAuthor['type']>(['account', 'user', 'agent', 'workflow_agent', 'a2a', 'system', 'app']);
const authorOf = (a: PlatformAuthor): ChannelAuthor => ({ type: AUTHORS.has(a.type as ChannelAuthor['type']) ? (a.type as ChannelAuthor['type']) : 'system', id: a.id, name: a.name ?? '' });

async function said<T>(call: () => Promise<T>): Promise<T> {
    try {
        return await call();
    } catch (e) {
        throw new Error(errorText(e));
    }
}

/** `person`: a space someone joined, read through their eyes (as the transport reads it). */
export function platformShelf(client: NoClick, person?: Perspective): ChannelShelf {
    const channel = (id: string) => Channel.fromId(id, { client, user: null });
    const message = (m: Parameters<typeof messageOf>[0]) => messageOf(m, person);
    const author = (a: PlatformAuthor) => seenBy(authorOf(a), person);
    return {
        replies: (channelId, parentId, before) =>
            said(async () => {
                const page = await channel(channelId).repliesPage(parentId, before ? { before, limit: REPLIES_LIMIT } : { newest: true, limit: REPLIES_LIMIT });
                return { messages: page.data.map(message), older: page.nextCursor };
            }),
        reply: (channelId, parentId, text, attachmentIds, alsoInChannel) => said(async () => message(await channel(channelId).reply(parentId, text, { files: attachmentIds, alsoInChannel }))),
        markThreadRead: (channelId, parentId) => said(async () => void (await channel(channelId).markThreadRead(parentId))),
        threads: (workspaceId) =>
            said(async () =>
                (await Channel.threads({ client, user: null, workspace: workspaceId ?? undefined, limit: THREADS_LIMIT })).map((t) => ({
                    channelId: t.channelId,
                    channelName: t.channelName,
                    workspaceId: t.workspaceId,
                    parent: message(t.parent),
                    latest: t.latestReply ? message(t.latestReply) : null,
                    count: t.replyCount,
                    unread: t.unreadCount,
                    lastAt: iso(t.lastReplyAt),
                }))
            ),
        pins: (channelId) => said(async () => (await channel(channelId).pins()).map((p) => ({ message: message(p.message), by: author(p.by), at: iso(p.at) }))),
        pin: (channelId, messageId, on) => said(async () => message(await (on ? channel(channelId).pin(messageId) : channel(channelId).unpin(messageId)))),
        bookmarks: (channelId) => said(async () => (await channel(channelId).bookmarks()).map((b) => ({ id: b.id, url: b.url, title: b.title, by: author(b.by), at: iso(b.createdAt) }))),
        addBookmark: (channelId, bookmark) =>
            said(async () => {
                const b = await channel(channelId).addBookmark(bookmark);
                return { id: b.id, url: b.url, title: b.title, by: author(b.by), at: iso(b.createdAt) };
            }),
        removeBookmark: (channelId, bookmarkId) => said(async () => void (await channel(channelId).removeBookmark(bookmarkId))),
        files: (channelId, q) =>
            said(async () =>
                (await channel(channelId).files({ q: q || undefined, limit: SHARED_LIMIT })).data.map((f) => ({
                    messageId: f.messageId,
                    threadId: f.threadId,
                    author: author(f.author),
                    at: iso(f.createdAt) ?? '',
                    file: attachmentOf(f.file),
                }))
            ),
        links: (channelId, q) =>
            said(async () =>
                (await channel(channelId).links({ q: q || undefined, limit: SHARED_LIMIT })).data.map((l) => ({
                    messageId: l.messageId,
                    threadId: l.threadId,
                    author: author(l.author),
                    at: iso(l.createdAt) ?? '',
                    url: l.url,
                    title: l.title,
                    domain: l.domain,
                }))
            ),
    };
}
