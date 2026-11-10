import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const FuseaiIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/fuseai.svg" dark="/icons/fuseai-dark.svg" className={className} style={style} />
);

export const FuseaiNode: NodeDefinition = {
    type: 'automation-fuseai', category: 'crm-sales', label: 'Fuseai',
    description: 'Manage prospect lists and campaigns, find emails and verify contact data',
    Icon: FuseaiIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={FuseaiIcon} iconColor="" />),
};
