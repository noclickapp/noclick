// The user turn a fired trigger took, rendered as the event it was — the
// same native frame the run popup's "What came in" wears (a Slack row, a
// WhatsApp bubble, an email pane) — instead of the agent's text view of it.
// The persisted turn carries the fired node + its bounded output, so this
// derives the lead exactly as runStory does; when no lead derives (a
// schedule tick, an id-only notification) the agent's concise text stands in,
// with the sanitized event behind a disclosure.

import { useMemo, useState } from 'react';
import { ChevronDown, Zap } from 'lucide-react';
import { cn } from '~/lib/utils';
import { getNodeIconMeta } from '~/lib/nodeIconRegistry';
import { SerializedIcon } from '~/components/shared/SerializedIcon';
import { InboundMessage } from '~/components/design/rehearsal/native';
import {
    deriveLead,
    humanizeOp,
    sanitizeEventPayload,
    slugOfType,
    toScenario,
} from '~/components/design/run-results/runStory';
import type { ChatTriggerEvent } from '~/hooks/useAgentChat';

const TEXT_PREVIEW_LINES = 8;

export function TriggerEventMessage({
    trigger,
    text,
}: {
    trigger: ChatTriggerEvent;
    text: string;
}) {
    const slug = slugOfType(trigger.nodeType);
    const scenario = useMemo(() => {
        const lead =
            deriveLead(slug, trigger.output) ??
            deriveLead(slug, sanitizeEventPayload(trigger.output));
        return lead
            ? toScenario(
                  {
                      nodeId: trigger.nodeId,
                      nodeType: trigger.nodeType,
                      label: trigger.label ?? slug,
                      operation: trigger.operation,
                  },
                  lead
              )
            : undefined;
    }, [slug, trigger]);
    // The app's own mark and name lead the caption: a Slack row and a Discord
    // row share an anatomy, and the node's label ("Support channel") may not
    // say which app it is. The light icon registry serves it (populated by the
    // app routes' loaders); an unloaded registry shows the trigger bolt.
    const meta = getNodeIconMeta(trigger.nodeType);
    const appName = meta?.label;
    const caption = [
        appName,
        trigger.label && trigger.label !== appName ? trigger.label : undefined,
        trigger.operation && humanizeOp(trigger.operation),
    ]
        .filter(Boolean)
        .join(' · ');
    return (
        <div
            data-testid="agent-chat-trigger-message"
            className="flex flex-col items-end gap-1.5"
        >
            <span className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                {meta?.iconHtml ? (
                    <SerializedIcon
                        html={meta.iconHtml}
                        iconColor={meta.iconColor}
                        className="h-3.5 w-3.5 shrink-0"
                    />
                ) : (
                    <Zap className="h-3 w-3" />
                )}
                <span data-testid="agent-chat-trigger-caption">{caption || 'Trigger'}</span>
            </span>
            <div className="w-full max-w-[85%]">
                {scenario ? (
                    <InboundMessage scenario={scenario} />
                ) : (
                    <EventText text={text} output={trigger.output} />
                )}
            </div>
        </div>
    );
}

/** The agent's concise view of an event no frame fits — clamped, with the
 *  sanitized payload one click away rather than dumped into the bubble. */
function EventText({ text, output }: { text: string; output: unknown }) {
    const [expanded, setExpanded] = useState(false);
    const [showRaw, setShowRaw] = useState(false);
    const lines = text.split('\n');
    const clamped = !expanded && lines.length > TEXT_PREVIEW_LINES;
    const shown = clamped ? lines.slice(0, TEXT_PREVIEW_LINES).join('\n') : text;
    const raw = useMemo(() => {
        const event = sanitizeEventPayload(output);
        return Object.keys(event).length ? JSON.stringify(event, null, 2) : null;
    }, [output]);
    return (
        <div className="rounded-2xl rounded-br-sm bg-secondary px-4 py-2.5 text-[13.5px] leading-relaxed text-foreground">
            <p className="m-0 whitespace-pre-wrap break-words">{shown}</p>
            {(clamped || expanded) && lines.length > TEXT_PREVIEW_LINES ? (
                <button
                    type="button"
                    onClick={() => setExpanded((v) => !v)}
                    className="mt-1 text-[12px] text-muted-foreground hover:text-foreground"
                >
                    {expanded ? 'Show less' : `Show all ${lines.length} lines`}
                </button>
            ) : null}
            {raw ? (
                <div className="mt-2 border-t border-border/60 pt-1.5">
                    <button
                        type="button"
                        onClick={() => setShowRaw((v) => !v)}
                        data-testid="agent-chat-trigger-raw-toggle"
                        className="flex items-center gap-1 text-[12px] text-muted-foreground hover:text-foreground"
                    >
                        <ChevronDown
                            className={cn('h-3 w-3 transition-transform', showRaw && 'rotate-180')}
                        />
                        Event payload
                    </button>
                    {showRaw ? (
                        <pre className="mt-1.5 max-h-72 overflow-auto rounded-md bg-background/60 p-2 text-[11.5px] leading-snug text-muted-foreground">
                            {raw}
                        </pre>
                    ) : null}
                </div>
            ) : null}
        </div>
    );
}
