// Presentational chat composer, extracted from AgentChatBlock so the public
// shared-agent page can reuse the exact same input UI. Structured like a
// modern chat composer: optional attachment tray on top, auto-growing textarea,
// a controls row inside the same card underneath (attach + hint on the left,
// send button bottom-right). Owns only keyboard handling, height management,
// and file intake (picker / paste / drop) — validation, uploads, streaming
// guards, and dispatch stay with the caller. Attachment UI renders only when
// the caller passes `onAddFiles` (the public share page doesn't, yet).

import { useMemo, useRef, useState } from 'react';
import { ArrowUp, FileText, Loader2, Paperclip, X } from 'lucide-react';
import { UploadProgressBar } from '~/components/ui/upload-progress';
import { cn } from '~/lib/utils';
import { useIsMobile } from '~/hooks/useIsMobile';
import { useAutoGrowTextarea } from '~/hooks/useAutoGrowTextarea';
import { useSurfaceFocus } from '~/hooks/useSurfaceFocus';
import type { PendingChatAttachment } from '~/hooks/useChatAttachments';
import { MentionMenu, type MentionMenuFile } from '~/components/chat/MentionMenu';
import {
    applyMention,
    detectMentionToken,
    type MentionToken,
} from '~/utils/mentionToken';
import { fuzzyFilter } from '~/utils/fuzzySearch';

// Cap for the auto-grow: past this the textarea scrolls internally. Lower on
// mobile so the composer never dominates a small screen.
const MAX_TEXTAREA_HEIGHT_PX = 220;
const MAX_TEXTAREA_HEIGHT_PX_MOBILE = 120;

