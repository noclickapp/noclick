// RepairShopr's self-registering canvas and integration catalog definition.
// The shared automation node renders the generated operation and credential schema.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const RepairshoprIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/repairshopr.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const RepairshoprNode: NodeDefinition = {
    type: 'automation-repairshopr', category: 'industry', label: 'RepairShopr',
    description: 'Manage customers, tickets, contacts and leads; read invoices, estimates and products',
    Icon: RepairshoprIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={RepairshoprIcon} iconColor="" />),
};
