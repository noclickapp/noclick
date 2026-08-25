// Presentational chat composer, extracted from AgentChatBlock so the public
// shared-agent page can reuse the exact same input UI. Structured like a
// modern chat composer: optional attachment tray on top, auto-growing textarea,
// a controls row inside the same card underneath (attach + hint on the left,
// send button bottom-right). Owns only keyboard handling, height management,
// and file intake (picker / paste / drop) — validation, uploads, streaming
// guards, and dispatch stay with the caller. Attachment UI renders only when
// the caller passes `onAddFiles` (the public share page doesn't, yet).

import { useEffect, useRef, useState } from 'react';
import { ArrowUp, FileText, Loader2, Paperclip, X } from 'lucide-react';
import { UploadProgressBar } from '~/components/ui/upload-progress';
import { cn } from '~/lib/utils';
import { useIsMobile } from '~/hooks/useIsMobile';
import type { PendingChatAttachment } from '~/hooks/useChatAttachments';

// Cap for the auto-grow: past this the textarea scrolls internally. Lower on
// mobile so the composer never dominates a small screen.
const MAX_TEXTAREA_HEIGHT_PX = 220;
const MAX_TEXTAREA_HEIGHT_PX_MOBILE = 120;

function AttachmentTrayItem({
    attachment,
    onRemove,
}: {
    attachment: PendingChatAttachment;
    onRemove?: (localId: string) => void;
}) {
    const removeButton = onRemove ? (
        <button
            type="button"
            onClick={() => onRemove(attachment.localId)}
            aria-label={`Remove ${attachment.name}`}
            className="absolute -right-1.5 -top-1.5 flex h-[18px] w-[18px] items-center justify-center rounded-full border border-border bg-popover text-muted-foreground opacity-0 shadow-sm transition-opacity hover:text-foreground group-hover:opacity-100"
        >
            <X className="h-3 w-3" strokeWidth={2.5} />
        </button>
    ) : null;

    if (attachment.previewUrl) {
        return (
            <div
                // overflow-hidden lives on the INNER frame (it's only there to
                // round the img corners) — on this outer anchor it clipped the
                // remove badge and the hover preview, both of which overhang.
                className="group relative shrink-0"
                title={
                    attachment.status === 'error'
                        ? attachment.error
                        : attachment.name
                }
                data-testid="chat-attachment-thumb"
            >
                <div
                    className={cn(
                        'relative h-14 w-14 overflow-hidden rounded-lg border',
                        attachment.status === 'error'
                            ? 'border-red-500/60'
                            : 'border-border/70'
                    )}
                >
                    <img
                        src={attachment.previewUrl}
                        alt={attachment.name}
                        className="h-full w-full object-cover"
                    />
                    {attachment.status === 'uploading' ? (
                        <div className="absolute inset-0 flex items-center justify-center bg-black/40">
                            <Loader2 className="h-4 w-4 animate-spin text-white" />
                            <UploadProgressBar
                                fraction={attachment.progress ?? 0}
                                className="absolute inset-x-1.5 bottom-1.5 h-0.5 bg-white/25"
                                barClassName="bg-white"
                            />
                        </div>
                    ) : null}
                </div>
                {/* Larger preview while hovering the thumb. pointer-events-none
                    so it never traps the cursor away from the remove badge. */}
                <div className="pointer-events-none absolute bottom-full left-0 z-50 mb-2 hidden group-hover:block">
                    <div className="rounded-lg border border-border bg-popover p-1 shadow-xl">
                        <img
                            src={attachment.previewUrl}
                            alt=""
                            className="max-h-64 max-w-[320px] rounded-md object-contain"
                        />
                    </div>
                </div>
                {removeButton}
            </div>
        );
    }
    return (
        <div
            className={cn(
                'group relative flex max-w-[180px] shrink-0 items-center gap-1.5 rounded-lg border px-2.5 py-2 text-xs',
                attachment.status === 'error'
                    ? 'border-red-500/60 text-red-600 dark:text-red-400'
                    : 'border-border/70 text-foreground/90'
            )}
            title={
                attachment.status === 'error'
                    ? attachment.error
                    : attachment.name
            }
            data-testid="chat-attachment-chip"
        >
            {attachment.status === 'uploading' ? (
                <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-muted-foreground" />
            ) : (
                <FileText className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
            )}
            <div className="min-w-0 flex-1">
                <span className="block truncate">{attachment.name}</span>
                {attachment.status === 'uploading' ? (
                    <UploadProgressBar fraction={attachment.progress ?? 0} className="mt-1 h-0.5" />
                ) : null}
            </div>
            {removeButton}
        </div>
    );
}

