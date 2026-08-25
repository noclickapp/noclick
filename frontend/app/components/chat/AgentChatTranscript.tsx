// Presentational agent-chat transcript (user bubbles + agent markdown), moved
// verbatim out of AgentChatBlock so the public shared-agent page (/a/{linkId})
// can render the exact same conversation UI without pulling in the editor's
// settings sidebar, model pickers, or node-config plumbing.

import { memo, useState } from 'react';
import { Check, Copy, FileText } from 'lucide-react';
import { MarkdownRenderer } from '~/components/chat/MarkdownRenderer';
import { AgentChatSteps } from '~/components/chat/AgentChatSteps';
import { ShortcutTooltip } from '~/components/shared/ShortcutTooltip';
import { ThinkingOrb } from '~/components/shared/ThinkingOrb';
import {
    liveTailIndex,
    type AgentChatMessage,
    type BuilderPromptProposal,
} from '~/hooks/useAgentChat';
import type { ContentItem } from '~/types/socket-schema.generated';

/** Copy-to-clipboard action under a completed agent reply. Copies the raw
 *  markdown (what you'd paste elsewhere), flashes a check on success. */
function CopyMessageButton({ text }: { text: string }) {
    const [copied, setCopied] = useState(false);
    return (
        <ShortcutTooltip
            label={copied ? 'Copied' : 'Copy response'}
            side="bottom"
        >
            <button
                type="button"
                aria-label="Copy response"
                data-testid="agent-chat-copy"
                onClick={async () => {
                    try {
                        await navigator.clipboard.writeText(text);
                        setCopied(true);
                        setTimeout(() => setCopied(false), 1500);
                    } catch {
                        // Clipboard unavailable (permissions / insecure context) —
                        // nothing sane to do; the button simply doesn't flash.
                    }
                }}
                className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground/60 transition-colors hover:bg-foreground/[0.06] hover:text-foreground"
            >
                {copied ? (
                    <Check className="h-3.5 w-3.5 text-emerald-600 dark:text-emerald-400" />
                ) : (
                    <Copy className="h-3.5 w-3.5" />
                )}
            </button>
        </ShortcutTooltip>
    );
}

/** Decision memory for builder proposals, keyed by the server-minted
 *  proposal_id. The card is re-rendered from the PERSISTED transcript after
 *  reconcile adoption and reloads — without this, an already-approved
 *  proposal would come back with live Approve buttons (double-submit bait). */
const BUILDER_DECISION_PREFIX = 'nc-builder-proposal:';
type BuilderDecision = 'approved' | 'dismissed';

function storedBuilderDecision(
    pid: string | null | undefined
): BuilderDecision | null {
    if (!pid) return null;
    try {
        const v = localStorage.getItem(BUILDER_DECISION_PREFIX + pid);
        return v === 'approved' || v === 'dismissed' ? v : null;
    } catch {
        return null;
    }
}

/** Approval card for the agent's prompt_builder tool call. Approving expands
 *  the builder sidebar and submits the proposed prompt via the same DOM
 *  events the empty-canvas hero uses (`noclick:sidebar:expand` +
 *  `noclick:builder:submit`, handled in NoClick.tsx), so the builder picks it
 *  up as a fresh conversation. */
function BuilderPromptCard({
    proposal,
    onDecision,
}: {
    proposal: BuilderPromptProposal;
    onDecision?: (
        proposal: BuilderPromptProposal,
        decision: BuilderDecision
    ) => void;
}) {
    // The persisted verdict (restored from the transcript's builder_decision
    // events — cross-device) wins over the localStorage fallback.
    const [decision, setDecision] = useState<BuilderDecision | null>(
        () => proposal.decision ?? storedBuilderDecision(proposal.proposal_id)
    );
    const decide = (d: BuilderDecision) => {
        setDecision(d);
        try {
            if (proposal.proposal_id)
                localStorage.setItem(
                    BUILDER_DECISION_PREFIX + proposal.proposal_id,
                    d
                );
        } catch {
            /* storage unavailable — decision stays session-local */
        }
        onDecision?.(proposal, d);
    };
    return (
        <div
            data-testid="agent-chat-builder-prompt"
            className="min-w-0 max-w-xl rounded-xl border border-border bg-card px-4 py-3.5"
        >
            <div className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground dark:text-zinc-500">
                Proposed workflow edit
            </div>
            <div className="mt-2.5 border-l-2 border-foreground/20 pl-3 text-sm leading-relaxed text-foreground/90 whitespace-pre-wrap break-words">
                {proposal.prompt}
            </div>
            <div className="mt-3.5 flex items-center gap-2">
                {decision === null ? (
                    <>
                        <button
                            type="button"
                            data-testid="agent-chat-builder-approve"
                            onClick={() => {
                                decide('approved');
                                document.dispatchEvent(
                                    new CustomEvent('noclick:sidebar:expand')
                                );
                                document.dispatchEvent(
                                    new CustomEvent('noclick:builder:submit', {
                                        // The anchored variant names the requesting agent node, so
                                        // the builder targets the right agent in a multi-agent
                                        // workflow. The card displays the clean prompt.
                                        detail: {
                                            prompt:
                                                proposal.anchored_prompt ??
                                                proposal.prompt,
                                        },
                                    })
                                );
                            }}
                            className="rounded-lg bg-primary px-3.5 py-1.5 text-xs font-medium text-primary-foreground transition-opacity hover:opacity-90"
                        >
                            Send to builder
                        </button>
                        <button
                            type="button"
                            data-testid="agent-chat-builder-dismiss"
                            onClick={() => decide('dismissed')}
                            className="rounded-lg px-3 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground"
                        >
                            Dismiss
                        </button>
                    </>
                ) : (
                    <div className="text-xs text-muted-foreground/80">
                        {decision === 'approved'
                            ? 'Sent to the builder'
                            : 'Dismissed'}
                    </div>
                )}
            </div>
        </div>
    );
}

