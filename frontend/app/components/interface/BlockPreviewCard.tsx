// Shared preview card for UX blocks. Used in both the FlowHelperView palette
// and as the drag overlay when dragging interface nodes onto the canvas.

import { scaled } from '~/lib/constants';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
import { BrandIcon } from '~/components/shared/BrandIcon';

interface BlockPreviewCardProps {
    blockType: string;
    label: string;
    Icon: NodeDefinition['Icon'];
}

// Sized to scale with the active root-font-size tier.
const BASE_CARD_WIDTH = 190;
const BASE_SKELETON_H = 28;

/** Miniature skeleton that visually represents each block type.
 *  Every case must render content that looks correct inside a 28px-tall zone. */
function Skeleton({ blockType }: { blockType: string }) {
    switch (blockType) {
        case 'form':
            return (
                <div className="flex flex-col gap-1">
                    <div className="h-[10px] rounded bg-foreground/10 border border-border/50 dark:border-zinc-700/50" />
                    <div className="h-[10px] rounded bg-foreground/10 border border-border/50 dark:border-zinc-700/50" />
                </div>
            );
        case 'markdown':
            return (
                <div className="flex flex-col justify-center gap-1">
                    <div className="h-[3px] w-[55%] rounded-full bg-muted-foreground/40 dark:bg-zinc-600/50" />
                    <div className="h-[2.5px] w-full rounded-full bg-secondary dark:bg-zinc-700/35" />
                    <div className="h-[2.5px] w-[80%] rounded-full bg-secondary dark:bg-zinc-700/35" />
                    <div className="h-[2.5px] w-[40%] rounded-full bg-secondary dark:bg-zinc-700/35" />
                </div>
            );
        case 'file':
            return (
                <div className="h-full rounded bg-foreground/10 border border-border/35 dark:border-zinc-700/35 flex items-center justify-center">
                    <div className="w-[10px] h-[12px] rounded-[1px] bg-secondary dark:bg-zinc-700/40 border border-muted-foreground/30 dark:border-zinc-600/30" />
                </div>
            );
        case 'dataframe':
            return (
                <div className="rounded overflow-hidden border border-border/35 dark:border-zinc-700/35">
                    <div className="flex gap-px bg-secondary dark:bg-zinc-700/15">
                        <div className="flex-1 h-[10px] bg-secondary dark:bg-zinc-700/25" />
                        <div className="flex-1 h-[10px] bg-secondary dark:bg-zinc-700/25" />
                        <div className="flex-1 h-[10px] bg-secondary dark:bg-zinc-700/25" />
                    </div>
                    <div className="flex gap-px">
                        <div className="flex-1 h-[10px] bg-foreground/10" />
                        <div className="flex-1 h-[10px] bg-foreground/10" />
                        <div className="flex-1 h-[10px] bg-foreground/10" />
                    </div>
                </div>
            );
        case 'plot':
            return (
                <div className="h-full flex items-end gap-[2px] px-[2px]">
                    {[40, 65, 30, 85, 50, 70].map((h, i) => (
                        <div
                            key={i}
                            className="flex-1 rounded-t-[2px] bg-blue-500/20"
                            style={{ height: `${h}%` }}
                        />
                    ))}
                </div>
            );
        case 'html':
            return (
                <div className="flex flex-col justify-center gap-1 px-1.5 py-1 rounded bg-foreground/10 border border-border/35 dark:border-zinc-700/35">
                    <div className="h-[2.5px] w-[30%] rounded-full bg-orange-500/20" />
                    <div className="h-[2.5px] w-[70%] rounded-full bg-muted-foreground/40 dark:bg-zinc-600/25" />
                    <div className="h-[2.5px] w-[50%] rounded-full bg-muted-foreground/40 dark:bg-zinc-600/20" />
                </div>
            );
        case 'fileUpload':
            return (
                <div className="h-full rounded border border-dashed border-border/40 dark:border-zinc-700/40 bg-foreground/10 flex items-center justify-center">
                    <span className="text-[7px] text-muted-foreground/70 dark:text-zinc-600">
                        Drop file here
                    </span>
                </div>
            );
        default:
            return (
                <div className="h-[18px] rounded bg-foreground/10 border border-border/35 dark:border-zinc-700/35" />
            );
    }
}

/** Self-contained preview card used in the palette and as the drag overlay */
export function BlockPreviewCard({
    blockType,
    label,
    Icon,
}: BlockPreviewCardProps) {
    const skeletonH = scaled(BASE_SKELETON_H);
    return (
        <div
            className="rounded-lg border border-border dark:border-white/[0.07] overflow-hidden bg-card dark:bg-[linear-gradient(145deg,rgba(39,39,42,0.6),rgba(24,24,27,0.75))]"
            style={{ width: scaled(BASE_CARD_WIDTH) }}
        >
            <div className="flex items-center gap-1.5 px-2.5 py-2 border-b border-border/60 dark:border-white/[0.04]">
                <BrandIcon
                    Icon={Icon}
                    className="w-3 h-3 text-muted-foreground flex-shrink-0"
                />
                <span className="text-[10px] font-medium text-foreground/80 leading-none truncate">
                    {label}
                </span>
            </div>
            <div
                className="px-2.5 pointer-events-none"
                style={{
                    height: skeletonH + scaled(16),
                    display: 'flex',
                    alignItems: 'center',
                }}
            >
                <div className="w-full" style={{ height: skeletonH }}>
                    <Skeleton blockType={blockType} />
                </div>
            </div>
        </div>
    );
}

// Rendered width (with the low-res scale baked in), for callers aligning
// an overlay or layout slot to the card width — e.g. the drag overlay.
export function getBlockPreviewWidth(): number {
    return scaled(BASE_CARD_WIDTH);
}
