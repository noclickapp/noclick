// The builder chat as the automation's log of changes: each request is a change, its words the heading, with the
// work under it (while it runs, the batch it's on and the words of its turn; once done, its actions folded) and the
// steps it touched as they land, then its answer: what the builder said last, and how its run ended when it didn't
// finish, with a Try again that sends the change's request again. A reply that came with no request (a note added to
// the chat) is a change of its own.
import { useEffect, useRef, type ReactNode } from 'react';
import { useSnapshot } from 'valtio';
import { AlertCircle, CircleSlash } from 'lucide-react';
import { MarkdownRenderer, preloadMarkdownRenderer } from '~/components/chat/MarkdownRendererLazy';
import { MessageContentRenderer } from '~/components/chat/MessageContentRenderer';
import { WorkflowEditEventView } from '~/components/chat/WorkflowEditEventView';
import { ProgressMotion } from '~/components/coordinator/inline/motion';
import { HAIRLINE } from '~/components/dashboard/primitives';
import { BUTTON_SECONDARY } from '~/components/shell/buttons';
import { N8nImportBadge } from '~/components/workflow/N8nImportBadge';
import { useN8nImportStatus } from '~/hooks/useN8nImportStatus';
import { useStickToBottom } from '~/hooks/useStickToBottom';
import { activeGenStore } from '~/lib/activeGenStore';
import { builderTurns, liveWork, replyWork, type BuilderTurn } from '~/lib/builderSteps';
import { cn } from '~/lib/utils';
import { deriveBuilderNodes } from '../builderProgress/model';
import type { Message } from '../types';
import { BuilderActions, BuilderLive, BuilderParts } from './BuilderWork';

/** What a reply that isn't a builder turn says: its plain text and content. */
function plainWords(message: Message): string | undefined {
    const content = (message.content ?? []).filter((c) => c.type === 'text').map((c) => (c.text ?? '').trim()).filter(Boolean);
    return (content.length ? content.join('\n\n') : message.text?.trim()) || undefined;
}

/** Requests sent so far: a new one pins the thread to the bottom, whether it lands alone or with its reply (a send
 *  registers both at once). */
export const requestsIn = (messages: Message[]) => messages.filter((m) => m.isUser).length;

const requestText = (message: Message) => {
    const items = Array.isArray(message.content) ? message.content : [];
    return items.length ? items.filter((i) => i.type === 'text').map((i) => i.text ?? '').join('\n').trim() : message.text;
};

/** What a request says, to send again: only words, as a request with images or an import can't be sent as words. */
function resendable(request?: Message): string | undefined {
    if (!request || request.n8nImportNodeCount !== undefined || request.content?.some((i) => i.type !== 'text')) return undefined;
    return requestText(request)?.trim() || undefined;
}

/** What was asked, as the change's heading: the words, any images or a drawing that came with them. */
function Request({ message }: { message: Message }) {
    const n8n = useN8nImportStatus();
    if (message.n8nImportNodeCount !== undefined) {
        return <N8nImportBadge nodeCount={message.n8nImportNodeCount} processing={n8n.nodeCount !== null} />;
    }
    const items = Array.isArray(message.content) ? message.content : [];
    const text = requestText(message);
    const images = items
        .filter((i) => i.type === 'image_url')
        .map((i) => (typeof i.image_url === 'string' ? i.image_url : i.image_url?.url))
        .filter((url): url is string => !!url)
        // A drawing rides as "drawing:<id>:<data url>".
        .map((url) => (url.startsWith('drawing:') ? url.split(':').slice(2).join(':') : url));
    return (
        <div>
            {text && <MessageContentRenderer text={text} className="text-[15px] font-medium leading-snug text-foreground" />}
            {images.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-2">
                    {images.map((src, i) => (
                        <img key={i} src={src} alt="" className="h-20 w-auto max-w-[180px] rounded-lg border border-border object-cover dark:border-foreground/[0.1]" />
                    ))}
                </div>
            )}
        </div>
    );
}

/** How a run that didn't finish ended: stopped without saying it was done, or hit by an error; with a Try again that
 *  sends its change's request again, where there is one to send. */
function Ending({ message, resend }: { message: Message; resend?: () => void }) {
    const failed = !!message.failed;
    return (
        <div className="flex items-center gap-2 text-[13.5px]" data-testid={failed ? 'builder-failed' : 'builder-incomplete'}>
            {failed ? (
                <AlertCircle className="h-4 w-4 shrink-0 text-red-600/80 dark:text-red-400/80" strokeWidth={2} />
            ) : (
                <CircleSlash className="h-4 w-4 shrink-0 text-muted-foreground/70" strokeWidth={2} />
            )}
            <span className="min-w-0 flex-1 truncate text-muted-foreground" title={(failed && message.error) || undefined}>
                {failed ? 'It hit an error and stopped' : 'Stopped without finishing'}
            </span>
            {resend && (
                <button type="button" onClick={resend} className={cn(BUTTON_SECONDARY, 'h-8 px-3.5 text-[13px]')}>
                    Try again
                </button>
            )}
        </div>
    );
}

