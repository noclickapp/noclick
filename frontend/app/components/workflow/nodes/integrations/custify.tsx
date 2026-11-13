// Adds Custify to the canvas and integration catalog. Configuration and credentials
// are generated from the backend node's published operation models.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const CustifyIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/custify.svg" dark="/icons/custify-dark.svg" className={className} style={style} />
);

export const CustifyNode: NodeDefinition = {
    type: 'automation-custify', category: 'crm-sales', label: 'Custify',
    description: 'Manage customer people, companies, tasks, tickets, events and surveys',
    keywords: ['customer success', 'health scores', 'CSM', 'customer retention'],
    Icon: CustifyIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={CustifyIcon} iconColor="" />),
};
