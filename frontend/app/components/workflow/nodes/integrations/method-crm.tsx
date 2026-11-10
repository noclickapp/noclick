// Method CRM uses its official published API logo in the workflow catalog.
// This definition makes the self-registering CRM node available on the canvas.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const MethodCRMIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/method-crm.svg" dark="/icons/method-crm-dark.svg" className={className} style={style} />
);

export const MethodCRMNode: NodeDefinition = {
    type: 'automation-method-crm', category: 'crm-sales', label: 'Method CRM',
    description: 'Query and manage CRM records, accounting sync and file links',
    Icon: MethodCRMIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={MethodCRMIcon} iconColor="" />),
};