const isLive = (message: Message) => !message.isUser && !message.isComplete && !message.wasInterrupted && !message.failed;

/** One reply's work and words. A Try again waits while a run is going or a question is open: a send then answers it. */
function Reply({
    message,
    request,
    conversationId,
    workflowId,
    busy,
}: {
    message: Message;
    request?: Message;
    conversationId?: string;
    workflowId?: string;
    busy?: boolean;
}) {
    const gens = useSnapshot(activeGenStore).gens;
    const live = isLive(message);
    const gen = message.generationId ? gens[message.generationId] : undefined;
    const segments = message.editSegments ?? [];
    const events = segments.flatMap((s) => (s.type === 'events' ? s.events : []));
    const parts = deriveBuilderNodes(events);
    const work = replyWork(segments);
    const answer = segments.length ? work.answer : plainWords(message);
    // Live, only the gen's own words and events: nothing from before it (a turn before an answered question) is now.
    const now = live && gen ? liveWork(gen.text, gen.events as Record<string, unknown>[]) : {};
    const legacyEvents = !message.editSegments && message.workflowEditEvents?.length ? message.workflowEditEvents : null;
    const prompt = resendable(request);
    const resend =
        prompt && conversationId && !busy
            ? () => document.dispatchEvent(new CustomEvent('noclick:builder:retry', { detail: { prompt, conversationId } }))
            : undefined;
    const changed = parts.filter((p) => p.state === 'done' || p.state === 'removed').length;
    return (
        <div className="flex flex-col gap-2.5">
            {live ? (
                <BuilderLive step={now.step} said={now.said} status={message.editStatus} />
            ) : (
                <BuilderActions items={work.items} legacy={work.items.length ? [] : (message.editSteps ?? message.agenticSteps?.map((s) => s.text) ?? [])} />
            )}
            {parts.length > 0 && <BuilderParts parts={parts} workflowId={workflowId} frozen={!live} />}
            {legacyEvents && <WorkflowEditEventView events={legacyEvents} isComplete={!!message.isComplete} workflowId={workflowId} />}
            {!live && answer && <MarkdownRenderer content={answer} className="break-words text-[14.5px] leading-relaxed text-foreground/90" />}
            {(message.failed || message.incomplete) && <Ending message={message} resend={resend} />}
            {message.wasInterrupted && <p className="text-[13px] text-muted-foreground">You stopped it here.</p>}
            {message.isComplete && !message.failed && !message.incomplete && !message.wasInterrupted && changed > 0 && (
                <div className="flex items-center gap-2 text-[12.5px] text-muted-foreground" data-testid="builder-changed">
                    <span className="h-px flex-1 bg-border dark:bg-foreground/[0.08]" />
                    Changed {changed} {changed === 1 ? 'step' : 'steps'}
                </div>
            )}
        </div>
    );
}

function Change({ turn, conversationId, workflowId, busy }: { turn: BuilderTurn; conversationId?: string; workflowId?: string; busy?: boolean }) {
    return (
        <article className={cn('flex flex-col gap-3.5 border-t pt-5 first:border-t-0 first:pt-1', HAIRLINE)} data-testid="builder-change">
            {turn.request && <Request message={turn.request} />}
            {turn.replies.map((reply, i) => (
                <Reply key={reply.generationId ?? i} message={reply} request={turn.request} conversationId={conversationId} workflowId={workflowId} busy={busy} />
            ))}
        </article>
    );
}

export function BuilderThread({
    messages,
    conversationId,
    workflowId,
    after,
}: {
    messages: Message[];
    /** The chat's conversation, where a Try again sends its request. */
    conversationId?: string;
    workflowId?: string;
    /** Drawn under the last change. */
    after?: ReactNode;
}) {
    useEffect(() => {
        const w = window as unknown as { requestIdleCallback?: (cb: () => void) => number };
        if (w.requestIdleCallback) w.requestIdleCallback(() => preloadMarkdownRenderer());
        else setTimeout(preloadMarkdownRenderer, 300);
    }, []);
    const turns = builderTurns(messages);
    const busy = messages.some(isLive) || !!messages[messages.length - 1]?.pendingAsk;
    // Pinned to the newest change unless the reader scrolled up; a request of their own always pins.
    const requests = useRef(requestsIn(messages));
    const sent = requestsIn(messages) > requests.current;
    requests.current = requestsIn(messages);
    const scroller = useStickToBottom<HTMLDivElement>([messages]);
    if (sent) scroller.pin();
    return (
        <div
            ref={scroller.ref}
            onScroll={scroller.onScroll}
            className="h-full overflow-y-auto px-4 pb-6 pt-1 scrollbar-subtle [mask-image:linear-gradient(to_bottom,transparent,black_14px)]"
            data-testid="builder-thread"
        >
            {/* One child holding every change: the scroller follows it as it grows. */}
            <div>
                <ProgressMotion />
                {turns.map((turn, i) => (
                    <Change key={i} turn={turn} conversationId={conversationId} workflowId={workflowId} busy={busy} />
                ))}
                {after}
            </div>
        </div>
    );
}
