import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const OnedeskIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/onedesk.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const OnedeskNode: NodeDefinition = {
    type: 'automation-onedesk', category: 'support', label: 'OneDesk',
    description: 'Manage tickets, tasks, customers, projects, timesheets and conversations',
    keywords: ['onedesk', 'helpdesk', 'ticket', 'time tracking'],
    Icon: OnedeskIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={OnedeskIcon} iconColor="" />),
};
