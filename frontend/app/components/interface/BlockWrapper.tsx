// Shared wrapper component for interface blocks.
// Provides selection highlighting, a label header, consistent styling,
// and a loading overlay with progress bar during workflow execution.

import { createContext, memo, useState, useEffect, useRef } from 'react';
import { X } from 'lucide-react';
import { BrandIcon } from '~/components/shared/BrandIcon';
import { getBlockDefinition } from './blockRegistry';

// Slot for block-specific header actions. A block component can portal buttons
// into this so they appear in the BlockWrapper's title bar next to the label.
// `null` while the slot div hasn't mounted yet — consumers should guard on it.
export const BlockHeaderSlotContext = createContext<HTMLDivElement | null>(null);

const BLOCK_ICON_COLORS: Record<string, string> = {
    // Matches the form node's trigger treatment (text-foreground, white in dark)
    form: 'text-foreground',
    image: 'text-orange-600 dark:text-orange-400',
    audio: 'text-amber-600 dark:text-amber-400',
    video: 'text-pink-600 dark:text-pink-400',
    file: 'text-orange-600 dark:text-orange-400',
    dataframe: 'text-sky-600 dark:text-sky-400',
    'html-react': 'text-violet-600 dark:text-violet-400',
    'file-upload': 'text-lime-400',
};

interface BlockWrapperProps {
    blockType: string;
    label?: string;
    isSelected: boolean;
    isLoading?: boolean;
    estimatedDurationMs?: number;
    onSelect: () => void;
    onRemove?: () => void;
    children: React.ReactNode;
}

export const BlockWrapper = memo(function BlockWrapper({
    blockType,
    label,
    isSelected,
    isLoading = false,
    estimatedDurationMs,
    onSelect,
    onRemove,
    children,
}: BlockWrapperProps) {
    const def = getBlockDefinition(blockType);
    const Icon = def?.icon;
    const iconColor = BLOCK_ICON_COLORS[blockType] ?? 'text-muted-foreground';
    const displayLabel = label || def?.label || blockType;

    // Track elapsed time for progress bar
    const startTimeRef = useRef<number>(0);
    const [progress, setProgress] = useState(0);
    const [showComplete, setShowComplete] = useState(false);
    // Ref callback so block children can portal header actions into the title bar.
    const [headerSlot, setHeaderSlot] = useState<HTMLDivElement | null>(null);

    useEffect(() => {
        if (isLoading) {
            startTimeRef.current = Date.now();
            setProgress(0);
            setShowComplete(false);

            // Only tick if we have an estimate (otherwise indeterminate shimmer)
            if (!estimatedDurationMs) return;

            const interval = setInterval(() => {
                const elapsed = Date.now() - startTimeRef.current;
                setProgress(Math.min(elapsed / estimatedDurationMs, 0.95));
            }, 200);
            return () => clearInterval(interval);
        }
        // Loading just finished — flash 100% briefly
        if (startTimeRef.current > 0) {
            setProgress(1);
            setShowComplete(true);
            const timeout = setTimeout(() => {
                setShowComplete(false);
                setProgress(0);
                startTimeRef.current = 0;
            }, 300);
            return () => clearTimeout(timeout);
        }
    }, [isLoading, estimatedDurationMs]);

    const showProgressBar = isLoading || showComplete;
    const hasEstimate = isLoading && !!estimatedDurationMs;

    return (
        <div
            role="button"
            tabIndex={0}
            className={`h-full w-full flex flex-col rounded-xl overflow-hidden transition-all relative ${
                isSelected
                    ? 'ring-2 ring-foreground/40 shadow-2xl dark:shadow-black/60'
                    : 'ring-1 ring-border dark:ring-white/[0.06] shadow-xl dark:shadow-black/50 hover:ring-border dark:hover:ring-white/[0.12]'
            }`}
            style={{ background: 'hsl(var(--card))' }}
            onClick={(e) => {
                // Only select on direct click, not on drag handle or resize interactions
                if (
                    (e.target as HTMLElement).closest('.react-resizable-handle')
                )
                    return;
                onSelect();
            }}
            onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') onSelect();
            }}
        >
            {/* Progress bar */}
            {showProgressBar && (
                <div className="absolute top-0 left-0 right-0 h-[2px] bg-secondary z-10">
                    {hasEstimate ? (
                        <div
                            className="h-full bg-foreground/70 transition-[width] duration-200 ease-linear"
                            style={{ width: `${progress * 100}%` }}
                        />
                    ) : showComplete ? (
                        <div className="h-full bg-foreground/70 w-full" />
                    ) : (
                        <div className="h-full bg-foreground/70 animate-[shimmer_1.5s_ease-in-out_infinite] w-1/3" />
                    )}
                </div>
            )}

<div className="flex items-center gap-2.5 pl-3.5 pr-1 h-12 shrink-0 border-b border-border dark:border-white/[0.06] bg-gradient-to-b from-muted/80 to-card/80 cursor-grab active:cursor-grabbing">
                {Icon && <BrandIcon Icon={Icon} iconColor={iconColor} className="w-4 h-4 shrink-0" />}
                <span className="text-[13px] font-medium text-foreground truncate flex-1 tracking-wide">
                    {displayLabel}
                </span>
                <div ref={setHeaderSlot} className="flex items-center gap-1" />
                {isSelected && onRemove && (
                    <button
                        onClick={(e) => {
                            e.stopPropagation();
                            onRemove();
                        }}
                        className="p-1.5 rounded-full hover:bg-foreground/10 text-muted-foreground hover:text-foreground transition-colors"
                        title="Remove block"
                    >
                        <X className="w-4 h-4" />
                    </button>
                )}
            </div>
            <BlockHeaderSlotContext.Provider value={headerSlot}>
                <div className="block-content flex-1 min-h-0 relative overflow-hidden">
                    {isLoading ? (
                        <div className="absolute inset-0 bg-muted/40">
                            <div className="absolute inset-0 -translate-x-full bg-gradient-to-r from-transparent via-foreground/[0.06] to-transparent animate-[shimmer_1.5s_ease-in-out_infinite]" />
                        </div>
                    ) : (
                        children
                    )}
                </div>
            </BlockHeaderSlotContext.Provider>
        </div>
    );
});
