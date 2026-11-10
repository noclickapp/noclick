import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const TrackPODIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/track-pod.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const TrackPODNode: NodeDefinition = {
    type: 'automation-track-pod', label: 'Track-POD', category: 'industry',
    description: 'Automate delivery orders, routes, drivers, vehicles and order status changes',
    keywords: ['delivery', 'logistics', 'dispatch', 'proof of delivery', 'track pod'],
    Icon: TrackPODIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={TrackPODIcon} iconColor="" />),
};