/** Image URLs in order from a multimodal content array. */
function imagesOfContent(content: ContentItem[] | undefined): string[] {
    if (!Array.isArray(content)) return [];
    const out: string[] = [];
    for (const c of content) {
        if (c.type !== 'image_url') continue;
        const raw = c.image_url;
        if (!raw) continue;
        if (typeof raw === 'string') out.push(raw);
        else if (raw.url) out.push(raw.url);
    }
    return out;
}

/** Video URLs in order from a multimodal content array (generated by
 *  video / kling output models). */
function videosOfContent(content: ContentItem[] | undefined): string[] {
    if (!Array.isArray(content)) return [];
    const out: string[] = [];
    for (const c of content) {
        if (c.type === 'video_url' && c.video_url) out.push(c.video_url);
    }
    return out;
}

/** The "agent is working" orb — the house `working` style both standalone
 *  (before any text has arrived) and inline at the end of streaming text. The
 *  two differ only in layout and label, so the turn reads as one state. */
export function ThinkingIndicator({ inline = false }: { inline?: boolean }) {
    return inline ? (
        <ThinkingOrb
            data-testid="agent-chat-streaming-dot"
            aria-label="Agent is responding"
            className="ml-1 inline-block align-text-bottom"
        />
    ) : (
        <ThinkingOrb
            data-testid="agent-chat-thinking"
            aria-label="Agent is thinking"
            className="block"
        />
    );
}

/** ChatGPT-style transcript: user messages are right-aligned bubbles, agent
 *  messages are full-width markdown with no chrome. Kept focused on the
 *  message shapes this surface actually produces — no agentic-steps /
 *  workflow-edit machinery from the builder chat. Renders a thinking-dots
 *  row at the tail when streaming has started but no text has arrived. */
