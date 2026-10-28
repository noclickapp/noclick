// Table node: adds, reads, updates and deletes rows in this automation's own tables (the ones the Table block
// shows and Resources lists). No account to connect.

import { memo } from 'react';
import { NodeProps } from '@xyflow/react';
import { Table2 } from 'lucide-react';
import AutomationNode from './base/AutomationNode';
import type { NodeDefinition } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const TableNodeComponent = (props: NodeProps) => {
    return (
        <AutomationNode
            {...props}
            Icon={Table2}
            iconColor="text-sky-600 dark:text-sky-400"
        />
    );
};

export const TableNode: NodeDefinition = {
    type: 'automation-table',
    label: 'Table',
    description: 'Add, read, update and delete rows',
    keywords: [
        'rows',
        'database',
        'dataset',
        'records',
        'save results',
        'store',
        'log',
        'spreadsheet',
    ],
    Icon: Table2,
    iconColor: 'text-sky-600 dark:text-sky-400',
    dimensions: DIMENSIONS,
    component: memo(TableNodeComponent),
};
