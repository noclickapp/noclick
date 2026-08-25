// Threads (by Meta) automation node definition.
// Threads API: publishing, replies/conversations, insights, profile discovery,
// keyword search, mentions, location, plus per-topic webhook triggers.

import { memo } from 'react';
import { NodeProps } from '@xyflow/react';
import { SiThreads } from 'react-icons/si';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const ThreadsNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={SiThreads} iconColor="" />;
};

export const ThreadsNode: NodeDefinition = {
    type: 'automation-threads',
    label: 'Threads',
    description: 'Threads posts, replies, insights & webhooks',
    Icon: SiThreads,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(ThreadsNodeComponent),
};
