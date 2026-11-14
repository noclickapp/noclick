// The account coordinator's chat, wherever its turns run. The Chat page draws whichever chat it's given: the
// coordinator's own conversation over the socket (useCoordinatorChat), or one a platform registers for the accounts
// its rollout opens it to (hosted: the coordinator agent through /v1, behind coordinator_agent). A platform registers
// a Provider (lazy, so nothing loads until the page opens) that renders its chat into the context below.
import { createContext, Suspense, useContext, type ComponentType, type ReactNode } from 'react';
import type { AgentChatMessage } from '~/hooks/useAgentChat';
import type { ChatUpload } from '~/hooks/useChatAttachments';
import type { ThreadJobs } from '~/hooks/useCoordinatorJobs';
import type { MemoryTransport } from '~/hooks/useCoordinatorMemories';
import type { AgentChatAttachment, ChatReference } from '~/lib/agentChat';
import type { ChatFile } from '~/hooks/useChatFiles';
import type { CoordinatorSetupRef } from '~/types/socket-events.generated';

export interface CoordinatorChat {
    messages: AgentChatMessage[];
    isStreaming: boolean;
    errorReason: string | null;
    /** The thread, once it's known; the composer waits for it. */
    conversationId: string | null;
    /** Whether the page knows what the thread holds; until then it shows neither the thread nor the start. */
    loaded: boolean;
    /** This account has no coordinator to talk to. */
    gated: boolean;
    /** The key this instance needs before the coordinator's model can run (a self-hosted install without one). */
    needsKey?: string | null;
    loadError: string | null;
    retry: () => void;
    /** False when nothing went out (nothing to send, no thread yet, a turn still running that it can't join, no
     *  connection). */
    send: (text: string, attachments?: AgentChatAttachment[], references?: ChatReference[]) => boolean;
    /** While a turn this page started (or took up) runs, words sent join it (`send` steers) rather than wait for it:
     *  the composer offers Steer, and Stop with nothing typed. Files can't join a running turn. */
    steers?: boolean;
    /** Stops the turn this page started or took up, where the chat can. */
    stop?: () => void;
    /** Where a file the composer adds goes. */
    upload: ChatUpload;
    /** The memory panel's transport; the coordinator's own when absent. */
    memories?: MemoryTransport;
    /** How the cards follow the work a turn started; the coordinator's jobs when absent. */
    followJobs?: ThreadJobs;
    /** The account's files the "+" menu offers to send again, newest first, their names containing `query`. */
    listFiles: (query: string) => Promise<ChatFile[]>;
    /** Puts NoClick's note that `arrival` is being set up in the thread, which draws its setup card under it. */
    arrive: (arrival: SetupArrival) => Promise<void>;
    /** What works beside the conversation and what needs the person, drawn by the platform that runs the agents
     *  (hosted: Work's Beside card and rail, with the account's asks on top). It draws nothing when nothing is going. */
    Beside?: ComponentType<ChatBesideProps>;
    /** The platform's own drawing of the thread, in place of the messages' transcript (hosted: Work's rows over the
     *  conversation it keeps live itself), with what the page reads of it: how many things it holds, what changes as it
     *  moves (to follow the newest), and the automations being set up in it. `messages` is then empty. */
    thread?: { Transcript: ComponentType<ChatTranscriptProps>; size: number; moved: unknown; setups: readonly string[] };
    /** The coordinator's own switchers, drawn by the platform that runs it: its model beside Send, the row under the
     *  box (the account its model runs on, where it runs, its budget), and, while it can't run what's picked, the
     *  Send that asks for an account instead (`ask`, which Enter opens too). */
    composerControls?: { model: ReactNode; footer: ReactNode; ask?: { button: ReactNode; open: () => void } | null };
    /** The platform's own box, in place of the shared composer (hosted: Work's, the one box of every agent
     *  conversation, over the conversation it keeps live itself: its "+" menu, its / commands such as /loop, Stop and
     *  Steer), drawn with the coordinator's switchers. */
    Composer?: ComponentType<ChatComposerProps>;
}

/** What the page gives the platform's box: what it says while empty, its size (`tall` while it's the middle of an
 *  empty page), words put in it from elsewhere (an Ask NoClick, the Beside's reply), changing each time, how a send
 *  that moves the page runs (the first message carries the box to the thread's foot), and its frame. */
export interface ChatComposerProps {
    placeholder: string;
    size: 'default' | 'tall';
    putBack: { text: string; references?: readonly ChatReference[]; n: number } | null;
    transition: (update: () => void) => void;
    transitionName: string;
    className?: string;
}

/** What the Beside reads from the page (the thread it reads from its platform's own chat): how to start a reply in
 *  the composer, the chat column's width, and where beside the chat it may open a column of its own (a laptop's: a
 *  helper's conversation), null until the page has laid it out. It floats over the column's top right and says how much
 *  of the column's right the thread and the composer give it (`onReserve`). */
export interface ChatBesideProps {
    draft: (text: string) => void;
    aside: HTMLElement | null;
    width: number;
    onReserve: (px: number) => void;
}

export interface ChatTranscriptProps {
    /** How a reference chip names an account, in its app's logo. */
    referenceDisplay?: (reference: ChatReference) => { label: string; mark: ReactNode } | undefined;
}

/** A workflow picked on a public page (an /agents page, /mcp), made and now set up from the chat. */
export interface SetupArrival {
    name: string;
    setup: CoordinatorSetupRef;
}

/** What the registered Provider renders around the Chat page. */
export const CoordinatorChatContext = createContext<CoordinatorChat | null>(null);

let Provider: ComponentType<{ children: ReactNode }> | null = null;

/** A platform's coordinator chat: a Provider that renders the context around its children. */
export function registerCoordinatorChat(provider: ComponentType<{ children: ReactNode }>): void {
    Provider = provider;
}

export function hasPlatformCoordinatorChat(): boolean {
    return Provider !== null;
}

/** The platform's chat, inside `PlatformCoordinatorChat`. */
export function usePlatformCoordinatorChat(): CoordinatorChat {
    const chat = useContext(CoordinatorChatContext);
    if (!chat) throw new Error('The platform’s coordinator chat is read inside PlatformCoordinatorChat.');
    return chat;
}

/** Wraps the Chat page in the registered Provider, showing `fallback` while it loads. */
export function PlatformCoordinatorChat({ fallback, children }: { fallback: ReactNode; children: ReactNode }) {
    if (!Provider) return <>{children}</>;
    return (
        <Suspense fallback={fallback}>
            <Provider>{children}</Provider>
        </Suspense>
    );
}
