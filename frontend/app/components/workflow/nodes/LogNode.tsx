// Log node for writing activity entries to the Feed.
// Simple automation-style node with a single input and output.

import { memo } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import type { NodeDefinition } from './types';
import { ScrollText } from 'lucide-react';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const LogNodeComponent = (props: NodeProps) => (
    <AutomationNode
        {...props}
        Icon={ScrollText}
        iconColor="text-muted-foreground"
        width={DIMENSIONS.width}
        height={DIMENSIONS.height}
        iconSize={DIMENSIONS.iconSize}
    />
);

export const LogNode: NodeDefinition = {
    type: 'log',
    label: 'Log',
    description: 'Log activity to feed',
    Icon: ScrollText,
    iconColor: 'text-muted-foreground',
    dimensions: DIMENSIONS,
    component: memo(LogNodeComponent),
};
