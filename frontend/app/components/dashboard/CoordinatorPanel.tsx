// The account coordinator's web transport: a dock on the Dashboard that opens
// the account's one conversation (coordinator:open), sends turns
// (coordinator:send) and renders the reply through the same chat frames and
// transcript every agent chat uses. Mounted only where useFeatureGate says so.

import { useCallback, useEffect, useRef, useState } from 'react';
import { Brain, ChevronDown, RotateCcw, Sparkles } from 'lucide-react';
import { toast } from 'sonner';
import { cn } from '~/lib/utils';
import { AgentChatComposer } from '~/components/chat/AgentChatComposer';
import { AgentChatTranscript } from '~/components/chat/AgentChatTranscript';
import { useAgentChat } from '~/hooks/useAgentChat';
import { CoordinatorMemoriesDialog } from '~/components/dashboard/CoordinatorMemories';
import { sendEvent, sendEventAsync } from '~/lib/socket-sender';
import {
    CoordinatorOpenRequest,
    CoordinatorResetRequest,
    CoordinatorSendRequest,
} from '~/types/socket-events.generated';

type Reply<T> = Partial<T> & { error?: string; kind?: string };

export function CoordinatorPanel() {
    const [open, setOpen] = useState(false);
    const [memoriesOpen, setMemoriesOpen] = useState(false);
    const [conversationId, setConversationId] = useState<string | null>(null);
    const [gated, setGated] = useState(false);
    const [draft, setDraft] = useState('');
    const textareaRef = useRef<HTMLTextAreaElement>(null);
    const { messages, isStreaming, errorReason, addUserMessage } = useAgentChat(conversationId);

    useEffect(() => {
        let cancelled = false;
        (async () => {
            try {
                const reply = (await sendEventAsync(
                    CoordinatorOpenRequest.create({ request_id: crypto.randomUUID() }),
                )) as Reply<{ conversation_id: string }>;
                if (cancelled) return;
                if (reply.error || !reply.conversation_id) {
                    if (reply.kind === 'gated') setGated(true);
                    else toast.error(reply.error || 'Could not open the coordinator');
                    return;
                }
                setConversationId(reply.conversation_id);
            } catch (error) {
                console.error('[CoordinatorPanel] open failed:', error);
            }
        })();
        return () => {
            cancelled = true;
        };
    }, []);

    const submit = useCallback(() => {
        const text = draft.trim();
        if (!text || !conversationId || isStreaming) return;
        addUserMessage(text);
        setDraft('');
        if (!sendEvent(CoordinatorSendRequest.create({ request_id: crypto.randomUUID(), text }))) {
            toast.error('Not connected');
        }
    }, [draft, conversationId, isStreaming, addUserMessage]);

    const reset = useCallback(async () => {
        if (!conversationId) return;
        try {
            const reply = (await sendEventAsync(
                CoordinatorResetRequest.create({ request_id: crypto.randomUUID() }),
            )) as Reply<{ reset: boolean }>;
            if (reply.error) throw new Error(reply.error);
            // Re-resume: the hook reloads the (now empty) transcript on id change.
            const id = conversationId;
            setConversationId(null);
            setTimeout(() => setConversationId(id), 0);
        } catch (error) {
            toast.error(error instanceof Error ? error.message : 'Could not reset');
        }
    }, [conversationId]);

    if (gated) return null;

    if (!open) {
        return (
            <button
                type="button"
                onClick={() => setOpen(true)}
                className="fixed bottom-24 right-4 z-40 inline-flex items-center gap-2 rounded-full border border-border bg-card px-4 py-2 text-sm font-medium text-foreground shadow-lg hover:bg-accent"
                data-testid="coordinator-dock"
            >
                <Sparkles className="h-4 w-4" />
                Coordinator
            </button>
        );
    }

    return (
        <div
            className={cn(
                'fixed bottom-24 right-4 z-40 flex w-[min(28rem,calc(100vw-2rem))] flex-col overflow-hidden rounded-2xl border border-border bg-card shadow-2xl',
                'h-[min(34rem,calc(100vh-11rem))]',
            )}
            data-testid="coordinator-panel"
        >
            <div className="flex items-center gap-2 border-b border-border px-3 py-2">
                <Sparkles className="h-4 w-4 text-muted-foreground" />
                <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium leading-tight text-foreground">Coordinator</p>
                    <p className="truncate text-[11px] text-muted-foreground">Knows your whole account. Ask, or request a build.</p>
                </div>
                <button type="button" onClick={() => setMemoriesOpen(true)}
                    className="rounded-md p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground"
                    title="Memories" aria-label="Open memories">
                    <Brain className="h-4 w-4" />
                </button>
                <button
                    type="button"
                    onClick={reset}
                    disabled={!conversationId || isStreaming}
                    className="rounded-md p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground disabled:opacity-40"
                    title="Start over (keeps memories)"
                    aria-label="Start over"
                >
                    <RotateCcw className="h-4 w-4" />
                </button>
                <button
                    type="button"
                    onClick={() => setOpen(false)}
                    className="rounded-md p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground"
                    aria-label="Collapse"
                >
                    <ChevronDown className="h-4 w-4" />
                </button>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto px-3 py-2">
                <AgentChatTranscript messages={messages} isStreaming={isStreaming} errorReason={errorReason} />
            </div>
            <div className="border-t border-border px-2 pb-2 pt-1">
                <AgentChatComposer
                    value={draft}
                    onChange={setDraft}
                    onSubmit={submit}
                    placeholder="Ask about your account, or describe what to build"
                    inputDisabled={!conversationId}
                    sendDisabled={!draft.trim() || !conversationId || isStreaming}
                    textareaRef={textareaRef}
                />
            </div>
            <CoordinatorMemoriesDialog open={memoriesOpen} onOpenChange={setMemoriesOpen} />
        </div>
    );
}
