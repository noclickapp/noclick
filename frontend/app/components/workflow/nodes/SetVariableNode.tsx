// Set Variable node — stores a value as a named global variable ({{vars.name}}).
// Typically placed in setup subgraphs after form nodes to persist collected values
// so main workflow nodes can reference them via {{vars.variable_name}}.

import { memo } from 'react';
import { NodeProps } from '@xyflow/react';
import { Variable } from 'lucide-react';
import AutomationNode from './base/AutomationNode';
import type { NodeDefinition } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const SetVariableNodeComponent = (props: NodeProps) => {
    return (
        <AutomationNode
            {...props}
            Icon={Variable}
            iconColor="text-emerald-600 dark:text-emerald-400"
        />
    );
};

export const SetVariableNode: NodeDefinition = {
    type: 'set-variable',
    label: 'Set Variable',
    description: 'Global value store',
    Icon: Variable,
    iconColor: 'text-emerald-600 dark:text-emerald-400',
    dimensions: DIMENSIONS,
    component: memo(SetVariableNodeComponent),
};
