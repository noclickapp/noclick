// What a channel keeps beside its messages, as Work reads and writes it: threads (a message's replies, and every
// thread you follow), pins, bookmarks, and the files and links its messages shared. The hosted transport serves it
// from the platform API (platformShelf.ts, over the channels layer's sdkTransport); every method throws an Error
// whose message is the sentence to show.
import type { ChannelHistoryPage } from '@/screens/channels/transport';
import type { ChannelAttachment, ChannelAuthor, ChannelMessage } from '@/screens/channels/types';

export interface ChannelPin {
    message: ChannelMessage;
    by: ChannelAuthor;
    at: string | null;
}

export interface ChannelBookmark {
    id: string;
    url: string;
    title: string;
    by: ChannelAuthor;
    at: string | null;
}

/** A file one of the channel's messages (or a reply) shared. */
export interface SharedFile {
    messageId: string;
    threadId: string | null;
    author: ChannelAuthor;
    at: string;
    file: ChannelAttachment;
}

/** A link a message (or a reply) carried. */
export interface SharedLink {
    messageId: string;
    threadId: string | null;
    author: ChannelAuthor;
    at: string;
    url: string;
    /** A markdown link's words; null for a bare address. */
    title: string | null;
    domain: string;
}

/** A thread you follow, wherever it is. */
export interface FollowedThread {
    channelId: string;
    channelName: string;
    workspaceId: string | null;
    parent: ChannelMessage;
    latest: ChannelMessage | null;
    count: number;
    unread: number;
    lastAt: string | null;
}

export interface ChannelShelf {
    /** A thread's newest replies, or those before `before`; oldest first. */
    replies(channelId: string, parentId: string, before?: string): Promise<ChannelHistoryPage>;
    reply(channelId: string, parentId: string, text: string, attachmentIds: string[], alsoInChannel: boolean): Promise<ChannelMessage>;
    /** You've read the thread through its newest reply. */
    markThreadRead(channelId: string, parentId: string): Promise<void>;
    /** The threads you follow (in a space, or everywhere), newest reply first. */
    threads(workspaceId: string | null): Promise<FollowedThread[]>;
    /** Newest pin first. */
    pins(channelId: string): Promise<ChannelPin[]>;
    pin(channelId: string, messageId: string, on: boolean): Promise<ChannelMessage>;
    /** Oldest first, as they were added. */
    bookmarks(channelId: string): Promise<ChannelBookmark[]>;
    addBookmark(channelId: string, bookmark: { url: string; title: string }): Promise<ChannelBookmark>;
    removeBookmark(channelId: string, bookmarkId: string): Promise<void>;
    /** Newest first; `q` narrows by name. */
    files(channelId: string, q?: string): Promise<SharedFile[]>;
    links(channelId: string, q?: string): Promise<SharedLink[]>;
}
