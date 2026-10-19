// Media in the thread: a voice note or recording that plays in place, a video NoClick made, and the pages an answer
// drew on. Each takes the real file or link; nothing here fetches on its own.
import { useEffect, useRef, useState } from 'react';
import { AudioLines, ChevronDown, Pause, Play, Video } from 'lucide-react';
import { cn } from '~/lib/utils';
import { GlyphTile, InlineCard, PILL_QUIET } from './primitives';

/** Plays one audio file: toggle, seek (0–1), speed, how far through it is (0–1), and its length once known. With
 *  `preload`, the length is read before anything plays (only the file's header is fetched). */
export function useAudio(src: string | undefined, { preload = false }: { preload?: boolean } = {}) {
    const audio = useRef<HTMLAudioElement | null>(null);
    const [playing, setPlaying] = useState(false);
    const [progress, setProgress] = useState(0);
    const [duration, setDuration] = useState<number | undefined>();
    const [rate, setRateState] = useState(1);
    const element = () => {
        if (!audio.current && src) {
            const a = new Audio();
            a.preload = 'metadata';
            a.addEventListener('loadedmetadata', () => Number.isFinite(a.duration) && setDuration(a.duration));
            a.addEventListener('timeupdate', () => setProgress(a.duration ? a.currentTime / a.duration : 0));
            a.addEventListener('play', () => setPlaying(true));
            a.addEventListener('pause', () => setPlaying(false));
            a.addEventListener('ended', () => setProgress(0));
            a.src = src;
            audio.current = a;
        }
        return audio.current;
    };
    useEffect(() => {
        if (preload) element();
        return () => {
            audio.current?.pause();
            audio.current = null;
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps -- `element` reads the same src
    }, [src, preload]);
    const toggle = () => {
        const a = element();
        if (!a) return;
        a.playbackRate = rate;
        if (a.paused) void a.play();
        else a.pause();
    };
    const seek = (fraction: number) => {
        const a = element();
        if (!a || !Number.isFinite(a.duration)) return;
        a.currentTime = Math.min(Math.max(fraction, 0), 1) * a.duration;
        setProgress(a.currentTime / a.duration);
    };
    const setRate = (next: number) => {
        setRateState(next);
        if (audio.current) audio.current.playbackRate = next;
    };
    return { playing, progress, duration, rate, toggle, seek, setRate, playable: !!src };
}

/** Bar heights for a waveform drawn from a seed: stable for one file, different between files. */
export function waveOf(seed: string, bars = 28): number[] {
    let h = 2166136261;
    for (let i = 0; i < seed.length; i++) h = Math.imul(h ^ seed.charCodeAt(i), 16777619);
    return Array.from({ length: bars }, (_, i) => {
        h = Math.imul(h ^ (h >>> 13), 1274126177) + i;
        // Quieter at the ends, as speech is.
        const envelope = Math.sin(((i + 0.5) / bars) * Math.PI) * 0.6 + 0.4;
        return Math.round(3 + (Math.abs(h) % 15) * envelope);
    });
}

export function clock(seconds: number): string {
    const s = Math.max(0, Math.round(seconds));
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

const SPEEDS = [1, 1.5, 2];

/** A recording: a call, a voice note, generated speech. Plays in place, scrubs, and goes faster. `seconds` is its
 *  length until the file says otherwise. */
export function RecordingCard({ src, title, meta, seconds }: { src?: string; title: string; meta?: string; seconds?: number }) {
    const audio = useAudio(src, { preload: true });
    const length = audio.duration ?? seconds;
    const bars = waveOf(src ?? title, 56);
    return (
        <InlineCard
            lead={
                <GlyphTile>
                    <AudioLines className="h-4 w-4" />
                </GlyphTile>
            }
            title={title}
            meta={meta}
            display
        >
            <div className="flex items-center gap-3" data-testid="coordinator-recording">
                <button
                    type="button"
                    aria-label={audio.playing ? 'Pause' : 'Play'}
                    onClick={audio.toggle}
                    disabled={!audio.playable}
                    className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-foreground text-background transition-opacity hover:opacity-90 disabled:opacity-40"
                >
                    {audio.playing ? <Pause className="h-4 w-4" fill="currentColor" /> : <Play className="ml-0.5 h-4 w-4" fill="currentColor" />}
                </button>
                <button
                    type="button"
                    aria-label="Seek"
                    disabled={!audio.playable}
                    className="flex h-8 min-w-0 flex-1 items-center gap-[2px]"
                    onClick={(e) => {
                        const r = e.currentTarget.getBoundingClientRect();
                        audio.seek((e.clientX - r.left) / r.width);
                    }}
                >
                    {bars.map((h, i) => (
                        <span key={i} className={cn('w-full max-w-[3px] flex-1 rounded-full', i / bars.length < audio.progress ? 'bg-foreground/80' : 'bg-foreground/20')} style={{ height: `${h + 6}px` }} />
                    ))}
                </button>
                {length !== undefined && (
                    <span className="w-[76px] shrink-0 text-right text-[12.5px] tabular-nums text-muted-foreground">
                        {clock(audio.progress * length)} / {clock(length)}
                    </span>
                )}
                <button type="button" onClick={() => audio.setRate(SPEEDS[(SPEEDS.indexOf(audio.rate) + 1) % SPEEDS.length])} className={cn(PILL_QUIET, 'h-7 w-11 px-0 tabular-nums')}>
                    {audio.rate}×
                </button>
            </div>
        </InlineCard>
    );
}

/** A video NoClick made: it plays here. */
export function VideoCard({ src, poster, caption }: { src?: string; poster?: string; caption?: string }) {
    return (
        <figure className="w-full max-w-[420px]">
            <div className="relative overflow-hidden rounded-2xl bg-foreground/[0.06]">
                {/* A generated clip has no captions to offer. */}
                {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
                <video src={src} poster={poster} controls preload="metadata" playsInline className="aspect-video w-full object-cover" data-testid="coordinator-video" />
                {!src && (
                    <span className="pointer-events-none absolute bottom-2.5 right-2.5 inline-flex items-center gap-1 rounded-md bg-black/55 px-1.5 py-0.5 text-[11.5px] text-white">
                        <Video className="h-3 w-3" />
                        Preview
                    </span>
                )}
            </div>
            {caption && <figcaption className="mt-1.5 px-1 text-[12.5px] text-muted-foreground">{caption}</figcaption>}
        </figure>
    );
}

// ── Sources ──────────────────────────────────────────────────────────────────

export interface Source {
    title: string;
    url: string;
}

function siteOf(url: string): string {
    try {
        return new URL(url).hostname.replace(/^www\./, '');
    } catch {
        return url;
    }
}

/** One key per page: the scheme, a trailing slash or a fragment don't make two results different pages. */
export function sourceKey(url: string): string {
    try {
        const u = new URL(url);
        return `${u.hostname.replace(/^www\./, '')}${u.pathname.replace(/\/+$/, '')}${u.search}`.toLowerCase();
    } catch {
        return url.toLowerCase();
    }
}

/** A row's name: the page's title, else its path, since a title that only names the site repeats the line beside it. */
function titleOf(source: Source, site: string): string {
    const title = source.title.trim();
    if (title && title.toLowerCase() !== site) return title;
    try {
        const path = decodeURIComponent(new URL(source.url).pathname).replace(/^\/+|\/+$/g, '');
        return path ? path.split('/').join(' / ') : site;
    } catch {
        return site;
    }
}

/** The site's own icon, on white since a dark logo vanishes on the dark thread; its initial when none loads. */
function SiteIcon({ site, className }: { site: string; className?: string }) {
    const [missing, setMissing] = useState(false);
    if (missing) {
        return <span className={cn('grid shrink-0 place-items-center overflow-hidden bg-secondary text-[9px] font-semibold uppercase leading-none text-foreground/70 dark:bg-foreground/[0.1]', className)}>{site[0]}</span>;
    }
    return (
        <span className={cn('grid shrink-0 place-items-center overflow-hidden border border-border bg-white dark:border-transparent', className)}>
            <img src={`https://www.google.com/s2/favicons?domain=${encodeURIComponent(site)}&sz=64`} alt="" loading="lazy" onError={() => setMissing(true)} className="h-[70%] w-[70%] object-contain" />
        </span>
    );
}

/** The pages an answer drew on, folded to one line (the first sites' icons and how many) that opens the list. */
export function SourcesList({ sources, defaultOpen = false }: { sources: Source[]; defaultOpen?: boolean }) {
    const [open, setOpen] = useState(defaultOpen);
    const sites = [...new Set(sources.map((s) => siteOf(s.url)))].slice(0, 4);
    return (
        <div className="max-w-[560px]" data-testid="coordinator-sources">
            <button type="button" aria-expanded={open} onClick={() => setOpen((o) => !o)} className={cn(PILL_QUIET, '-ml-1.5 gap-2 pl-1.5 pr-2.5')}>
                <span className="flex -space-x-1.5">
                    {sites.map((site) => (
                        <SiteIcon key={site} site={site} className="h-[18px] w-[18px] rounded-full ring-2 ring-background" />
                    ))}
                </span>
                {sources.length === 1 ? '1 source' : `${sources.length} sources`}
                <ChevronDown className={cn('h-3.5 w-3.5 transition-transform', open && 'rotate-180')} />
            </button>
            {open && (
                <ul className="mt-1">
                    {sources.map((s) => {
                        const site = siteOf(s.url);
                        return (
                            <li key={s.url}>
                                <a href={s.url} target="_blank" rel="noopener noreferrer" className="group flex items-center gap-2.5 py-1.5 text-[13.5px]">
                                    <SiteIcon site={site} className="h-[18px] w-[18px] rounded-[5px]" />
                                    <span className="min-w-0 truncate text-foreground/90 group-hover:underline group-hover:decoration-foreground/30 group-hover:underline-offset-2">{titleOf(s, site)}</span>
                                    <span className="shrink-0 text-muted-foreground">{site}</span>
                                </a>
                            </li>
                        );
                    })}
                </ul>
            )}
        </div>
    );
}
