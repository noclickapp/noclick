// What a message points at, as a pill: an automation or a connected account, in the composer's tray (removable) and
// on the sent message. A surface that knows the account's app passes its logo; otherwise the kind's own mark shows.
import type { ReactNode } from 'react';
import { X } from 'lucide-react';
import type { ChatReference } from '@/lib/agentThread/messages';
import { ACTION_GLYPHS, AutomationMark } from '@/ui/glyphs';
import { cn } from '@/ui/utils';

/** The kind's own mark for what a message points at: an automation's, or an account's. */
export function ReferenceMark({ reference }: { reference: ChatReference }) {
    return reference.kind === 'automation' ? <AutomationMark className="h-4 w-4" /> : <ACTION_GLYPHS.account className="h-3.5 w-3.5" strokeWidth={2} />;
}

export function ChatReferenceChip({ reference, mark, onRemove, className }: { reference: ChatReference; mark?: ReactNode; onRemove?: () => void; className?: string }) {
    return (
        <span
            data-testid="chat-reference-chip"
            className={cn('inline-flex h-8 max-w-[260px] items-center gap-1.5 rounded-full bg-foreground/[0.06] pl-2 text-[13px] text-foreground', onRemove ? 'pr-1' : 'pr-3', className)}
        >
            <span className="grid h-5 w-5 shrink-0 place-items-center text-foreground/70">
                {mark ?? <ReferenceMark reference={reference} />}
            </span>
            <span className="truncate">{reference.label}</span>
            {onRemove && (
                <button
                    type="button"
                    onClick={onRemove}
                    aria-label={`Remove ${reference.label}`}
                    className="grid h-6 w-6 shrink-0 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-foreground/[0.08] hover:text-foreground"
                >
                    <X className="h-3.5 w-3.5" />
                </button>
            )}
        </span>
    );
}
