import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const GraphhopperIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/graphhopper.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const GraphhopperNode: NodeDefinition = {
    type: 'automation-graphhopper', category: 'industry', label: 'GraphHopper',
    description: 'Plan routes, geocode addresses, calculate matrices and optimize deliveries',
    Icon: GraphhopperIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={GraphhopperIcon} iconColor="" />),
};
