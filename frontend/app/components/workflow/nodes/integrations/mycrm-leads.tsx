import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const MyCRMIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/mycrm-leads.svg" className={className} style={style} />
);

export const MyCRMLeadsNode: NodeDefinition = {
    type: 'automation-mycrm-leads', category: 'crm-sales', label: 'MyCRM Leads',
    description: 'Create leads, manage contacts and tasks, read deals, and add deal notes',
    Icon: MyCRMIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={MyCRMIcon} iconColor="" />),
};
