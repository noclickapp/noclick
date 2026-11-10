// Adds Custify to the canvas and integration catalog. Configuration and credentials
// are generated from the backend node's published operation models.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const CustifyIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/custify.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const CustifyNode: NodeDefinition = {
    type: 'automation-custify', category: 'crm-sales', label: 'Custify',
    description: 'Manage customer people, companies, tasks, tickets, events and surveys',
    keywords: ['customer success', 'health scores', 'CSM', 'customer retention'],
    Icon: CustifyIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={CustifyIcon} iconColor="" />),
};
