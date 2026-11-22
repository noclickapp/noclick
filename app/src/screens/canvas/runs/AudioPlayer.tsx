// AudioPlayer component for playing base64-encoded audio inline.
// Used in workflow node outputs to preview generated audio (e.g., from ElevenLabs TTS).
// Converts base64 audio to blob and plays it with a simple play/pause control.
// Improved with proper state synchronization and multi-player coordination.

import { useState, useRef, useEffect, useCallback } from 'react';
import { Play, Pause, Volume2, AlertCircle, Loader2 } from 'lucide-react';

interface AudioPlayerProps {
    audioBase64: string;
    contentType?: string; // e.g., "audio/mpeg", defaults to "audio/mpeg"
    className?: string;
}

// Global set to track all active audio players and pause others when one plays
const activeAudioPlayers = new Set<HTMLAudioElement>();

export const AudioPlayer = ({ audioBase64, contentType = 'audio/mpeg', className = '' }: AudioPlayerProps) => {
    const [isPlaying, setIsPlaying] = useState(false);
    const [currentTime, setCurrentTime] = useState(0);
    const [duration, setDuration] = useState(0);
    const [isLoading, setIsLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const audioRef = useRef<HTMLAudioElement | null>(null);
    const [audioUrl, setAudioUrl] = useState<string | null>(null);

    // Convert base64 to blob URL on mount
    useEffect(() => {
        setIsLoading(true);
        setError(null);

        try {
            // Decode base64 to binary
            const binaryString = atob(audioBase64);
            const bytes = new Uint8Array(binaryString.length);
            for (let i = 0; i < binaryString.length; i++) {
                bytes[i] = binaryString.charCodeAt(i);
            }
            const blob = new Blob([bytes], { type: contentType });
            const url = URL.createObjectURL(blob);
            setAudioUrl(url);
            setIsLoading(false);

            return () => {
                // Cleanup: revoke object URL when component unmounts
                URL.revokeObjectURL(url);
            };
        } catch (err) {
            console.error('[AudioPlayer] Failed to decode base64 audio:', err);
            setError('Failed to decode audio');
            setIsLoading(false);
        }
    }, [audioBase64, contentType]);

    // Set up audio element event listeners - use audio element state as source of truth
    useEffect(() => {
        const audio = audioRef.current;
        if (!audio || !audioUrl) return;

        // Track this audio element
        activeAudioPlayers.add(audio);

        const updateTime = () => setCurrentTime(audio.currentTime);
        const updateDuration = () => {
            if (isFinite(audio.duration)) {
                setDuration(audio.duration);
            }
        };

        // Sync state with actual audio element state
        const handlePlay = () => {
            setIsPlaying(true);
            // Pause all other audio players
            activeAudioPlayers.forEach(otherAudio => {
                if (otherAudio !== audio && !otherAudio.paused) {
                    otherAudio.pause();
                }
            });
        };

        const handlePause = () => setIsPlaying(false);
        const handleEnded = () => {
            setIsPlaying(false);
            setCurrentTime(0);
        };

        const handleError = (e: Event) => {
            console.error('[AudioPlayer] Audio error:', e);
            setError('Failed to load audio');
            setIsPlaying(false);
        };

        const handleCanPlay = () => {
            setError(null);
        };

        audio.addEventListener('timeupdate', updateTime);
        audio.addEventListener('loadedmetadata', updateDuration);
        audio.addEventListener('durationchange', updateDuration);
        audio.addEventListener('play', handlePlay);
        audio.addEventListener('pause', handlePause);
        audio.addEventListener('ended', handleEnded);
        audio.addEventListener('error', handleError);
        audio.addEventListener('canplay', handleCanPlay);

        return () => {
            activeAudioPlayers.delete(audio);
            audio.removeEventListener('timeupdate', updateTime);
            audio.removeEventListener('loadedmetadata', updateDuration);
            audio.removeEventListener('durationchange', updateDuration);
            audio.removeEventListener('play', handlePlay);
            audio.removeEventListener('pause', handlePause);
            audio.removeEventListener('ended', handleEnded);
            audio.removeEventListener('error', handleError);
            audio.removeEventListener('canplay', handleCanPlay);
        };
    }, [audioUrl]);

    const togglePlayPause = useCallback(async () => {
        const audio = audioRef.current;
        if (!audio) return;

        try {
            if (audio.paused) {
                await audio.play();
                // State will be updated by 'play' event listener
            } else {
                audio.pause();
                // State will be updated by 'pause' event listener
            }
        } catch (err) {
            console.error('[AudioPlayer] Play/pause failed:', err);
            setError('Failed to play audio');
            setIsPlaying(false);
        }
    }, []);

    const handleSeek = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
        const audio = audioRef.current;
        if (!audio) return;

        const newTime = parseFloat(e.target.value);
        audio.currentTime = newTime;
        setCurrentTime(newTime);
    }, []);

    const formatTime = (seconds: number) => {
        if (!isFinite(seconds) || seconds < 0) return '0:00';
        const mins = Math.floor(seconds / 60);
        const secs = Math.floor(seconds % 60);
        return `${mins}:${secs.toString().padStart(2, '0')}`;
    };

    if (error) {
        return (
            <div className={`inline-flex items-center gap-1.5 px-2 py-1 rounded bg-red-500/10 border border-red-500/20 ${className}`}>
                <AlertCircle className="w-3.5 h-3.5 text-red-600 dark:text-red-400 flex-shrink-0" />
                <span className="text-xs text-red-600 dark:text-red-400">{error}</span>
            </div>
        );
    }

    if (isLoading || !audioUrl) {
        return (
            <div className={`inline-flex items-center gap-1.5 px-2 py-1 rounded bg-muted/50 border border-border/50 dark:border-zinc-700/50 ${className}`}>
                <Loader2 className="w-3.5 h-3.5 text-muted-foreground flex-shrink-0 animate-spin" />
                <span className="text-xs text-muted-foreground">Loading audio...</span>
            </div>
        );
    }

    const progressPercent = duration > 0 ? (currentTime / duration) * 100 : 0;

    return (
        <div className={`inline-flex items-center gap-2 px-2 py-1.5 rounded bg-muted/50 border border-border/50 dark:border-zinc-700/50 hover:border-muted-foreground/40 dark:hover:border-zinc-600/50 transition-colors ${className}`}>
            {/* Hidden audio element */}
            <audio ref={audioRef} src={audioUrl} preload="metadata" />

            {/* Play/Pause button */}
            <button
                onClick={togglePlayPause}
                disabled={!audioUrl}
                className="flex-shrink-0 w-7 h-7 flex items-center justify-center rounded-md bg-emerald-500/15 hover:bg-emerald-500/25 border border-emerald-500/30 hover:border-emerald-500/50 transition-all disabled:opacity-50 disabled:cursor-not-allowed active:scale-95"
                title={isPlaying ? 'Pause' : 'Play'}
                aria-label={isPlaying ? 'Pause' : 'Play'}
            >
                {isPlaying ? (
                    <Pause className="w-3.5 h-3.5 text-emerald-700 dark:text-emerald-300" fill="currentColor" />
                ) : (
                    <Play className="w-3.5 h-3.5 text-emerald-700 dark:text-emerald-300" fill="currentColor" style={{ marginLeft: '1px' }} />
                )}
            </button>

            {/* Progress bar and time display */}
            <div className="flex items-center gap-2 min-w-[140px] max-w-[200px] flex-1">
                <div className="flex-1 relative group">
                    <input
                        type="range"
                        min="0"
                        max={duration || 0}
                        step="0.01"
                        value={currentTime}
                        onChange={handleSeek}
                        disabled={!audioUrl || duration === 0}
                        className="w-full h-1.5 bg-transparent rounded-full appearance-none cursor-pointer disabled:cursor-not-allowed relative z-10
                            [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3
                            [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-emerald-400 [&::-webkit-slider-thumb]:cursor-pointer
                            [&::-webkit-slider-thumb]:shadow-md [&::-webkit-slider-thumb]:border-2 [&::-webkit-slider-thumb]:border-zinc-900
                            [&::-webkit-slider-thumb]:transition-transform [&::-webkit-slider-thumb]:hover:scale-110
                            [&::-moz-range-thumb]:w-3 [&::-moz-range-thumb]:h-3 [&::-moz-range-thumb]:rounded-full
                            [&::-moz-range-thumb]:bg-emerald-400 [&::-moz-range-thumb]:border-2 [&::-moz-range-thumb]:border-zinc-900
                            [&::-moz-range-thumb]:cursor-pointer [&::-moz-range-thumb]:shadow-md"
                        title={`${formatTime(currentTime)} / ${formatTime(duration)}`}
                    />
                    {/* Custom track background */}
                    <div className="absolute top-1/2 left-0 right-0 h-1.5 -translate-y-1/4 bg-foreground/20 rounded-full overflow-hidden pointer-events-none">
                        <div
                            className="h-full bg-gradient-to-r from-emerald-500/60 to-emerald-400/60 transition-all duration-100"
                            style={{ width: `${progressPercent}%` }}
                        />
                    </div>
                </div>

                <span className="text-[10px] text-muted-foreground font-mono flex-shrink-0 min-w-[45px] tabular-nums">
                    {formatTime(currentTime)}<span className="text-muted-foreground/70 dark:text-zinc-600">/</span>{formatTime(duration)}
                </span>
            </div>

            {/* Volume indicator */}
            <Volume2 className="w-3 h-3 text-muted-foreground/70 dark:text-zinc-600 flex-shrink-0" />
        </div>
    );
};
