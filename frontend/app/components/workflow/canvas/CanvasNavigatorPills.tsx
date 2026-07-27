// Positions the bottom-left navigator pills — the red errored-nodes pill and the
// amber incomplete-nodes pill — as one flex row.
//
// They used to place themselves independently, the amber one at a hardcoded
// `left: 170px` that stood in for "16px + the red pill's width". The red pill is
// really ~125px, so a visible gap sat between them, and it moved with the digit
// count. A shared row with a fixed gap makes the spacing exact at any count, and
// keeps the two in step when the flow-helper panel raises them.
import type { ReactNode } from 'react';

interface CanvasNavigatorPillsProps {
    isConfigViewExpanded: boolean;
    flowHelperHeight: number;
    /** Skip the reposition transition (flow helper opened via a key). */
    noAnimation?: boolean;
    children: ReactNode;
}

export function CanvasNavigatorPills({
    isConfigViewExpanded,
    flowHelperHeight,
    noAnimation,
    children,
}: CanvasNavigatorPillsProps) {
    return (
        <div
            className="absolute left-4 z-10 flex items-center gap-2"
            style={{
                bottom: isConfigViewExpanded ? `${flowHelperHeight + 12}px` : '12px',
                // Match FlowHelperView's height transition (280ms + same bezier) so
                // the pills ride up/down with the panel instead of trailing it;
                // skip it when opened via a key so they snap.
                transition: noAnimation
                    ? 'none'
                    : 'bottom 280ms cubic-bezier(0.22, 0.61, 0.36, 1)',
            }}
        >
            {children}
        </div>
    );
}
