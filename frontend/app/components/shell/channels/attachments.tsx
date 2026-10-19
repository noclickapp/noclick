// Files on a message: images show, voice clips play over their own waveform,
// anything else is a card that downloads. The composer's tray draws a pending
// voice clip with the same player.
import { Download, File as FileIcon, FileArchive, FileAudio, FileSpreadsheet, FileText, FileVideo, Pause, Play } from 'lucide-react';
import { formatSize } from '~/components/resource/ResourceRenderer';
import { clipClock, useClipPlayback } from '~/hooks/useClipPlayback';
import { cn } from '~/lib/utils';
import type { ChannelAttachment } from './types';

export { clipClock };

export function VoicePlayer({ url, durationMs, peaks, className }: { url?: string; durationMs: number; peaks: number[]; className?: string }) {
    const total = durationMs / 1000;
    const { playing, at, progress, toggle, scrubProps, audioProps } = useClipPlayback(total);

    return (
        <div className={cn('inline-flex max-w-full items-center gap-3 rounded-full bg-foreground/[0.04] py-1.5 pl-1.5 pr-4 ring-1 ring-inset ring-foreground/[0.07]', className)}>
            <button
                type="button"
                onClick={toggle}
                disabled={!url}
                aria-label={playing ? 'Pause' : 'Play voice clip'}
                className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-foreground text-background transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:opacity-40"
            >
                {playing ? <Pause className="h-3.5 w-3.5 fill-current" /> : <Play className="h-3.5 w-3.5 translate-x-px fill-current" />}
            </button>
            <div
                {...scrubProps}
                tabIndex={url ? 0 : -1}
                aria-label="Position in the clip"
                className="flex h-8 min-w-0 cursor-pointer touch-pan-y items-center gap-[2px] rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
                {peaks.map((peak, i) => (
                    <span
                        key={i}
                        className={cn('w-[3px] shrink-0 rounded-full transition-colors duration-100', (i + 0.5) / peaks.length <= progress ? 'bg-foreground' : 'bg-foreground/25')}
                        style={{ height: `${Math.round(4 + peak * 20)}px` }}
                    />
                ))}
            </div>
            <span className="shrink-0 text-[12.5px] tabular-nums text-muted-foreground">{clipClock((at > 0 ? total - at : total) * 1000)}</span>
            {url && (
                // A voice clip has no captions to offer.
                // eslint-disable-next-line jsx-a11y/media-has-caption
                <audio {...audioProps} src={url} preload="metadata" />
            )}
        </div>
    );
}

function fileIcon(mimeType: string) {
    if (mimeType.startsWith('audio/')) return FileAudio;
    if (mimeType.startsWith('video/')) return FileVideo;
    if (/zip|tar|gzip|compressed/.test(mimeType)) return FileArchive;
    if (/sheet|excel|csv/.test(mimeType)) return FileSpreadsheet;
    if (/pdf|text|document|word|markdown|json/.test(mimeType)) return FileText;
    return FileIcon;
}

function FileCard({ file }: { file: ChannelAttachment }) {
    const Icon = fileIcon(file.mimeType);
    const ext = file.name.includes('.') ? file.name.slice(file.name.lastIndexOf('.') + 1).toUpperCase() : 'File';
    const body = (
        <>
            <span className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-foreground/[0.06]">
                <Icon className="h-5 w-5 text-foreground/70" strokeWidth={1.6} />
            </span>
            <span className="min-w-0 flex-1">
                <span className="block truncate text-[14px] font-medium text-foreground">{file.name}</span>
                <span className="block text-[12.5px] text-muted-foreground">
                    {ext} · {formatSize(file.sizeBytes)}
                </span>
            </span>
            {file.url && <Download className="h-4 w-4 shrink-0 text-muted-foreground transition-colors group-hover/file:text-foreground" />}
        </>
    );
    const frame = 'flex w-full max-w-sm items-center gap-3 rounded-xl bg-foreground/[0.02] p-2.5 pr-3.5 ring-1 ring-inset ring-foreground/[0.08]';
    return file.url ? (
        <a href={file.url} download={file.name} className={cn(frame, 'group/file transition-colors hover:bg-foreground/[0.045]')}>
            {body}
        </a>
    ) : (
        <div className={frame}>{body}</div>
    );
}

/** An audio file sent without a recorded waveform plays over an even one. */
const FLAT_PEAKS = Array.from({ length: 32 }, () => 0.35);

export function MessageAttachments({ attachments }: { attachments: ChannelAttachment[] }) {
    const images = attachments.filter((a) => a.kind === 'image' && a.url);
    const rest = attachments.filter((a) => !images.includes(a));
    return (
        <div className="mt-2 flex flex-col items-start gap-2">
            {images.length > 0 && (
                <div className="flex flex-wrap gap-2">
                    {images.map((image) => (
                        <a
                            key={image.id}
                            href={image.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-block max-w-full overflow-hidden rounded-xl ring-1 ring-foreground/[0.08] transition-opacity hover:opacity-95"
                        >
                            <img
                                src={image.url}
                                alt={image.name}
                                loading="lazy"
                                className={cn('block object-cover', images.length > 1 ? 'h-40 w-auto max-w-[240px]' : 'h-auto max-h-80 w-auto max-w-full')}
                            />
                        </a>
                    ))}
                </div>
            )}
            {rest.map((file) =>
                file.kind === 'audio' && file.durationMs !== undefined ? (
                    <VoicePlayer key={file.id} url={file.url} durationMs={file.durationMs} peaks={file.peaks?.length ? file.peaks : FLAT_PEAKS} />
                ) : (
                    <FileCard key={file.id} file={file} />
                )
            )}
        </div>
    );
}
