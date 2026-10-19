// Playing one audio clip: play and pause, the playhead followed every frame (timeupdate alone steps four times a
// second), and seeking. Spread `audioProps` on the clip's <audio>, which says how much of it to load, and `scrubProps`
// on what stands for its length (a track, a waveform): a press or a drag there seeks, the arrow keys step 5 seconds.
import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react';

/** 67000 ms → "1:07". */
export function clipClock(ms: number): string {
    const seconds = Math.max(0, Math.round(ms / 1000));
    return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
}

export function useClipPlayback(totalSeconds: number) {
    const audio = useRef<HTMLAudioElement>(null);
    const [playing, setPlaying] = useState(false);
    const [at, setAt] = useState(0);

    useEffect(() => {
        if (!playing) return;
        let frame = 0;
        const tick = () => {
            if (audio.current) setAt(audio.current.currentTime);
            frame = requestAnimationFrame(tick);
        };
        tick();
        return () => cancelAnimationFrame(frame);
    }, [playing]);

    const toggle = useCallback(() => {
        const el = audio.current;
        if (!el) return;
        if (el.paused) void el.play();
        else el.pause();
    }, []);
    const pause = useCallback(() => audio.current?.pause(), []);
    // A clip that hasn't loaded yet (preload="none") has nothing to seek into: the browser drops the position, so it
    // waits here while the clip's metadata loads.
    const pendingSeek = useRef<number | null>(null);
    const seekTo = useCallback(
        (seconds: number) => {
            const el = audio.current;
            if (!el) return;
            const target = Math.min(totalSeconds, Math.max(0, seconds));
            setAt(target);
            if (el.readyState >= HTMLMediaElement.HAVE_METADATA) {
                el.currentTime = target;
                return;
            }
            if (pendingSeek.current === null) {
                el.preload = 'metadata';
                el.load();
            }
            pendingSeek.current = target;
        },
        [totalSeconds]
    );

    const dragging = useRef(false);
    const seekToPointer = (e: PointerEvent<HTMLElement>) => {
        const rect = e.currentTarget.getBoundingClientRect();
        if (rect.width) seekTo(((e.clientX - rect.left) / rect.width) * totalSeconds);
    };

    return {
        playing,
        at,
        progress: totalSeconds ? Math.min(1, at / totalSeconds) : 0,
        toggle,
        pause,
        seekTo,
        scrubProps: {
            role: 'slider' as const,
            tabIndex: 0,
            'aria-valuemin': 0,
            'aria-valuemax': Math.round(totalSeconds),
            'aria-valuenow': Math.round(at),
            'aria-valuetext': clipClock(at * 1000),
            onPointerDown: (e: PointerEvent<HTMLElement>) => {
                dragging.current = true;
                e.currentTarget.setPointerCapture?.(e.pointerId);
                seekToPointer(e);
            },
            onPointerMove: (e: PointerEvent<HTMLElement>) => {
                if (dragging.current) seekToPointer(e);
            },
            onPointerUp: () => {
                dragging.current = false;
            },
            onPointerCancel: () => {
                dragging.current = false;
            },
            onKeyDown: (e: KeyboardEvent<HTMLElement>) => {
                if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
                e.preventDefault();
                seekTo(at + (e.key === 'ArrowRight' ? 5 : -5));
            },
        },
        audioProps: {
            ref: audio,
            onLoadedMetadata: () => {
                if (audio.current && pendingSeek.current !== null) audio.current.currentTime = pendingSeek.current;
                pendingSeek.current = null;
            },
            onPlay: () => setPlaying(true),
            onPause: () => setPlaying(false),
            onEnded: () => {
                setPlaying(false);
                setAt(0);
            },
        },
    };
}
