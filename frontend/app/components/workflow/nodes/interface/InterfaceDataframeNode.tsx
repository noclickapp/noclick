// Interface dataframe/table node for rendering an AG Grid table in the workflow canvas.
// Renders the actual Dataframe block UI inside ReactFlow.

import { NodeProps } from '@xyflow/react';
import { TableGridIcon } from './interfaceIcons';
import InterfaceNode from './InterfaceNode';
import type { NodeDefinition } from '../types';

const DIMENSIONS = { width: 800, height: 500, iconSize: 48 };

const InterfaceDataframeNodeComponent = (props: NodeProps) => {
    return <InterfaceNode {...props} Icon={TableGridIcon} iconColor="text-sky-600 dark:text-sky-400" />;
};

export const InterfaceDataframeNode: NodeDefinition = {
    type: 'interface-dataframe',
    label: 'Table',
    description: 'AG Grid table',
    Icon: TableGridIcon,
    iconColor: 'text-sky-600 dark:text-sky-400',
    dimensions: DIMENSIONS,
    component: InterfaceDataframeNodeComponent,
};
