import { forwardRef, type CSSProperties, type ImgHTMLAttributes } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

// Unmodified official full-color mark; preserve supplied canvas filters and aspect ratio.
export const GoatCounterIcon = forwardRef<HTMLImageElement, ImgHTMLAttributes<HTMLImageElement>>(
    ({ style, ...props }, ref) => (
        <img {...props} ref={ref} src="/icons/goatcounter.svg" alt="" aria-hidden="true"
            style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
    ),
);
GoatCounterIcon.displayName = 'GoatCounterIcon';

const GoatCounterNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={GoatCounterIcon} iconColor="" />
);
export const GoatCounterNode: NodeDefinition = {
    type: 'automation-goatcounter', category: 'analytics-bi', label: 'GoatCounter',
    description: 'GoatCounter site metadata and bounded aggregated count reads',
    keywords: ['GoatCounter', 'web analytics', 'site metadata', 'visitor counts'],
    Icon: GoatCounterIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: GoatCounterNodeComponent,
};
