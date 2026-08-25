// Browser-style title bar shared by every interface (UI) block on the canvas:
// brand icon + label flush-left, an optional portal slot for block-injected actions,
// and a trailing action area (the Publish button). Extracted from InterfaceNode so the
// desktop (xyflow) canvas and the mobile ForkCanvas InterfaceCard render an identical
// header — the desktop style refresh can't drift away from mobile again.

import type { CSSProperties, ReactNode } from 'react';
import { BrandIcon } from '~/components/shared/BrandIcon';

interface InterfaceBlockHeaderProps {
    Icon?: React.ComponentType<{ className?: string; style?: CSSProperties }>;
    iconColor?: string;
    label: string;
    /** Ref for the block-actions portal slot (desktop only — block children portal
     *  header actions here). Omit on read-only surfaces that don't inject actions. */
    headerSlotRef?: (el: HTMLDivElement | null) => void;
    /** Trailing action(s), e.g. <InterfaceNodePublishButton/>. */
    trailing?: ReactNode;
}

export function InterfaceBlockHeader({ Icon, iconColor, label, headerSlotRef, trailing }: InterfaceBlockHeaderProps) {
    return (
        <div className="flex items-center gap-2.5 pl-3.5 pr-1 h-12 shrink-0 border-b border-border dark:border-white/[0.06] bg-gradient-to-b from-muted/80 to-card/80">
            {Icon && <BrandIcon Icon={Icon} iconColor={iconColor || 'text-muted-foreground'} className="w-4 h-4 shrink-0" />}
            <span className="text-[13px] font-medium text-foreground truncate flex-1 tracking-wide">{label}</span>
            {headerSlotRef && <div ref={headerSlotRef} className="nodrag flex items-center gap-1" />}
            {trailing}
        </div>
    );
}
