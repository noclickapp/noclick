// Instagram Graph API automation node definition.
// Uses Facebook OAuth for Instagram Business/Creator accounts.

import { memo } from 'react';
import { NodeProps } from '@xyflow/react';
import { InstagramIcon } from '~/components/icons/InstagramIcon';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const InstagramNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={InstagramIcon} iconColor="text-pink-500" />;
};

export const InstagramNode: NodeDefinition = {
    type: 'automation-instagram',
    label: 'Instagram',
    description: 'Instagram Automation',
    Icon: InstagramIcon,
    iconColor: 'text-pink-500',
    dimensions: DIMENSIONS,
    component: memo(InstagramNodeComponent),
};