export function AttachmentTrayItem({
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
            className="absolute -right-1.5 -top-1.5 flex h-[18px] w-[18px] items-center justify-center rounded-full border border-border bg-popover text-muted-foreground opacity-0 shadow-sm transition-opacity hover:text-foreground focus-visible:opacity-100 group-hover:opacity-100 [@media(hover:none)]:opacity-100"
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

/** Send: a filled circle, greyed out while there is nothing to send. */
export function ComposerSendButton({ onClick, disabled }: { onClick: () => void; disabled?: boolean }) {
    return (
        <button
            type="button"
            onClick={onClick}
            disabled={disabled}
            aria-label="Send"
            title="Send (Enter) · new line (Shift+Enter)"
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground transition-[background-color,color,opacity] hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:bg-foreground/[0.08] disabled:text-foreground/35 disabled:hover:opacity-100"
        >
            <ArrowUp className="h-[18px] w-[18px]" strokeWidth={2.25} />
        </button>
    );
}

/** The composer's surface: a raised card in light, a hairline ring in dark. The
 *  builder's chat box wears it too, so every place you type to NoClick matches. */
export const COMPOSER_SURFACE =
    'bg-composer shadow-[0_1px_2px_rgba(0,0,0,0.04),0_10px_30px_-18px_rgba(0,0,0,0.25)] ring-1 ring-inset ring-border transition-shadow focus-within:ring-foreground/20 dark:shadow-[inset_0_1px_0_hsl(var(--foreground)/0.06)] dark:ring-foreground/[0.09] dark:focus-within:ring-foreground/[0.18]';

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
    mentionFiles,
    mentionMount,
    onMentionRefresh,
    below,
    transitionName,
    footerStart,
    addMenu,
    tray,
    cardRef,
    size = 'default',
    className,
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
    /** Workspace files for @-mention autocomplete. Absent (e.g. the public
     *  share page, which has no workspace) → `@` is inert plain text. */
    mentionFiles?: MentionMenuFile[];
    /** Sandbox mount for resolving inserted paths (default "/workspace"). */
    mentionMount?: string | null;
    /** Refresh the workspace listing — called once when `@` first opens a menu,
     *  so a chat that never mentions a file pays nothing. */
    onMentionRefresh?: () => void;
    /** Content attached under the box, inside its column (e.g. a tray of options). */
    below?: React.ReactNode;
    /** view-transition-name for the box, so a layout change can move it as one piece. */
    transitionName?: string;
    /** Content at the start of the controls row (e.g. the coordinator's phone channels). */
    footerStart?: React.ReactNode;
    /** Replaces the paperclip with a menu of ways to add things (the coordinator's "+"); paste and drop still land
     *  in the same tray through `onAddFiles`. */
    addMenu?: React.ReactNode;
    /** More chips in the attachment tray, before the files (things the message refers to). */
    tray?: React.ReactNode;
    /** The box itself, for a menu that opens against it. */
    cardRef?: React.Ref<HTMLDivElement>;
    /** `tall` opens with room for a few lines, for a page whose point is the box. */
    size?: 'default' | 'tall';
    /** The outer frame's spacing, for a host that lays the box out itself. */
    className?: string;
}) {
    const localRef = useRef<HTMLTextAreaElement>(null);
    const ref = textareaRef ?? localRef;
    const fileInputRef = useRef<HTMLInputElement>(null);
    const [dragOver, setDragOver] = useState(false);
    const attachEnabled = !!onAddFiles && !inputDisabled;
    // With nothing but Send to show, a toolbar row is dead height: Send sits
    // beside the text instead.
    const toolbar = attachEnabled || !!footerEnd || !!footerStart || !!addMenu;

    // --- @-mention state ---
    const mentionEnabled = !!mentionFiles && !inputDisabled;
    const [mention, setMention] = useState<MentionToken | null>(null);
    const [mentionIndex, setMentionIndex] = useState(0);
    // One refresh() per open token — reset when the token closes.
    const mentionRefreshedRef = useRef(false);

    const filteredMentions = useMemo(() => {
        if (!mention || !mentionFiles) return [];
        return fuzzyFilter(mentionFiles, mention.query, (f) => [
            { text: f.path.toLowerCase(), weight: 1, fuzzy: true },
        ]).slice(0, 8);
    }, [mention, mentionFiles]);
    const menuOpen = mentionEnabled && mention !== null && filteredMentions.length > 0;

    // Recompute the active token from the textarea's live value + caret.
    const syncMention = (el: HTMLTextAreaElement) => {
        if (!mentionEnabled) return;
        const tok = detectMentionToken(el.value, el.selectionStart ?? el.value.length);
        setMention((prev) => {
            if (tok && (!prev || prev.query !== tok.query)) setMentionIndex(0);
            return tok;
        });
        if (tok) {
            if (!mentionRefreshedRef.current) {
                mentionRefreshedRef.current = true;
                onMentionRefresh?.();
            }
        } else {
            mentionRefreshedRef.current = false;
        }
    };

    const closeMention = () => {
        setMention(null);
        mentionRefreshedRef.current = false;
    };

    const acceptMention = (index: number) => {
        const el = ref.current;
        const file = filteredMentions[index];
        if (!el || !mention || !file) return;
        const mount = (mentionMount || '/workspace').replace(/\/+$/, '');
        const caret = el.selectionStart ?? el.value.length;
        const next = applyMention(value, caret, mention, `${mount}/${file.path}`);
        onChange(next.value);
        closeMention();
        // Restore the caret after the controlled re-render lands the new value.
        requestAnimationFrame(() => {
            const e2 = ref.current;
            if (e2) {
                e2.focus();
                e2.setSelectionRange(next.caret, next.caret);
            }
        });
    };
    const isMobile = useIsMobile();
    const maxTextareaHeight = isMobile
        ? MAX_TEXTAREA_HEIGHT_PX_MOBILE
        : MAX_TEXTAREA_HEIGHT_PX;

    // Grow with the draft; the controls row below keeps the card from reading
    // like a search field even at one line. The cap follows the viewport, so a
    // tall desktop draft shrinks when the viewport goes mobile.
    useAutoGrowTextarea(ref, value, maxTextareaHeight);
    const focusText = useSurfaceFocus(ref);

    const sendButton = <ComposerSendButton onClick={onSubmit} disabled={sendDisabled} />;

    return (
        <div className={cn('shrink-0 px-3 sm:px-6 pb-5 pt-2', className)}>
            <div className="mx-auto w-full max-w-3xl">
                {/* Raised card, not sunken — --sunken is near-identical to the page
            black in dark mode, which read as a flat wireframe box. A press anywhere
            that isn't a control puts the caret in the text (pointer only; Tab reaches it too). */}
                {/* eslint-disable-next-line jsx-a11y/no-static-element-interactions */}
                <div
                    ref={cardRef}
                    onMouseDown={focusText}
                    className={cn(
                        'relative z-10 cursor-text rounded-[26px]',
                        COMPOSER_SURFACE,
                        dragOver && 'ring-primary/60 dark:ring-primary/60'
                    )}
                    style={transitionName ? { viewTransitionName: transitionName } : undefined}
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
                    {tray || (attachments && attachments.length > 0) ? (
                        <div
                            className="flex flex-wrap items-center gap-2 px-4 pt-4"
                            data-testid="chat-attachment-tray"
                        >
                            {tray}
                            {(attachments ?? []).map((a) => (
                                <AttachmentTrayItem
                                    key={a.localId}
                                    attachment={a}
                                    onRemove={onRemoveAttachment}
                                />
                            ))}
                        </div>
                    ) : null}
                    {menuOpen ? (
                        <MentionMenu
                            files={filteredMentions}
                            activeIndex={mentionIndex}
                            onSelect={acceptMention}
                            onHover={setMentionIndex}
                        />
                    ) : null}
                    <div className={cn(!toolbar && 'flex items-end gap-2 pr-2.5')}>
                        <textarea
                            ref={ref}
                            value={value}
                            onChange={(e) => {
                                onChange(e.target.value);
                                syncMention(e.target);
                            }}
                            onKeyDown={(e) => {
                                // The mention menu must preempt Enter-to-send, so its
                                // keys are handled here (a child listener can't
                                // reliably win the race — R6/B7).
                                if (menuOpen) {
                                    if (e.key === 'ArrowDown') {
                                        e.preventDefault();
                                        setMentionIndex((i) => (i + 1) % filteredMentions.length);
                                        return;
                                    }
                                    if (e.key === 'ArrowUp') {
                                        e.preventDefault();
                                        setMentionIndex((i) =>
                                            (i - 1 + filteredMentions.length) % filteredMentions.length,
                                        );
                                        return;
                                    }
                                    if (e.key === 'Enter' || e.key === 'Tab') {
                                        e.preventDefault();
                                        acceptMention(mentionIndex);
                                        return;
                                    }
                                    if (e.key === 'Escape') {
                                        e.preventDefault();
                                        closeMention();
                                        return;
                                    }
                                }
                                if (e.key === 'Enter' && !e.shiftKey) {
                                    e.preventDefault();
                                    onSubmit();
                                }
                            }}
                            onKeyUp={(e) => {
                                // Caret moved via arrows/click without editing text →
                                // re-evaluate the token, but don't fight the menu's own
                                // navigation keys (handled in onKeyDown).
                                if (
                                    menuOpen &&
                                    ['ArrowDown', 'ArrowUp', 'Enter', 'Tab', 'Escape'].includes(e.key)
                                ) {
                                    return;
                                }
                                syncMention(e.currentTarget);
                            }}
                            onBlur={() => closeMention()}
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
                            className={cn(
                                'block w-full resize-none overflow-y-auto bg-transparent px-5 pt-4 text-[16px] leading-6 text-foreground outline-none placeholder:text-[hsl(var(--placeholder))] scrollbar-subtle',
                                toolbar ? 'pb-1' : 'pb-4',
                                size === 'tall' && 'min-h-[68px] sm:min-h-[92px]'
                            )}
                            disabled={inputDisabled}
                        />
                        {!toolbar && <div className="shrink-0 pb-2.5">{sendButton}</div>}
                    </div>
                    {toolbar && (
                    <div className="flex items-center justify-between gap-3 px-3 pb-3 pt-1.5">
                        <div className="flex min-w-0 items-center gap-2">
                            {addMenu}
                            {footerStart}
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
                                    {!addMenu && (
                                        <button
                                            type="button"
                                            onClick={() =>
                                                fileInputRef.current?.click()
                                            }
                                            aria-label="Attach files"
                                            title="Attach images or files"
                                            data-testid="chat-attach-button"
                                            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-foreground/[0.07] hover:text-foreground"
                                        >
                                            <Paperclip className="h-4 w-4" />
                                        </button>
                                    )}
                                </>
                            ) : null}
                        </div>
                        <div className="ml-auto flex shrink-0 items-center gap-2.5 whitespace-nowrap">
                            {footerEnd}
                            {sendButton}
                        </div>
                    </div>
                    )}
                </div>
                {below}
            </div>
        </div>
    );
}
