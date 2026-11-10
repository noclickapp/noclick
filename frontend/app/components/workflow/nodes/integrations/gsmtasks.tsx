import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const GSMTasksIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/gsmtasks.svg" alt="" aria-hidden="true" className={className} style={style} />
);

export const GSMTasksNode: NodeDefinition = {
    type: 'automation-gsmtasks', category: 'industry', label: 'GSMTasks',
    description: 'Manage delivery tasks, workers, routes and signed task events',
    keywords: ['dispatch', 'delivery', 'fleet', 'field service', 'GSMTasks Project API'],
    Icon: GSMTasksIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={GSMTasksIcon} iconColor="" />),
};
