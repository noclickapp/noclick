// What a message points at, as a pill: an automation or a connected account, in
// the composer's tray (removable) and on the sent message. A surface that knows
// the account's app passes its logo; otherwise the kind's own mark shows. And a
// file a message carries or embeds, as a card.
import { lazy, Suspense, useState, type MouseEvent, type ReactNode } from 'react';
import { X } from 'lucide-react';
import { fmtBytes } from '~/components/dashboard/formatters';
import { ACTION_GLYPHS, AutomationMark } from '~/components/shell/glyphs';
import { FileGlyph } from '~/components/shell/resources/FileGlyph';
import type { ChatReference } from '~/lib/agentChat';
import { extensionOf, fileKindOf, previewType } from '~/lib/embedKind';
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

// The preview loads with the first file opened, so a page that only shows a card never loads it.
const FilePreviewDialog = lazy(() => import('~/components/dashboard/FilePreviewDialog').then((m) => ({ default: m.FilePreviewDialog })));

/** A file in a message, as a card: its kind in a tile, its title (what the message calls it, an embed's caption,
 *  else its name), its type and its size when known. One the preview shows (a PDF, a picture, text of a known size)
 *  opens there; any other downloads. */
export function ChatFileCard({ name, url, mimeType, title, sizeBytes }: { name: string; url: string; mimeType?: string; title?: string; sizeBytes?: number | null }) {
    // Null until first opened; the dialog then stays mounted so it closes as a dialog does and gives focus back.
    const [previewing, setPreviewing] = useState<boolean | null>(null);
    const preview = previewType(name, sizeBytes ?? null);
    const type = (extensionOf(name) || mimeType?.split('/')[1] || 'File').toUpperCase().slice(0, 5);
    const open = (e: MouseEvent) => {
        // A modified click opens the file in a tab, as a link does.
        if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return;
        e.preventDefault();
        setPreviewing(true);
    };
    return (
        <>
            <a
                href={url}
                target="_blank"
                rel="noopener noreferrer"
                download={preview ? undefined : name}
                onClick={preview ? open : undefined}
                title={title || name}
                data-testid="agent-chat-file-attachment"
                className="flex max-w-[260px] items-center gap-2.5 rounded-2xl bg-card py-2 pl-2 pr-3.5 no-underline ring-1 ring-inset ring-border transition-colors hover:bg-foreground/[0.03] dark:bg-foreground/[0.03] dark:ring-foreground/[0.08] dark:hover:bg-foreground/[0.05]"
            >
                <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-foreground/[0.06]">
                    <FileGlyph kind={fileKindOf(name)} />
                </span>
                <span className="min-w-0">
                    <span className="block truncate text-[13.5px] font-medium text-foreground">{title || name}</span>
                    <span className="block text-[12px] text-muted-foreground">
                        {type}
                        {sizeBytes ? ` · ${fmtBytes(sizeBytes)}` : ''}
                    </span>
                </span>
            </a>
            {previewing !== null && preview && (
                <Suspense fallback={null}>
                    <FilePreviewDialog
                        request={
                            previewing
                                ? {
                                      file: { path: name, size: sizeBytes ?? 0, mtime: '', kind: fileKindOf(name), url, mime: preview },
                                      source: { id: url, kind: 'resources', label: '', sublabel: '', files: [] },
                                  }
                                : null
                        }
                        onClose={() => setPreviewing(false)}
                    />
                </Suspense>
            )}
        </>
    );
}