export const AgentChatTranscript = memo(function AgentChatTranscript({
    messages,
    isStreaming,
    errorReason,
    errorActions,
    onOpenWorkspaceFile,
    onBuilderDecision,
}: {
    messages: AgentChatMessage[];
    isStreaming: boolean;
    errorReason: string | null;
    errorActions?: React.ReactNode;
    /** Opens the workspace file preview for a sandbox path an agent message
     *  links (e.g. /workspace/report.md). Omitted on surfaces without the file
     *  view (public share page) — those render inert chips, never dead links. */
    onOpenWorkspaceFile?: (path: string) => void;
    /** Reports an approve/dismiss verdict on a builder proposal card so the
     *  owner surface can persist it (agent:builder_decision — card state
     *  restore + the agent's next-turn platform note). Omitted on surfaces
     *  that never render cards (public share page). */
    onBuilderDecision?: (
        proposal: BuilderPromptProposal,
        decision: 'approved' | 'dismissed'
    ) => void;
}) {
    // The live tail skips trailing approval cards — they sink below the turn,
    // so an in-flight bubble can sit ABOVE a card and must still own the
    // streaming indicator.
    const last = messages[liveTailIndex(messages)];
    // Show the standalone pulsing dot when there is no IN-FLIGHT agent bubble to
    // host the inline cursor: no messages yet, a user message tail, or a
    // COMPLETE agent tail (a turn started elsewhere — presence-driven busy —
    // has no local bubble until its frames arrive). An in-flight bubble owns
    // the indicator via its inline cursor/steps; an error tail keeps the space
    // for the banner + recovery actions.
    const showThinkingDots =
        isStreaming &&
        (!last || last.isUser || (last.isComplete && !last.error));
    return (
        <div
            data-testid="agent-chat-transcript"
            className="flex flex-col gap-6"
        >
            {messages.map((msg, i) => {
                const images = imagesOfContent(msg.content);
                const videos = videosOfContent(msg.content);
                const showCursor = !msg.isUser && !msg.isComplete;
                if (msg.error) {
                    return (
                        <div
                            key={i}
                            data-testid="agent-chat-error-message"
                            className="min-w-0 text-sm text-red-600/90 dark:text-red-400/90 border border-red-200 dark:border-red-900/40 bg-red-50 dark:bg-red-950/30 rounded-lg px-3 py-2 whitespace-pre-wrap break-words"
                        >
                            <div>
                                <span className="font-medium">
                                    Agent stopped:
                                </span>{' '}
                                {msg.error}
                            </div>
                            {/* Recovery actions only on the CURRENT stopped state, not
                  historical error bubbles further up the transcript. */}
                            {i === messages.length - 1 ? errorActions : null}
                        </div>
                    );
                }
                if (msg.builderPrompt) {
                    return (
                        <BuilderPromptCard
                            key={i}
                            proposal={msg.builderPrompt}
                            onDecision={onBuilderDecision}
                        />
                    );
                }
                if (msg.isUser) {
                    return (
                        <div
                            key={i}
                            data-testid="agent-chat-user-message"
                            className="flex justify-end"
                        >
                            <div className="max-w-[80%] rounded-2xl rounded-br-sm bg-secondary text-foreground text-[15px] leading-relaxed px-4 py-2.5 whitespace-pre-wrap break-words">
                                {images.map((url, j) => (
                                    <img
                                        key={j}
                                        src={url}
                                        alt=""
                                        className="rounded-lg mb-2 max-h-[400px] object-contain"
                                    />
                                ))}
                                {(msg.attachments ?? []).map((f, j) => (
                                    <a
                                        key={j}
                                        href={f.url}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        data-testid="agent-chat-file-attachment"
                                        className="mb-2 flex items-center gap-1.5 rounded-lg border border-border/60 bg-background/40 px-2.5 py-1.5 text-xs text-foreground/90 no-underline transition-colors hover:bg-background/60"
                                    >
                                        <FileText className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                                        <span className="truncate">
                                            {f.name}
                                        </span>
                                    </a>
                                ))}
                                {msg.text}
                            </div>
                        </div>
                    );
                }
                const hasSteps = !!msg.steps?.length;
                // All steps resolved but the turn hasn't: the gap between the last
                // tool completing and the response text landing over the relay — keep
                // a live indicator so the bubble doesn't
                // read as finished-but-empty.
                const awaitingResponse =
                    hasSteps &&
                    showCursor &&
                    msg.steps!.every((s) => s.status === 'completed');
                return (
                    <div
                        key={i}
                        data-testid="agent-chat-agent-message"
                        className="text-[15px] leading-relaxed text-foreground"
                    >
                        {hasSteps ? (
                            <AgentChatSteps
                                steps={msg.steps!}
                                turnComplete={msg.isComplete}
                            />
                        ) : null}
                        {images.map((url, j) => (
                            <img
                                key={j}
                                src={url}
                                alt=""
                                className="rounded-lg mb-3 max-h-[400px] object-contain"
                            />
                        ))}
                        {videos.map((url, j) => (
                            <video
                                key={j}
                                src={url}
                                controls
                                data-testid="agent-chat-video"
                                className="rounded-lg mb-3 max-h-[400px] w-full object-contain bg-background"
                            />
                        ))}
                        {msg.text ? (
                            <>
                                <MarkdownRenderer
                                    content={msg.text}
                                    cursor={
                                        showCursor ? (
                                            <ThinkingIndicator inline />
                                        ) : undefined
                                    }
                                    onSandboxPathClick={onOpenWorkspaceFile}
                                />
                                {msg.isComplete ? (
                                    // -ml aligns the ICON glyph (centered in its 28px hit area)
                                    // with the message text's left edge, ChatGPT-style.
                                    <div className="-ml-1.5 mt-1.5 flex items-center gap-1">
                                        <CopyMessageButton text={msg.text} />
                                    </div>
                                ) : null}
                            </>
                        ) : awaitingResponse ? (
                            <ThinkingIndicator />
                        ) : images.length > 0 ||
                          videos.length > 0 ||
                          hasSteps ? null : showCursor ||
                          (isStreaming && i === messages.length - 1) ? null : (
                            <span className="text-muted-foreground/70 dark:text-zinc-600 italic">
                                No response.
                            </span>
                        )}
                    </div>
                );
            })}
            {showThinkingDots ? <ThinkingIndicator /> : null}
            {/* Trailing banner for errors that aren't already shown as a message
          bubble (e.g. the frontend pre-flight credential error). A backend
          agent:state error arrives BOTH as errorReason and a msg.error bubble;
          suppress the banner in that case so it isn't shown twice. */}
            {errorReason && !last?.error ? (
                <div
                    data-testid="agent-chat-error"
                    className="min-w-0 text-sm text-red-600/90 dark:text-red-400/90 border border-red-200 dark:border-red-900/40 bg-red-50 dark:bg-red-950/30 rounded-lg px-3 py-2 break-words"
                >
                    <div>
                        <span className="font-medium">Agent stopped:</span>{' '}
                        {errorReason}
                    </div>
                    {errorActions}
                </div>
            ) : null}
        </div>
    );
});
