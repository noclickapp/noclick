// A voice clip, recorded in the browser: the microphone through a
// MediaRecorder, a running clock, and the loudness as it goes (a live meter
// while recording, the clip's waveform after). `stop` hands back the audio as
// a File; `cancel` throws it away. Leaving the page mid-clip releases the mic.
import { useCallback, useEffect, useRef, useState } from 'react';

/** How many recent levels the live meter keeps: enough to fill a laptop-wide strip. */
const LIVE_LEVELS = 120;
/** How many bars a finished clip's waveform has. */
export const CLIP_PEAKS = 40;
const SAMPLE_MS = 80;
const MAX_MS = 5 * 60 * 1000;
const TYPES = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus'];

export interface VoiceClip {
    file: File;
    durationMs: number;
    /** Loudness over the clip, 0–1, CLIP_PEAKS long. */
    peaks: number[];
}

interface Session {
    recorder: MediaRecorder;
    stream: MediaStream;
    context: AudioContext;
    timer: number;
    chunks: Blob[];
    levels: number[];
    startedAt: number;
}

/** The loudest level in each of `count` equal stretches, scaled so the loudest bar is full height. */
export function peaksFrom(levels: number[], count: number = CLIP_PEAKS): number[] {
    if (!levels.length) return Array.from({ length: count }, () => 0.1);
    const peaks = Array.from({ length: count }, (_, i) => {
        const from = Math.floor((i * levels.length) / count);
        const to = Math.max(from + 1, Math.floor(((i + 1) * levels.length) / count));
        return Math.max(...levels.slice(from, to));
    });
    const loudest = Math.max(...peaks) || 1;
    return peaks.map((p) => Math.max(0.1, p / loudest));
}

function micError(error: unknown): string {
    const name = error instanceof DOMException ? error.name : '';
    if (name === 'NotAllowedError' || name === 'SecurityError') return 'Microphone access is blocked. Allow it in your browser to record a clip.';
    if (name === 'NotFoundError') return 'No microphone found.';
    return 'Couldn’t start recording.';
}

function release(session: Session) {
    window.clearInterval(session.timer);
    session.stream.getTracks().forEach((track) => track.stop());
    void session.context.close();
}

export function useVoiceClip({ onError }: { onError: (message: string) => void }) {
    const [state, setState] = useState<'idle' | 'starting' | 'recording'>('idle');
    const [elapsedMs, setElapsedMs] = useState(0);
    const [levels, setLevels] = useState<number[]>([]);
    const session = useRef<Session | null>(null);

    const reset = useCallback(() => {
        session.current = null;
        setState('idle');
        setElapsedMs(0);
        setLevels([]);
    }, []);

    const stop = useCallback(
        () =>
            new Promise<VoiceClip | null>((resolve) => {
                const current = session.current;
                if (!current) return resolve(null);
                const durationMs = performance.now() - current.startedAt;
                current.recorder.onstop = () => {
                    const type = (current.recorder.mimeType || 'audio/webm').split(';')[0];
                    const ext = type.split('/')[1] === 'mp4' ? 'm4a' : type.split('/')[1];
                    release(current);
                    reset();
                    resolve({ file: new File(current.chunks, `Voice clip.${ext}`, { type }), durationMs, peaks: peaksFrom(current.levels) });
                };
                current.recorder.stop();
            }),
        [reset]
    );

    const cancel = useCallback(() => {
        const current = session.current;
        if (!current) return;
        current.recorder.onstop = null;
        if (current.recorder.state !== 'inactive') current.recorder.stop();
        release(current);
        reset();
    }, [reset]);

    const start = useCallback(async () => {
        if (session.current || state !== 'idle') return;
        if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
            onError('This browser can’t record audio.');
            return;
        }
        setState('starting');
        let stream: MediaStream;
        try {
            stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        } catch (error) {
            setState('idle');
            onError(micError(error));
            return;
        }
        const mimeType = TYPES.find((type) => MediaRecorder.isTypeSupported(type));
        const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
        const context = new AudioContext();
        const analyser = context.createAnalyser();
        analyser.fftSize = 1024;
        context.createMediaStreamSource(stream).connect(analyser);
        const samples = new Uint8Array(analyser.fftSize);
        const chunks: Blob[] = [];
        const clipLevels: number[] = [];
        recorder.ondataavailable = (e) => {
            if (e.data.size) chunks.push(e.data);
        };
        recorder.start(250);
        const startedAt = performance.now();
        const timer = window.setInterval(() => {
            analyser.getByteTimeDomainData(samples);
            let sum = 0;
            for (const sample of samples) sum += ((sample - 128) / 128) ** 2;
            // Speech sits low on the raw RMS scale; lift it so a normal voice fills the meter.
            const level = Math.min(1, Math.sqrt(sum / samples.length) * 4);
            clipLevels.push(level);
            setLevels((prev) => [...prev.slice(1 - LIVE_LEVELS), level]);
            const elapsed = performance.now() - startedAt;
            setElapsedMs(elapsed);
            if (elapsed >= MAX_MS) void stop();
        }, SAMPLE_MS);
        session.current = { recorder, stream, context, timer, chunks, levels: clipLevels, startedAt };
        setState('recording');
    }, [onError, state, stop]);

    useEffect(
        () => () => {
            const current = session.current;
            if (!current) return;
            current.recorder.onstop = null;
            if (current.recorder.state !== 'inactive') current.recorder.stop();
            release(current);
        },
        []
    );

    return { state, elapsedMs, levels, start, stop, cancel };
}
