// The chat the Chat page is drawn over: whoever runs NoClick's conversation renders it into the context below, with
// its own transcript and its own box, and what the page reads of it around them. This app's is NoClick's one session
// on the platform API (CoordinatorChat.tsx); a host can draw another (one over its own connection) through the same
// shape.
import { createContext, useContext, type ComponentType, type ReactNode } from 'react';
import type { ChatReference } from '@/lib/agentThread/messages';
import type { SetupRef } from '@/lib/agentThread/thread';
import type { ChatAttachment, ChatFile } from '@/ui/chat/useChatFiles';
import type { MemoryTransport } from './memories/useMemories';

export interface ChatSource {
    /** NoClick is working on a turn. */
    isStreaming: boolean;
    /** The thread, once it's known; the box waits for it. */
    conversationId: string | null;
    /** Whether the page knows what the thread holds; until then it shows neither the thread nor the start. */
    loaded: boolean;
    /** This account has no NoClick to talk to. */
    gated: boolean;
    loadError: string | null;
    retry: () => void;
    /** False when nothing went out (nothing to send, no thread yet, a turn still running that it can't join, no
     *  connection). */
    send: (text: string, attachments?: ChatAttachment[], references?: ChatReference[]) => boolean;
    /** The memory panel's transport. */
    memories: MemoryTransport;
    /** The account's files the "+" menu offers to send again, newest first, their names containing `query`. */
    listFiles: (query: string) => Promise<ChatFile[]>;
    /** Puts NoClick's note that `arrival` is being set up in the thread, which draws its setup card under it. */
    arrive: (arrival: SetupArrival) => Promise<void>;
    /** What works beside the conversation and what needs the person: Work's Beside card and rail, with the account's
     *  asks on top. It draws nothing when nothing is going. */
    Beside?: ComponentType<ChatBesideProps>;
    /** The chat's drawing of its thread, with what the page reads of it: how many things it holds, what changes as it
     *  moves (to follow the newest), and the automations being set up in it. */
    thread: { Transcript: ComponentType; size: number; moved: unknown; setups: readonly string[] };
    /** NoClick's own switchers: its model beside Send, the row under the box (the account its model runs on, where it
     *  runs, its budget), and, while it can't run what's picked, the Send that asks for an account instead (`ask`,
     *  which Enter opens too). */
    composerControls?: { model: ReactNode; footer: ReactNode; ask?: { button: ReactNode; open: () => void } | null };
    /** The chat's box (Work's, the one box of every agent conversation: its "+" menu, its / commands such as /loop,
     *  Stop and Steer, with NoClick's switchers). */
    Composer: ComponentType<ChatComposerProps>;
}

/** What the page gives the chat's box: what it says while empty, its size (`tall` while it's the middle of an empty
 *  page), words put in it from elsewhere (an Ask NoClick, the Beside's reply), changing each time, how a send that
 *  moves the page runs (the first message carries the box to the thread's foot), and its frame. */
export interface ChatComposerProps {
    placeholder: string;
    size: 'default' | 'tall';
    putBack: { text: string; references?: readonly ChatReference[]; n: number } | null;
    transition: (update: () => void) => void;
    transitionName: string;
    className?: string;
}

/** What the Beside reads from the page (the thread it reads from its own chat): how to start a reply in the composer,
 *  the chat column's width, and where beside the chat it may open a column of its own (a laptop's: a helper's
 *  conversation), null until the page has laid it out. It floats over the column's top right and says how much of the
 *  column's right the thread and the composer give it (`onReserve`). */
export interface ChatBesideProps {
    draft: (text: string) => void;
    aside: HTMLElement | null;
    width: number;
    onReserve: (px: number) => void;
}

/** A workflow picked on another page (an /agents page, /mcp), made and now set up from the chat. */
export interface SetupArrival {
    name: string;
    setup: SetupRef;
}

export const ChatSourceContext = createContext<ChatSource | null>(null);

/** The chat the page is drawn over, inside its provider. */
export function useChatSource(): ChatSource {
    const chat = useContext(ChatSourceContext);
    if (!chat) throw new Error('The Chat page is drawn inside the provider of the chat it’s drawn over.');
    return chat;
}
