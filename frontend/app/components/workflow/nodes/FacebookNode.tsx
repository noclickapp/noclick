// Facebook (Pages + Messenger) automation node definition.

import { memo } from 'react';
import { NodeProps } from '@xyflow/react';
import { SiFacebook } from 'react-icons/si';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const FacebookNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={SiFacebook} iconColor="text-[#1877F2]" />;
};

export const FacebookNode: NodeDefinition = {
    type: 'automation-facebook',
    label: 'Facebook',
    description: 'Facebook Pages & Messenger automation',
    Icon: SiFacebook,
    iconColor: 'text-[#1877F2]',
    dimensions: DIMENSIONS,
    component: memo(FacebookNodeComponent),
};
