import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const PropertyRadarIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/propertyradar.svg" dark="/icons/propertyradar-dark.svg" className={className} style={style} />
);

export const PropertyRadarNode: NodeDefinition = {
    type: 'automation-propertyradar', category: 'industry', label: 'PropertyRadar',
    description: 'Search properties and manage real estate lists, members and webhooks',
    Icon: PropertyRadarIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={PropertyRadarIcon} iconColor="" />),
};
