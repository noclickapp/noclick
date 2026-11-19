// What a channel page reads and writes through: the platform API through the SDK (sdkTransport.ts), which whoever
// mounts the page follows live by handing it the account's changes; a test hands in its own.
import type { AgentChoice, Channel, ChannelAttachment, ChannelMessage, ChannelMode, ChannelSchedule, ChannelWorkspace } from './types';

/** Something moved in the account's channels: new messages, a thread's replies, one message's reactions or pin, its
 *  bookmarks, a channel itself, a workspace, or your own sections of its channels; or someone started or stopped
 *  typing in a channel (`typing`). */
export interface ChannelChange {
    kind: 'message' | 'thread' | 'reaction' | 'pin' | 'bookmark' | 'channel' | 'workspace' | 'sections' | 'typing';
    channelId?: string;
    workspaceId?: string;
    messageId?: string;
    /** The thread it's in: a reply's (or a thread's) parent. */
    threadId?: string;
    /** Who is typing (`typing`): their user id in the account, or `account` for its owner, and their name as the
     *  channel shows it. */
    typist?: { id: string; name: string; typing: boolean };
}

export interface ChannelHistoryPage {
    /** Oldest first. */
    messages: ChannelMessage[];
    /** Where older messages start (pass back as `before`), or null at the very beginning. */
    older: string | null;
}

/** A voice clip's length and waveform, recorded in the browser. */
export interface VoiceClipInfo {
    durationMs: number;
    peaks: number[];
}

/** Every read and write Channels makes. A method throws an Error whose message is the sentence to show. */
export interface ChannelsTransport {
    /** The account's workspaces (its own channels, outside any, are the page's home). */
    workspaces(): Promise<ChannelWorkspace[]>;
    /** The account's open channels, in every workspace and none. */
    channels(): Promise<Channel[]>;
    /** The account's agents, to add to a channel: those in its Automations and its platform agents. */
    agents(): Promise<AgentChoice[]>;
    /** The newest messages, or those before `before`. */
    history(channelId: string, before?: string): Promise<ChannelHistoryPage>;
    /** Messages after `afterId`, oldest first. */
    after(channelId: string, afterId: string): Promise<ChannelMessage[]>;
    message(channelId: string, messageId: string): Promise<ChannelMessage>;
    upload(channelId: string, file: File, clip?: VoiceClipInfo): Promise<ChannelAttachment>;
    post(channelId: string, text: string, attachmentIds: string[]): Promise<ChannelMessage>;
    /** Add (`on`) or take back your reaction; returns the message. */
    react(channelId: string, messageId: string, emoji: string, on: boolean): Promise<ChannelMessage>;
    createWorkspace(name: string, logo?: File): Promise<ChannelWorkspace>;
    createChannel(input: { workspaceId: string | null; name: string; topic: string; agents: AgentChoice[]; people?: string[] }): Promise<Channel>;
    updateChannel(channelId: string, changes: { name?: string; topic?: string; mode?: ChannelMode }): Promise<Channel>;
    /** The schedules that post in it. */
    schedules(channelId: string): Promise<ChannelSchedule[]>;
    /** Add one of your agents; a workspace's channel takes a platform agent into the workspace first. */
    addAgent(channel: Channel, agent: AgentChoice): Promise<Channel>;
    removeMember(channelId: string, memberId: string): Promise<Channel>;
    close(channelId: string): Promise<void>;
    /** Open a closed channel again, under `name` where an open one has its own (else `ChannelNameTaken`). */
    reopen(channelId: string, name?: string): Promise<Channel>;
    /** Star or mute it, or undo either, for you alone; returns it as you read it. */
    setPreference(channelId: string, preference: 'starred' | 'muted', on: boolean): Promise<Channel>;
    /** Leave a channel you're in (a person in a space's): it carries on without you, and posting in it joins again. */
    leave(channelId: string): Promise<void>;
    /** Join a channel of your space you're not in (a person in a space's); returns it as you read it. */
    join(channelId: string): Promise<Channel>;
    /** To the trash, for 30 days; resolves to its trash item, which puts it back. */
    deleteChannel(channelId: string): Promise<{ trashId: string }>;
    /** Put back a channel `deleteChannel` sent to the trash. */
    restoreChannel(trashId: string): Promise<void>;
    /** You've read it through its newest message. */
    markRead(channelId: string): Promise<void>;
    /** You're typing in it (`true`), or stopped: its other readers see so for a few seconds. */
    typing(channelId: string, typing: boolean): Promise<void>;
    /** Follow changes as they happen; returns the way to stop. */
    subscribe(listener: (change: ChannelChange) => void): () => void;
}

/** A reopen refused because an open channel in its space has its name: it reopens under another. */
export class ChannelNameTaken extends Error {}
