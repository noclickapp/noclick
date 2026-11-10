import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const BatchDialerIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/batchdialer.svg" dark="/icons/batchdialer-dark.svg" className={className} style={style} />
);

export const BatchDialerNode: NodeDefinition = {
    type: 'automation-batchdialer', category: 'crm-sales', label: 'BatchDialer',
    description: 'Manage contacts, campaigns, call history and transcriptions',
    Icon: BatchDialerIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={BatchDialerIcon} iconColor="" />),
};
