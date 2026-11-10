import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const LeapCRMIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/leap-crm.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const LeapCRMNode: NodeDefinition = {
    type: 'automation-leap-crm', category: 'crm-sales', label: 'Leap CRM',
    description: 'Manage customers, jobs, notes and contacts in Leap CRM',
    keywords: ['JobProgress'],
    Icon: LeapCRMIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={LeapCRMIcon} iconColor="" />),
};
