import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const GraphhopperIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/graphhopper.svg" dark="/icons/graphhopper-dark.svg" className={className} style={style} />
);

export const GraphhopperNode: NodeDefinition = {
    type: 'automation-graphhopper', category: 'industry', label: 'GraphHopper',
    description: 'Plan routes, geocode addresses, calculate matrices and optimize deliveries',
    Icon: GraphhopperIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={GraphhopperIcon} iconColor="" />),
};
