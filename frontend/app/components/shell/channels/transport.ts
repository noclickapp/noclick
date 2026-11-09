// What a channel page reads and writes through: the hosted Work page serves the
// account's channels and workspaces from its platform API and follows them live
// (cloud/lib/channels/transport.ts); a test hands in its own.
import type { AgentChoice, Channel, ChannelAttachment, ChannelMessage, ChannelMode, ChannelSchedule, ChannelWorkspace } from './types';

/** Something moved in the account's channels: new messages, one message's reactions, a channel itself, or a workspace. */
export interface ChannelChange {
    kind: 'message' | 'reaction' | 'channel' | 'workspace';
    channelId?: string;
    workspaceId?: string;
    messageId?: string;
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
    createChannel(input: { workspaceId: string | null; name: string; topic: string; mode: ChannelMode; agents: AgentChoice[] }): Promise<Channel>;
    updateChannel(channelId: string, changes: { topic?: string; mode?: ChannelMode }): Promise<Channel>;
    /** The schedules that post in it. */
    schedules(channelId: string): Promise<ChannelSchedule[]>;
    /** Add one of your agents; a workspace's channel takes a platform agent into the workspace first. */
    addAgent(channel: Channel, agent: AgentChoice): Promise<Channel>;
    removeMember(channelId: string, memberId: string): Promise<Channel>;
    close(channelId: string): Promise<void>;
    /** You've read it through its newest message. */
    markRead(channelId: string): Promise<void>;
    /** Follow changes as they happen; returns the way to stop. */
    subscribe(listener: (change: ChannelChange) => void): () => void;
}
