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
    /** False when nothing went out (nothing to send, no thread yet, a turn still running, no connection). */
    send: (text: string, attachments?: AgentChatAttachment[], references?: ChatReference[]) => boolean;
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
