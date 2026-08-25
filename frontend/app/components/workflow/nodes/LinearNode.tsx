// Linear automation node definition.
// Generated from MCP - Uses AutomationNode component with Linear-specific configuration.

import { memo } from 'react';
import { NodeProps } from '@xyflow/react';
import { SiLinear } from 'react-icons/si';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const LinearNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={SiLinear} iconColor="text-indigo-600 dark:text-indigo-400" />;
};

export const LinearNode: NodeDefinition = {
    type: 'automation-linear',
    label: 'Linear',
    description: 'Linear automation',
    Icon: SiLinear,
    iconColor: 'text-indigo-600 dark:text-indigo-400',
    dimensions: DIMENSIONS,
    component: memo(LinearNodeComponent),
};
