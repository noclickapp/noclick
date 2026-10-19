// What a message points at, as a pill: an automation or a connected account, in
// the composer's tray (removable) and on the sent message. A surface that knows
// the account's app passes its logo; otherwise the kind's own mark shows.
import type { ReactNode } from 'react';
import { FileText, X } from 'lucide-react';
import { ACTION_GLYPHS, AutomationMark } from '~/components/shell/glyphs';
import type { ChatReference } from '~/lib/agentChat';
import { cn } from '~/lib/utils';

export function ChatReferenceChip({ reference, mark, onRemove, className }: { reference: ChatReference; mark?: ReactNode; onRemove?: () => void; className?: string }) {
    return (
        <span
            data-testid="chat-reference-chip"
            className={cn('inline-flex h-8 max-w-[260px] items-center gap-1.5 rounded-full bg-foreground/[0.06] pl-2 text-[13px] text-foreground', onRemove ? 'pr-1' : 'pr-3', className)}
        >
            <span className="grid h-5 w-5 shrink-0 place-items-center text-foreground/70">
                {mark ?? (reference.kind === 'automation' ? <AutomationMark className="h-4 w-4" /> : <ACTION_GLYPHS.account className="h-3.5 w-3.5" strokeWidth={2} />)}
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

/** A sent file, as a card: its kind in a tile, its name, its type. */
export function ChatFileCard({ name, url, mimeType }: { name: string; url: string; mimeType?: string }) {
    const ext = name.includes('.') ? name.split('.').pop()!.toUpperCase().slice(0, 5) : (mimeType?.split('/')[1] ?? 'File').toUpperCase().slice(0, 5);
    return (
        <a
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            data-testid="agent-chat-file-attachment"
            className="flex max-w-[260px] items-center gap-2.5 rounded-2xl bg-card py-2 pl-2 pr-3.5 no-underline ring-1 ring-inset ring-border transition-colors hover:bg-foreground/[0.03] dark:bg-foreground/[0.03] dark:ring-foreground/[0.08] dark:hover:bg-foreground/[0.05]"
        >
            <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-foreground/[0.06]">
                <FileText className="h-4 w-4 text-muted-foreground" />
            </span>
            <span className="min-w-0">
                <span className="block truncate text-[13.5px] font-medium text-foreground">{name}</span>
                <span className="block text-[12px] text-muted-foreground">{ext}</span>
            </span>
        </a>
    );
}
