import { ChevronLeft, ChevronRight } from 'lucide-react';
import { formatRelativeTime } from './utils';

type HistorySize = 'sm' | 'md';

interface HistoryEntry {
    created_at: string;
}

interface HistoryCarouselProps {
    historyEntries: HistoryEntry[];
    historyIndex: number;
    setHistoryIndex: (updater: (prev: number) => number) => void;
    /** 'sm' matches InputNodeDisplay; 'md' matches OutputPanel. */
    size: HistorySize;
}

// Newer entries are at index 0; the visible label counts down from total → 1
// so clicking left ("older") decreases the displayed number.
export function HistoryCarousel({ historyEntries, historyIndex, setHistoryIndex, size }: HistoryCarouselProps) {
    if (historyEntries.length <= 1) return null;

    const iconClass = size === 'sm' ? 'h-3.5 w-3.5' : 'h-4 w-4';
    const textClass = size === 'sm' ? 'text-[10px]' : 'text-[11px]';

    return (
        <div className="flex items-center text-muted-foreground/70 dark:text-zinc-600 -ml-1">
            <button
                onClick={() => setHistoryIndex((i) => Math.min(i + 1, historyEntries.length - 1))}
                disabled={historyIndex >= historyEntries.length - 1}
                className="p-px rounded hover:text-muted-foreground disabled:text-muted-foreground/40 dark:disabled:text-zinc-700/60 disabled:cursor-not-allowed transition-colors"
            >
                <ChevronLeft className={iconClass} />
            </button>
            <span className={`${textClass} tabular-nums select-none px-0.5`}>
                {historyEntries.length - historyIndex} of {historyEntries.length}
            </span>
            <button
                onClick={() => setHistoryIndex((i) => Math.max(i - 1, 0))}
                disabled={historyIndex === 0}
                className="p-px rounded hover:text-muted-foreground disabled:text-muted-foreground/40 dark:disabled:text-zinc-700/60 disabled:cursor-not-allowed transition-colors"
            >
                <ChevronRight className={iconClass} />
            </button>
            <span className={`${textClass} select-none text-muted-foreground/50 dark:text-zinc-700`}>
                {formatRelativeTime(historyEntries[historyIndex]?.created_at)}
            </span>
        </div>
    );
}
