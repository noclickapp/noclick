// The account coordinator's web conversation: coordinator:open hands back the
// account's one thread (and the other ways into it, which the sidebar reads), coordinator:send runs a
// turn whose reply streams as the usual chat frames (with any files and the
// automations and accounts the message points at). The transcript is the same
// useAgentChat every agent chat uses, painted first from what this tab (or this
// browser, on a reload) last saw of it, so an ongoing conversation never opens
// on the empty start. Files upload to the account's own attachments, the store
// the phone and email channels file theirs in.
import { useCallback, useEffect, useState, useSyncExternalStore } from 'react';
import { useRouteLoaderData } from 'react-router';
import { toast } from 'sonner';
import { useSnapshot } from 'valtio';
import type { SetupArrival } from '~/components/shell/coordinatorChat';
import { useAgentChat } from '~/hooks/useAgentChat';
import type { ChatUpload } from '~/hooks/useChatAttachments';
import { attachmentEcho, type AgentChatAttachment, type ChatReference } from '~/lib/agentChat';
import type { ChatFile } from '~/hooks/useChatFiles';
import { agentChatSessionStore, getAgentChatSession, seedAgentChatSession } from '~/lib/agentChatSessionStore';
import { readCachedThread, writeCachedThread } from '~/lib/coordinatorThreadCache';
import { cleanupRequestCallback, registerRequestCallback } from '~/lib/socket-receiver';
import { sendEvent, sendEventAsync } from '~/lib/socket-sender';
import { uploadWithProgress } from '~/lib/uploadWithProgress';
import {
    CoordinatorArrivalRequest,
    CoordinatorAttachmentsListRequest,
    CoordinatorAttachmentUploadUrlRequest,
    CoordinatorEmailEnsureRequest,
    CoordinatorEmailInboundRequest,
    CoordinatorEmailSetRequest,
    CoordinatorOpenRequest,
    CoordinatorSendRequest,
    type CoordinatorSetupRef,
} from '~/types/socket-events.generated';

type Reply<T> = Partial<T> & { error?: string; kind?: string };

/** Where else the owner reaches this same conversation. */
export interface CoordinatorReach {
    /** E.164 number it answers on WhatsApp and calls; null where the platform has none. */
    phone: string | null;
    /** E.164 number of its iMessage line; null where the platform has none. */
    imessage: string | null;
    /** Its own email address, once it has picked one. */
    email: string | null;
    /** The owner turned off mail to that address: it stays theirs, and mail to it is ignored. */
    email_paused?: boolean;
    /** Anyone's mail to that address reaches it, not only the owner's. */
    email_from_anyone?: boolean;
}

interface OpenReply {
    conversation_id: string;
    reach: CoordinatorReach;
    /** The instance holds no key for the coordinator's model: the chat asks for it first. */
    needs_key?: string;
}

let reachRead: Promise<CoordinatorReach | null> | null = null;
let reachValue: CoordinatorReach | null = null;
const reachListeners = new Set<() => void>();
const subscribeReach = (listener: () => void) => {
    reachListeners.add(listener);
    return () => void reachListeners.delete(listener);
};

// Every open says where this browser is: the agent that answers in the coordinator's place takes its zone over the one
// the owner's number placed, never over one they chose.
function openRequest() {
    return CoordinatorOpenRequest.create({ request_id: crypto.randomUUID(), timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || null });
}

function readReach(): Promise<CoordinatorReach | null> {
    // The /v1 agent chat's browser zone rides this open too; it moves to /v1 when the coordinator socket events go.
    reachRead ??= sendEventAsync(openRequest()).then(
        (reply) => {
            const { error, reach } = reply as Reply<OpenReply>;
            reachValue = error || !reach ? null : reach;
            reachListeners.forEach((listener) => listener());
            return reachValue;
        },
        (error: unknown) => {
            console.error('[useCoordinatorReach] open failed:', error);
            reachRead = null;
            return null;
        }
    );
    return reachRead;
}

/** Reads the reach again: the coordinator picks its email address in the conversation, after a page has read it. */
export function refreshCoordinatorReach() {
    reachRead = null;
    void readReach();
}

function patchReach(patch: Partial<CoordinatorReach>) {
    if (!reachValue) return;
    reachValue = { ...reachValue, ...patch };
    reachListeners.forEach((listener) => listener());
}

/** NoClick's email address, claiming a readable one the first time it's wanted. Null where this instance has no
 *  inbound email; throws with the server's words when it can't claim one. */
export async function ensureCoordinatorEmail(): Promise<string | null> {
    const reply = (await sendEventAsync(CoordinatorEmailEnsureRequest.create({ request_id: crypto.randomUUID() }))) as Reply<{ address: string | null }>;
    if (reply.error) throw new Error(reply.error);
    patchReach({ email: reply.address ?? null });
    return reply.address ?? null;
}

