// A call and an email as a chat thread draws them: a call's lines as one card, an email as the message it was, so a
// thread reads as one conversation across the ways people reached its agent.
import type { ReactNode } from 'react';
import { Mail, Phone } from 'lucide-react';
import { cn } from '@/ui/utils';
import { CARD, GlyphTile, InlineCard } from '@/ui/chat/primitives';

export interface CallLine {
    who: 'you' | 'noclick';
    text: string;
}

/** What was said on a call, a line each: who, then what. `live` announces lines as they arrive. */
export function CallLines({ lines, live, testId }: { lines: { who: string; text: string }[]; live?: boolean; testId?: string }) {
    return (
        <dl className="space-y-1.5 text-[14px] leading-snug" data-testid={testId} aria-live={live ? 'polite' : undefined}>
            {lines.map((line, i) => (
                <div key={i} className={cn('flex gap-3', live && 'motion-safe:animate-in motion-safe:fade-in motion-safe:duration-300')}>
                    <dt className="w-16 shrink-0 text-[12.5px] leading-[1.45rem] text-muted-foreground">{line.who}</dt>
                    <dd className="min-w-0 whitespace-pre-wrap break-words text-foreground/90">{line.text}</dd>
                </div>
            ))}
        </dl>
    );
}

/** A call with NoClick: who, how long, and what was said. */
export function CallCard({ title, meta, lines, actions }: { title: string; meta?: string; lines: CallLine[]; actions?: ReactNode }) {
    return (
        <InlineCard
            lead={
                <GlyphTile>
                    <Phone className="h-4 w-4" />
                </GlyphTile>
            }
            title={title}
            meta={meta}
            actions={actions}
        >
            <CallLines lines={lines.map((line) => ({ who: line.who === 'you' ? 'You' : 'NoClick', text: line.text }))} testId="coordinator-call" />
        </InlineCard>
    );
}

/** An email you sent NoClick's address, kept as an email: its subject, who it was from and to, then what it said
 *  (the thread quoted under it already left out). Mail from before NoClick kept the addresses shows neither line. */
export function EmailMessage({ subject, body, from, to, time, files }: { subject?: string; body: string; from?: string; to?: string; time?: string; files?: ReactNode }) {
    return (
        <div className="flex flex-col items-end gap-1.5" data-testid="coordinator-email-message">
            <article className={cn(CARD, 'max-w-[480px] px-4 py-3.5')}>
                <header className="flex items-baseline gap-3">
                    <h3 className={cn('min-w-0 flex-1 break-words text-[15px] font-medium leading-snug', subject ? 'text-foreground' : 'text-muted-foreground')}>{subject || '(no subject)'}</h3>
                    {time && <span className="shrink-0 text-[12px] tabular-nums text-muted-foreground">{time}</span>}
                </header>
                {(from || to) && (
                    <dl className="mt-1 grid grid-cols-[auto_minmax(0,1fr)] gap-x-2.5 text-[12.5px] leading-[1.6]">
                        {from && (
                            <>
                                <dt className="text-muted-foreground">From</dt>
                                <dd className="truncate text-foreground/80">{from}</dd>
                            </>
                        )}
                        {to && (
                            <>
                                <dt className="text-muted-foreground">To</dt>
                                <dd className="truncate text-foreground/80">{to}</dd>
                            </>
                        )}
                    </dl>
                )}
                {body && <p className="mt-3 whitespace-pre-wrap break-words text-[14px] leading-relaxed text-foreground/90">{body}</p>}
                {files && <div className="mt-3 flex flex-wrap gap-1.5">{files}</div>}
            </article>
            <span className="inline-flex items-center gap-1.5 px-1 text-[12px] text-muted-foreground">
                <Mail className="h-3.5 w-3.5" />
                Email
            </span>
        </div>
    );
}
