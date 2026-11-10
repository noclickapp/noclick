import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const ManychatIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/manychat.svg" dark="/icons/manychat-dark.svg" className={className} style={style} />
);

export const ManychatNode: NodeDefinition = {
    type: 'automation-manychat', category: 'marketing', label: 'Manychat',
    description: 'Manage contacts, tags, custom fields, bot fields and send flows',
    Icon: ManychatIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ManychatIcon} iconColor="" />),
};
