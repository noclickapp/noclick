import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const LeapIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/leap.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const LeapNode: NodeDefinition = {
    type: 'automation-leap', category: 'crm-sales', label: 'Leap',
    description: 'Manage Leap CRM customers, jobs, notes, contacts and tasks',
    Icon: LeapIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={LeapIcon} iconColor="" />),
};
