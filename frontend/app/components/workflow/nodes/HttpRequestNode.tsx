// HTTP Request automation node definition.
// Handles arbitrary HTTP requests (GET, POST, PUT, PATCH, DELETE) to external APIs.

import { memo } from 'react';
import { NodeProps } from '@xyflow/react';
import { Globe } from 'lucide-react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const HttpRequestNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={Globe} iconColor="text-emerald-600 dark:text-emerald-400" />;
};

export const HttpRequestNode: NodeDefinition = {
    type: 'automation-http-request',
    label: 'HTTP Request',
    description: 'Make HTTP requests',
    Icon: Globe,
    iconColor: 'text-emerald-600 dark:text-emerald-400',
    dimensions: DIMENSIONS,
    component: memo(HttpRequestNodeComponent),
};
