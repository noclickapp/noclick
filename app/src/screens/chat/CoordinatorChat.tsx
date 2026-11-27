// The Chat page's conversation: NoClick's one session on the platform API (the conversation its listing marks active,
// followed through its `session` frames as it's cleared or resumed) through the one live conversation hook every page
// uses (useAgentThread), read with the page's client and drawn as Work draws an agent's session (ChatTranscript), with
// Work's Beside beside it (what the account's agents are at, and what needs the person) and Work's switchers for it on
// and under its box (which read through Work's client and live frames), written to in Work's box (ChatComposer: its "+"
// menu, /loop, /clear, /resume, Stop and Steer).
import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { toast } from 'sonner';
import { NotFound, type JsonObject, type NoClick } from 'noclick';
import type { ChatReference } from '@/lib/agentThread/messages';
import { setupSubject } from '@/lib/agentThread/thread';
import { useWorkFrames, WorkLiveContext, type WorkLive } from '@/sdk/live';
import { readsRestored } from '@/sdk/useV1';
import { ConversationBrowserView } from '@/screens/work/browser/BrowserView';
import { ConversationBrowserProvider, useConversationBrowser } from '@/screens/work/browser/useConversationBrowser';
import { WorkClientContext } from '@/screens/work/client';
import { accountFiles, attachmentOf } from '@/screens/work/conversation/Composer';
import { useSessionControls } from '@/screens/work/conversation/sessionControls';
import { useFollowSessions } from '@/screens/work/conversation/sessions';
import { COORDINATOR_AGENT, coordinatorAgent, historyByName, knownSession, readCoordinatorSession } from '@/screens/work/coordinatorAgent';
import { AGENT_GONE, useAgentThread } from '@/screens/work/hooks/useAgentThread';
import type { ChatAttachment, ChatFile } from '@/ui/chat/useChatFiles';
import { chatBesideFor } from './beside/ChatBeside';
import { NeedsContext, NeedsStore } from './beside/needs';
import { ChatComposer } from './ChatComposer';
import { ChatTranscript } from './ChatTranscript';
import { useCoordinatorComposerControls } from './composerControls';
import { agentMemoryTransport } from './memories/agentMemoryTransport';
import { ChatSourceContext, type ChatSource, type SetupArrival } from './source';
import { ChatThreadProvider, type ReferenceDisplay } from './thread';

/** A reference chip's own words stand. */
const ownWords: ReferenceDisplay = () => undefined;

/** The chat over `client`, following `live`; `referenceDisplay` names what a message points at, where the host names
 *  accounts its own way. */
export function CoordinatorChat({ client, live, referenceDisplay = ownWords, children }: { client: NoClick; live: WorkLive; referenceDisplay?: ReferenceDisplay; children: ReactNode }) {
    return (
        <WorkClientContext.Provider value={client}>
            <WorkLiveContext.Provider value={live}>
                <Chat client={client} referenceDisplay={referenceDisplay}>
                    {children}
                </Chat>
            </WorkLiveContext.Provider>
        </WorkClientContext.Provider>
    );
}

/** The session it's in, read once (by name, beside the lookup) and again on its `session` frames; null until read.
 *  `missing`: the account has no coordinator (its lookup found none). */
function useCoordinatorSession(client: NoClick, agent: ReturnType<typeof coordinatorAgent>): { session: string | null; error: string | null; missing: boolean; retry: () => void } {
    const [session, setSession] = useState<string | null>(() => knownSession(client));
    const [error, setError] = useState<string | null>(null);
    const [missing, setMissing] = useState(false);
    const [read, setRead] = useState(0);
    useEffect(() => {
        let left = false;
        // The session this browser kept, drawn while it's read again.
        void readsRestored(client).then(() => !left && setSession((s) => s ?? knownSession(client)));
        readCoordinatorSession(client).then(
            (s) => !left && (setSession(s), setError(null)),
            (e: unknown) => {
                if (left) return;
                if (e instanceof NotFound) setMissing(true);
                else setError(e instanceof Error ? e.message : String(e));
            }
        );
        return () => {
            left = true;
        };
    }, [client, read]);
    useWorkFrames('platform:agent', (frame) => {
        if (frame.change === 'session' && agent.isHydrated && frame.agent_id === agent.id) setRead((n) => n + 1);
    });
    return { session, error, missing, retry: () => setRead((n) => n + 1) };
}

