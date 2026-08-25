// On-error node — triggered when a workflow execution encounters an error.
// One per workflow. Its forward-reachable subgraph runs with error details,
// enabling error notification flows (Slack alerts, emails, logging, etc.).

import { memo } from 'react';
import { NodeProps } from '@xyflow/react';
import { AlertTriangle } from 'lucide-react';
import AutomationNode from './base/AutomationNode';
import type { NodeDefinition } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const OnErrorNodeComponent = (props: NodeProps) => {
    return (
        <AutomationNode
            {...props}
            Icon={AlertTriangle}
            iconColor="text-red-600 dark:text-red-400"
            hideLeftHandle
            bgGradient="radial-gradient(circle at 30% 30%, rgba(239, 68, 68, 0.25), hsl(var(--card) / 0.95))"
        />
    );
};

export const OnErrorNode: NodeDefinition = {
    type: 'on-error',
    label: 'On Error',
    description: 'Runs when workflow fails',
    Icon: AlertTriangle,
    iconColor: 'text-red-600 dark:text-red-400',
    dimensions: DIMENSIONS,
    component: memo(OnErrorNodeComponent),
};
