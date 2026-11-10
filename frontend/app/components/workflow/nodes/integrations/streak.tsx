import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const StreakIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/streak.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const StreakNode: NodeDefinition = {
    type: 'automation-streak', category: 'crm-sales', label: 'Streak',
    description: 'Manage CRM teams, boxes, contacts, organizations, tasks and comments',
    Icon: StreakIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={StreakIcon} iconColor="" />),
};
