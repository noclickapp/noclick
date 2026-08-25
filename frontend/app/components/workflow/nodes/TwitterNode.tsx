// Twitter/X REST API v2 automation node definition.
// Provides workflow integration for Twitter/X with tweets, users, likes, retweets, follows, and more.

import { memo } from 'react';
import { NodeProps } from '@xyflow/react';
import { SiX } from 'react-icons/si';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const TwitterNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={SiX} iconColor="text-foreground" />;
};

export const TwitterNode: NodeDefinition = {
    type: 'automation-twitter',
    label: 'X',
    description: 'Twitter/X automation',
    Icon: SiX,
    iconColor: 'text-foreground',
    dimensions: DIMENSIONS,
    component: memo(TwitterNodeComponent),
};
