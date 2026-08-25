// Delay node for adding wait/timeout functionality in workflows.
// Pauses workflow execution for a specified duration before continuing.

import { memo } from 'react';
import { NodeProps } from '@xyflow/react';
import { Pause } from 'lucide-react';
import AutomationNode from './base/AutomationNode';
import type { NodeDefinition } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

// ============================================================================
// Node Component
// ============================================================================

const DelayNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={Pause} iconColor="text-amber-600 dark:text-amber-400" />;
};

export const DelayNode: NodeDefinition = {
    type: 'delay',
    label: 'Delay',
    description: 'Wait for a specified time',
    Icon: Pause,
    iconColor: 'text-amber-600 dark:text-amber-400',
    dimensions: DIMENSIONS,
    component: memo(DelayNodeComponent),
};
