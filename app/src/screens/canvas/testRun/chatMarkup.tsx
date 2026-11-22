/* Chat-dialect text rendering for the outbound frames: what the agent composed
   for Slack/WhatsApp/Telegram uses CHAT markup, not standard markdown —
   `*bold*` is bold (not italic), `_italic_`, `~strike~`, `` `code` `` — so the
   standard MarkdownRenderer would misread it. This is a tiny line-preserving
   renderer for exactly those inline forms; URLs render in the app's link
   accent but stay non-interactive (a live link inside a simulated message is
   an invitation to leave the rehearsal). */

import type { ReactNode } from 'react';

const TOKEN =
    /(\*[^*\n]+\*|_[^_\n]+_|~[^~\n]+~|`[^`\n]+`|https?:\/\/[^\s<>]+)/g;

function renderInline(text: string, accent?: string): ReactNode[] {
    const out: ReactNode[] = [];
    let last = 0;
    let key = 0;
    for (const m of text.matchAll(TOKEN)) {
        const at = m.index ?? 0;
        if (at > last) out.push(text.slice(last, at));
        const tok = m[0];
        if (tok.startsWith('http')) {
            out.push(
                <span key={key++} style={{ color: accent }} className="underline decoration-current/40 underline-offset-2">
                    {tok}
                </span>
            );
        } else if (tok.startsWith('*')) {
            out.push(<strong key={key++} className="font-semibold">{tok.slice(1, -1)}</strong>);
        } else if (tok.startsWith('_')) {
            out.push(<em key={key++}>{tok.slice(1, -1)}</em>);
        } else if (tok.startsWith('~')) {
            out.push(<s key={key++}>{tok.slice(1, -1)}</s>);
        } else {
            out.push(
                <code key={key++} className="rounded bg-current/10 px-1 py-px font-mono text-[0.9em]">
                    {tok.slice(1, -1)}
                </code>
            );
        }
        last = at + tok.length;
    }
    if (last < text.length) out.push(text.slice(last));
    return out;
}

/** The composed message with chat markup applied, line structure intact. */
export function ChatMarkup({ text, accent }: { text: string; accent?: string }) {
    const lines = text.split('\n');
    return (
        <>
            {lines.map((line, i) => (
                <span key={i}>
                    {i > 0 && '\n'}
                    {renderInline(line, accent)}
                </span>
            ))}
        </>
    );
}
