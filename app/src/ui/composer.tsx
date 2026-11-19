// The parts every chat box shares: a file in its tray while it uploads, its round button (Send, Steer, Queue or Stop,
// as `composerPrimary` decides), and its surface. The boxes themselves (a chat's, a channel's) are built from these.
import { ArrowUp, CornerUpRight, FileText, ListPlus, Loader2, X } from 'lucide-react';
import { ShortcutTooltip } from '@/ui/ShortcutTooltip';
import { UploadProgressBar } from '@/ui/upload-progress';
import { cn } from '@/ui/utils';
import { TAP_AREA } from '@/ui/buttons';
import type { PrimaryKind } from './composerPrimary';

/** A file in a box's tray, while it uploads and after: what the tray draws of it. */
export interface TrayAttachment {
    localId: string;
    name: string;
    mimeType: string;
    sizeBytes: number;
    /** Object URL for the local image thumbnail while uploading (and after —
     *  the tray keeps showing the local pixels rather than fetching the upload again). */
    previewUrl?: string;
    status: 'uploading' | 'ready' | 'error';
    /** Byte fraction 0..1 of the in-flight upload (only while status === 'uploading'). */
    progress?: number;
    error?: string;
}

export function AttachmentTrayItem({
    attachment,
    onRemove,
}: {
    attachment: TrayAttachment;
    onRemove?: (localId: string) => void;
}) {
    const removeButton = onRemove ? (
        <ShortcutTooltip label="Remove" side="top">
            <button
                type="button"
                onClick={() => onRemove(attachment.localId)}
                aria-label={`Remove ${attachment.name}`}
                className={cn(
                    'absolute -right-1.5 -top-1.5 flex h-[18px] w-[18px] items-center justify-center rounded-full border border-border bg-popover text-muted-foreground opacity-0 shadow-sm transition-opacity hover:text-foreground focus-visible:opacity-100 group-hover:opacity-100 [@media(hover:none)]:opacity-100',
                    TAP_AREA
                )}
            >
                <X className="h-3 w-3" strokeWidth={2.5} />
            </button>
        </ShortcutTooltip>
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

const PRIMARY_LOOK: Record<Exclude<PrimaryKind, 'submit'>, { label: string; tip: string }> = {
    send: { label: 'Send', tip: 'Send' },
    steer: { label: 'Steer', tip: 'Joins what it’s doing now' },
    queue: { label: 'Queue', tip: 'Goes once this turn ends' },
    stop: { label: 'Stop', tip: 'Stop' },
};

const PRIMARY_SIZE = { md: { box: 'h-9 w-9', icon: 'h-[18px] w-[18px]', square: 'h-3 w-3' }, sm: { box: 'h-8 w-8', icon: 'h-4 w-4', square: 'h-2.5 w-2.5' } };

/** The box's round button, the same circle in every box (`composerPrimary` says which): Send, Steer (joins the turn
 *  at work), Queue (goes once it ends) or, with nothing typed while the agent works, Stop, a filled square. Primary
 *  ink on primary-foreground, so it inverts with the theme; never red, which is kept for failures. Greyed out while it
 *  can't act. */
export function ComposerPrimaryButton({
    kind,
    disabled,
    busy,
    onClick,
    size = 'md',
}: {
    kind: Exclude<PrimaryKind, 'submit'>;
    disabled?: boolean;
    busy?: boolean;
    onClick: (e: { metaKey: boolean; ctrlKey: boolean }) => void;
    size?: 'md' | 'sm';
}) {
    const look = PRIMARY_LOOK[kind];
    const sized = PRIMARY_SIZE[size];
    return (
        <ShortcutTooltip label={look.tip}>
            <button
                type="button"
                onClick={onClick}
                disabled={disabled}
                aria-label={look.label}
                data-primary={kind}
                className={cn(
                    'relative grid shrink-0 place-items-center rounded-full bg-primary text-primary-foreground transition-[background-color,color,opacity,transform] duration-150 hover:opacity-90 active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:bg-foreground/[0.08] disabled:text-foreground/35 disabled:hover:opacity-100 disabled:active:scale-100',
                    sized.box,
                    TAP_AREA
                )}
            >
                <span key={kind} className="grid place-items-center duration-150 animate-in zoom-in-75 motion-reduce:animate-none">
                    {busy ? (
                        <Loader2 className={cn(sized.icon, 'animate-spin')} strokeWidth={2} />
                    ) : kind === 'stop' ? (
                        <span data-stop-square className={cn('block rounded-[2px] bg-current', sized.square)} />
                    ) : kind === 'steer' ? (
                        <CornerUpRight className={sized.icon} strokeWidth={2.25} />
                    ) : kind === 'queue' ? (
                        <ListPlus className={sized.icon} strokeWidth={2.25} />
                    ) : (
                        <ArrowUp className={sized.icon} strokeWidth={2.25} />
                    )}
                </span>
            </button>
        </ShortcutTooltip>
    );
}

/** Send: the round button, greyed out while there is nothing to send. */
export function ComposerSendButton({ onClick, disabled }: { onClick: () => void; disabled?: boolean }) {
    return <ComposerPrimaryButton kind="send" onClick={onClick} disabled={disabled} />;
}

/** The composer's surface: a raised card in light, a hairline ring in dark. The
 *  builder's chat box wears it too, so every place you type to NoClick matches. */
export const COMPOSER_SURFACE =
    'bg-composer shadow-[0_1px_2px_rgba(0,0,0,0.04),0_10px_30px_-18px_rgba(0,0,0,0.25)] ring-1 ring-inset ring-border transition-shadow focus-within:ring-foreground/20 dark:shadow-[inset_0_1px_0_hsl(var(--foreground)/0.06)] dark:ring-foreground/[0.09] dark:focus-within:ring-foreground/[0.18]';
