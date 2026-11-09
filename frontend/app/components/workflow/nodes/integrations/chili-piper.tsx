import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ChiliPiperIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/chili-piper.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const ChiliPiperNode: NodeDefinition = {
    type: 'automation-chili-piper',
    category: 'meetings',
    label: 'Chili Piper',
    description: 'Book and manage meetings, find hosts and booking pages, and manage meeting webhooks',
    keywords: ['ChiliPiper', 'scheduling', 'sales meetings', 'booking'],
    Icon: ChiliPiperIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ChiliPiperIcon} iconColor="" />),
};