function Chat({ client, referenceDisplay, children }: { client: NoClick; referenceDisplay: ReferenceDisplay; children: ReactNode }) {
    // Its sessions and its helpers' follow a clear or a resume from anywhere.
    useFollowSessions();
    const agent = useMemo(() => coordinatorAgent(client), [client]);
    const found = useCoordinatorSession(client, agent);
    const session = found.session;
    const readFirst = useCallback(() => (session ? historyByName(client, session) : Promise.resolve(null)), [client, session]);
    const state = useAgentThread(agent, session, { key: COORDINATOR_AGENT, readFirst, label: 'coordinator' });
    const { thread, ready, working } = state;
    const ownId = ready && agent.isHydrated ? agent.id : null;
    const sessions = useSessionControls(agent, ownId, 'NoClick', working);
    const Beside = useMemo(() => chatBesideFor(client), [client]);
    const [needs] = useState(() => new NeedsStore());
    const composerControls = useCoordinatorComposerControls(client, ready);
    const memories = useMemo(() => agentMemoryTransport(agent), [agent]);

    // A send that didn't go says why, as Work says it.
    useEffect(() => {
        if (!state.error) return;
        toast('Your message didn’t send', { description: state.error });
        state.clearError();
    }, [state.error]); // eslint-disable-line react-hooks/exhaustive-deps

    const send = state.send;
    const sendMessage = useCallback(
        (raw: string, files: ChatAttachment[] = [], references: ChatReference[] = []): boolean => {
            if (!ready || (!raw.trim() && !files.length && !references.length)) return false;
            // Files go with a message of their own: never into a turn at work.
            if (working && files.length) return false;
            void send({ text: raw.trim(), files: files.map(attachmentOf), references });
            return true;
        },
        [ready, working, send]
    );

    const listFiles = useCallback((query: string): Promise<ChatFile[]> => accountFiles(client, query), [client]);

    // A note the conversation keeps once per workflow; read back at once, so it never waits on the stream.
    const rereadHistory = state.rereadHistory;
    const arrive = useCallback(
        async ({ name, setup, text }: SetupArrival) => {
            const named = name.split(/\s+/).join(' ').trim().slice(0, 120) || 'your automation';
            if (!session) return;
            await agent.note(session, text ?? `Let’s finish setting up ${named}.`, { data: { setup: { ...setup } } as JsonObject, key: `setup:${setupSubject(setup)}` });
            await rereadHistory();
        },
        [agent, session, rereadHistory]
    );

    // NoClick's browser in this chat, once the chat has found its agent: the Beside's tile, the turns' cards, the big view.
    const browser = useConversationBrowser(ownId, ownId ? session : null, 'NoClick');

    const setups = useMemo(() => thread.entries.flatMap((e) => (e.kind === 'note' && e.setup ? [setupSubject(e.setup)] : [])), [thread]);
    const chat: ChatSource = {
        isStreaming: working,
        conversationId: ready ? session : null,
        loaded: ready || thread.entries.length > 0,
        // The account has no coordinator to talk to.
        gated: state.loadError === AGENT_GONE || found.missing,
        loadError: state.loadError === AGENT_GONE ? null : (state.loadError ?? (session ? null : found.error)),
        retry: session ? state.retry : found.retry,
        send: sendMessage,
        memories,
        listFiles,
        arrive,
        Beside,
        composerControls,
        thread: { Transcript: ChatTranscript, size: thread.entries.length, moved: thread, setups },
        Composer: ChatComposer,
    };
    return (
        <ChatThreadProvider state={state} session={session} sessions={sessions} referenceDisplay={referenceDisplay}>
            <NeedsContext.Provider value={needs}>
                <ConversationBrowserProvider value={browser}>
                    <ChatSourceContext.Provider value={chat}>{children}</ChatSourceContext.Provider>
                    <ConversationBrowserView />
                </ConversationBrowserProvider>
            </NeedsContext.Provider>
            {sessions.dialogs}
        </ChatThreadProvider>
    );
}