/** Renames NoClick's address to `name@` its domain; throws with the server's words (taken, not allowed). */
export async function renameCoordinatorEmail(name: string): Promise<string> {
    const reply = (await sendEventAsync(CoordinatorEmailSetRequest.create({ request_id: crypto.randomUUID(), name }))) as Reply<{ address: string }>;
    if (reply.error || !reply.address) throw new Error(reply.error || 'Could not change the address');
    patchReach({ email: reply.address });
    return reply.address;
}

/** Takes mail to NoClick's address, or ignores it (the address stays the owner's). The switch moves at once; the
 *  server's answer, or its refusal, has the last word. Throws with the server's words. */
export async function setCoordinatorEmailInbound(on: boolean): Promise<void> {
    const before = reachValue?.email_paused ?? false;
    patchReach({ email_paused: !on });
    try {
        const reply = (await sendEventAsync(CoordinatorEmailInboundRequest.create({ request_id: crypto.randomUUID(), on }))) as Reply<{ address: string; paused: boolean }>;
        if (reply.error || typeof reply.paused !== 'boolean') throw new Error(reply.error || 'Could not change it');
        patchReach({ email: reply.address ?? reachValue?.email ?? null, email_paused: reply.paused });
    } catch (error) {
        patchReach({ email_paused: before });
        throw error;
    }
}

/** The coordinator's reach for surfaces outside its chat, read once a page (its numbers are the deployment's and don't
 *  change) and shared by every surface. Null until it lands, while not `enabled`, and where there's no coordinator. */
export function useCoordinatorReach(enabled = true): CoordinatorReach | null {
    const reach = useSyncExternalStore(subscribeReach, () => reachValue, () => null);
    useEffect(() => {
        if (enabled) void readReach();
    }, [enabled]);
    return enabled ? reach : null;
}

// The thread this tab last opened, so coming back to the chat finds it in memory without waiting on the server.
let lastOpened: { userId: string; conversationId: string } | null = null;

