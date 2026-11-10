import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const FomoIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/fomo.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const FomoNode: NodeDefinition = {
    type: 'automation-fomo', category: 'marketing', label: 'Fomo',
    description: 'Create and manage social proof events, notification templates and widget settings',
    keywords: ['social proof', 'notifications', 'conversions', 'testimonials'],
    Icon: FomoIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={FomoIcon} iconColor="" />),
};
