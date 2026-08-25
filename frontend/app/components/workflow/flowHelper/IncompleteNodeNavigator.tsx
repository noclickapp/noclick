import { AlertCircle, Check, ChevronLeft, ChevronRight } from 'lucide-react';

interface IncompleteNodeNavigatorProps {
    count: number;
    currentIndex: number;
    onPrev: () => void;
    onNext: () => void;
}

// Header badge shown in full-screen mode: either an amber "N of M" navigator
// for the misconfigured nodes, or a green "all configured" confirmation.
export function IncompleteNodeNavigator({
    count,
    currentIndex,
    onPrev,
    onNext,
}: IncompleteNodeNavigatorProps) {
    if (count === 0) {
        return (
            <div className="flex items-center gap-1.5 px-3 py-2 rounded-full border border-green-500/40 bg-green-500/15">
                <Check className="w-4 h-4 text-green-600 dark:text-green-400" />
                <span className="text-xs font-medium text-green-700 dark:text-green-300">All nodes configured</span>
            </div>
        );
    }

    return (
        <div className="flex items-center gap-1 px-2 py-1.5 rounded-full border border-amber-500/40 bg-amber-500/15">
            <button
                onClick={onPrev}
                className="p-1 rounded-full hover:bg-amber-500/20 transition-colors text-amber-600 hover:text-amber-700 dark:text-amber-400 dark:hover:text-amber-300"
                title="Previous incomplete node"
            >
                <ChevronLeft className="w-4 h-4" />
            </button>
            <div className="flex items-center gap-1.5 px-2">
                <AlertCircle className="w-4 h-4 text-amber-600 dark:text-amber-400" />
                <span className="text-xs font-semibold text-amber-700 dark:text-amber-300 tabular-nums">
                    {currentIndex + 1} / {count}
                </span>
            </div>
            <button
                onClick={onNext}
                className="p-1 rounded-full hover:bg-amber-500/20 transition-colors text-amber-600 hover:text-amber-700 dark:text-amber-400 dark:hover:text-amber-300"
                title="Next incomplete node"
            >
                <ChevronRight className="w-4 h-4" />
            </button>
        </div>
    );
}