export function useCoordinatorChat() {
    const userId = (useRouteLoaderData('routes/dashboard') as { user?: { id?: string } } | undefined)?.user?.id;
    const remembered = userId && lastOpened?.userId === userId ? lastOpened.conversationId : null;
    const [conversationId, setConversationId] = useState<string | null>(remembered);
    const [gated, setGated] = useState(false);
    const [needsKey, setNeedsKey] = useState<string | null>(null);
    const [openError, setOpenError] = useState<string | null>(null);
    // This browser's copy says the account has no conversation yet, so the start can show before the server agrees.
    const [cachedEmpty, setCachedEmpty] = useState(false);
    const [attempt, setAttempt] = useState(0);
    // Texts, calls and email reach the same thread: follow those turns live too.
    const chat = useAgentChat(conversationId, undefined, false, true);
    const session = useSnapshot(agentChatSessionStore).sessions[conversationId ?? ''];
    const historyLoaded = !!session?.resumedOnce;

    // A reload paints this browser's copy while the server is asked; the history replaces it when it lands.
    useEffect(() => {
        if (!userId || remembered) return;
        let live = true;
        void readCachedThread(userId).then((cached) => {
            if (!live || !cached) return;
            seedAgentChatSession(cached.conversationId, cached.messages);
            setCachedEmpty(cached.messages.length === 0);
            setConversationId((id) => id ?? cached.conversationId);
        });
        return () => {
            live = false;
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps -- `remembered` is read once, at mount
    }, [userId]);

    useEffect(() => {
        let cancelled = false;
        (async () => {
            try {
                const reply = (await sendEventAsync(openRequest())) as Reply<OpenReply>;
                if (cancelled) return;
                if (reply.error || !reply.conversation_id) {
                    if (reply.kind === 'gated') setGated(true);
                    else setOpenError(reply.error || 'Could not open your conversation');
                    return;
                }
                if (userId) lastOpened = { userId, conversationId: reply.conversation_id };
                setNeedsKey(reply.needs_key ?? null);
                setConversationId(reply.conversation_id);
            } catch (error) {
                if (cancelled) return;
                console.error('[useCoordinatorChat] open failed:', error);
                setOpenError(error instanceof Error ? error.message : 'Could not open your conversation');
            }
        })();
        return () => {
            cancelled = true;
        };
    }, [userId, attempt]);

    // Settled turns are written back for the next visit.
    const { messages } = chat;
    useEffect(() => {
        if (!userId || !conversationId || !historyLoaded || chat.isStreaming) return;
        const timer = setTimeout(() => writeCachedThread(userId, conversationId, messages), 500);
        return () => clearTimeout(timer);
    }, [userId, conversationId, historyLoaded, chat.isStreaming, messages]);

    // Whether the page knows what the thread holds; until then it shows neither the thread nor the start.
    const loaded = messages.length > 0 || historyLoaded || cachedEmpty;
    const loadError = loaded ? null : (openError ?? session?.resumeError ?? null);
    const retry = useCallback(() => {
        if (conversationId) getAgentChatSession(conversationId).resumeError = null;
        setOpenError(null);
        // The open sets the id again, which reads the history afresh.
        setConversationId(null);
        setAttempt((n) => n + 1);
    }, [conversationId]);

    const { addUserMessage, failTurn, isStreaming } = chat;
    const send = useCallback(
        (raw: string, attachments: AgentChatAttachment[] = [], references: ChatReference[] = []): boolean => {
            const text = raw.trim();
            if ((!text && !attachments.length && !references.length) || !conversationId || isStreaming) return false;
            const request_id = crypto.randomUUID();
            // The reply comes when the turn is over (its frames already streamed), or at once when the server refuses
            // the send: a file that never finished uploading, an account that dropped. That one has to be shown.
            registerRequestCallback(request_id, (reply) => {
                const { error, kind, env_var } = (reply as Reply<{ env_var: string }> | null) ?? {};
                if (kind === 'instance_key' && env_var) setNeedsKey(env_var);
                if (error) failTurn(error);
            });
            const request = CoordinatorSendRequest.create({
                request_id,
                text,
                attachment_ids: attachments.map((a) => a.resourceId),
                references: references.map(({ kind, id }) => ({ kind, id })),
            });
            if (!sendEvent(request)) {
                cleanupRequestCallback(request_id);
                toast.error('Not connected');
                return false;
            }
            const echo = attachmentEcho(attachments);
            addUserMessage(text, echo.content, echo.files, references.length ? references : undefined);
            return true;
        },
        [conversationId, isStreaming, addUserMessage, failTurn]
    );

    // NoClick's note for a workflow picked on a public page: the arrival's reply carries it, since this tab's relay may
    // not be connected yet when it lands.
    const { receiveFrame } = chat;
    const arrive = useCallback(
        async ({ setup }: SetupArrival) => {
            const reply = (await sendEventAsync(
                CoordinatorArrivalRequest.create({ request_id: crypto.randomUUID(), workflow_id: setup.workflow_id, client: setup.client ?? undefined })
            )) as Reply<{ note: { message: string; turn_id: string; setup: CoordinatorSetupRef } }>;
            if (reply.error || !reply.note) throw new Error(reply.error || 'Could not set that up');
            receiveFrame({ ...reply.note, finished: true, notification: true });
        },
        [receiveFrame]
    );

    return { ...chat, conversationId, gated, needsKey, send, loaded, loadError, retry, upload: uploadCoordinatorAttachment, listFiles: listCoordinatorFiles, arrive };
}

/** A file into the account's attachments: the server makes its row and a signed URL, the browser PUTs the bytes. */
export const uploadCoordinatorAttachment: ChatUpload = async (file, onProgress) => {
    const mimeType = file.type || 'application/octet-stream';
    const reply = (await sendEventAsync(
        CoordinatorAttachmentUploadUrlRequest.create({ request_id: crypto.randomUUID(), name: file.name || 'pasted-image.png', mime_type: mimeType, size_bytes: file.size })
    )) as Reply<{ attachment_id: string; upload_url: string; url: string }>;
    if (reply.error || !reply.attachment_id || !reply.upload_url || !reply.url) throw new Error(reply.error || 'Could not upload the file');
    const put = await uploadWithProgress(reply.upload_url, file, { method: 'PUT', headers: { 'Content-Type': mimeType }, onProgress });
    if (!put.ok) throw new Error(`The upload failed (${put.status})`);
    return { resourceId: reply.attachment_id, url: reply.url, name: file.name, mimeType, sizeBytes: file.size };
};

interface ListedAttachment {
    attachment_id: string;
    name: string;
    mime_type: string;
    size_bytes: number;
    url: string;
    created_at: string;
}

/** The account's files, newest first, their names containing `query`. */
async function listCoordinatorFiles(query: string): Promise<ChatFile[]> {
    const reply = (await sendEventAsync(
        CoordinatorAttachmentsListRequest.create({ request_id: crypto.randomUUID(), query: query || undefined })
    )) as Reply<{ attachments: ListedAttachment[] }>;
    if (reply.error) throw new Error(reply.error);
    return (reply.attachments ?? []).map((a) => ({
        resourceId: a.attachment_id,
        url: a.url,
        name: a.name,
        mimeType: a.mime_type,
        sizeBytes: a.size_bytes,
        createdAt: a.created_at,
    }));
}
