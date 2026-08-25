// BlueSky automation node definition.
// Uses AutomationNode component with BlueSky-specific configuration.

import { memo } from 'react';
import { NodeProps } from '@xyflow/react';
import { SiBluesky } from 'react-icons/si';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const BlueSkyNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={SiBluesky} iconColor="text-sky-500" />;
};

export const BlueSkyNode: NodeDefinition = {
    type: 'automation-bluesky',
    label: 'BlueSky',
    description: 'BlueSky automation',
    Icon: SiBluesky,
    iconColor: 'text-sky-500',
    dimensions: DIMENSIONS,
    component: memo(BlueSkyNodeComponent),
};