export function AgentChatComposer({
    value,
    onChange,
    onSubmit,
    placeholder,
    inputDisabled,
    sendDisabled,
    textareaRef,
    footerEnd,
    attachments,
    onAddFiles,
    onRemoveAttachment,
}: {
    value: string;
    onChange: (value: string) => void;
    onSubmit: () => void;
    placeholder: string;
    inputDisabled?: boolean;
    sendDisabled?: boolean;
    textareaRef?: React.RefObject<HTMLTextAreaElement | null>;
    /** Optional extra content on the controls row, next to the send button
     *  (e.g. the public page's Powered-by badge). */
    footerEnd?: React.ReactNode;
    /** Attachment tray items (useChatAttachments.attachments). */
    attachments?: PendingChatAttachment[];
    /** Enables the attach affordances (button / paste / drop) when present. */
    onAddFiles?: (files: File[]) => void;
    onRemoveAttachment?: (localId: string) => void;
}) {
    const localRef = useRef<HTMLTextAreaElement>(null);
    const ref = textareaRef ?? localRef;
    const fileInputRef = useRef<HTMLInputElement>(null);
    const [dragOver, setDragOver] = useState(false);
    const attachEnabled = !!onAddFiles && !inputDisabled;
    const isMobile = useIsMobile();
    const maxTextareaHeight = isMobile
        ? MAX_TEXTAREA_HEIGHT_PX_MOBILE
        : MAX_TEXTAREA_HEIGHT_PX;

    // Grow with the draft; the controls row below keeps the card from reading
    // like a search field even at one line. Recomputes when the mobile cap
    // changes so a tall desktop draft shrinks when the viewport goes mobile.
    // Hidden mounts measure NOTHING: a second agent's interface block mounts
    // display:none (tab kept alive), scrollHeight reads 0, and the pinned
    // 0px height survived the reveal as a squished composer — so measurement
    // skips while hidden and a ResizeObserver re-fires it on the 0→real flip.
    useEffect(() => {
        const el = ref.current;
        if (!el) return;
        const measure = () => {
            // display:none ancestor → offsetParent null → nothing to measure.
            if (el.offsetParent === null) return;
            el.style.height = 'auto';
            el.style.height = `${Math.min(el.scrollHeight, maxTextareaHeight)}px`;
        };
        measure();
        if (typeof ResizeObserver === 'undefined') return;
        const ro = new ResizeObserver(measure);
        ro.observe(el);
        return () => ro.disconnect();
    }, [value, ref, maxTextareaHeight]);

    return (
        <div className="shrink-0 px-3 sm:px-6 pb-5 pt-2">
            <div className="mx-auto w-full max-w-3xl">
                {/* Raised card, not sunken — --sunken is near-identical to the page
            black in dark mode, which read as a flat wireframe box. */}
                <div
                    className={cn(
                        'rounded-2xl border border-border/70 bg-card shadow-lg shadow-black/20 transition-colors focus-within:border-foreground/25',
                        dragOver && 'border-primary/60'
                    )}
                    onDragOver={
                        attachEnabled
                            ? (e) => {
                                  e.preventDefault();
                                  setDragOver(true);
                              }
                            : undefined
                    }
                    onDragLeave={
                        attachEnabled ? () => setDragOver(false) : undefined
                    }
                    onDrop={
                        attachEnabled
                            ? (e) => {
                                  e.preventDefault();
                                  setDragOver(false);
                                  if (e.dataTransfer.files.length) {
                                      onAddFiles(
                                          Array.from(e.dataTransfer.files)
                                      );
                                  }
                              }
                            : undefined
                    }
                >
                    {attachments && attachments.length > 0 ? (
                        <div
                            className="flex flex-wrap gap-2 px-3 pt-3"
                            data-testid="chat-attachment-tray"
                        >
                            {attachments.map((a) => (
                                <AttachmentTrayItem
                                    key={a.localId}
                                    attachment={a}
                                    onRemove={onRemoveAttachment}
                                />
                            ))}
                        </div>
                    ) : null}
                    <textarea
                        ref={ref}
                        value={value}
                        onChange={(e) => onChange(e.target.value)}
                        onKeyDown={(e) => {
                            if (e.key === 'Enter' && !e.shiftKey) {
                                e.preventDefault();
                                onSubmit();
                            }
                        }}
                        onPaste={
                            attachEnabled
                                ? (e) => {
                                      const files = e.clipboardData?.files;
                                      if (files?.length) {
                                          e.preventDefault();
                                          onAddFiles(Array.from(files));
                                      }
                                  }
                                : undefined
                        }
                        placeholder={placeholder}
                        rows={1}
                        className="block w-full resize-none overflow-y-auto bg-transparent px-4 pb-1 pt-3.5 text-base leading-relaxed text-foreground outline-none placeholder:text-[hsl(var(--placeholder))] scrollbar-subtle"
                        disabled={inputDisabled}
                    />
                    <div className="flex items-center justify-between gap-3 pb-2.5 pl-2.5 pr-2.5 pt-1">
                        <div className="flex min-w-0 items-center gap-2">
                            {attachEnabled ? (
                                <>
                                    <input
                                        ref={fileInputRef}
                                        type="file"
                                        multiple
                                        className="hidden"
                                        onChange={(e) => {
                                            if (e.target.files?.length) {
                                                onAddFiles(
                                                    Array.from(e.target.files)
                                                );
                                            }
                                            // Same file picked twice should
                                            // re-fire onChange.
                                            e.target.value = '';
                                        }}
                                    />
                                    <button
                                        type="button"
                                        onClick={() =>
                                            fileInputRef.current?.click()
                                        }
                                        aria-label="Attach files"
                                        title="Attach images or files"
                                        data-testid="chat-attach-button"
                                        className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-foreground/[0.07] hover:text-foreground"
                                    >
                                        <Paperclip className="h-4 w-4" />
                                    </button>
                                </>
                            ) : null}
                            {/* Keyboard hint is desktop-only — on mobile it wraps
                                and squeezes footerEnd (the share page's Powered-by
                                badge) into a broken two-line pill. */}
                            <span
                                className={cn(
                                    'hidden select-none text-[11px] text-muted-foreground/50 sm:block',
                                    !attachEnabled && 'pl-1.5'
                                )}
                            >
                                Enter to send · Shift+Enter for newline
                            </span>
                        </div>
                        <div className="ml-auto flex shrink-0 items-center gap-2.5 whitespace-nowrap">
                            {footerEnd}
                            <button
                                type="button"
                                onClick={onSubmit}
                                disabled={sendDisabled}
                                aria-label="Send"
                                className="flex h-8 w-8 items-center justify-center rounded-full bg-primary text-primary-foreground transition-all hover:bg-primary/90 disabled:cursor-not-allowed disabled:bg-foreground/[0.07] disabled:text-muted-foreground/50"
                            >
                                <ArrowUp
                                    className="h-4 w-4"
                                    strokeWidth={2.5}
                                />
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}
