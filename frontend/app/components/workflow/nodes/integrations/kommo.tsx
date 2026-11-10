import { memo, type CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const KommoIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/kommo.svg" dark="/icons/kommo-dark.svg" className={className} style={style} />
);
const KommoNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={KommoIcon} iconColor="" />
);

export const KommoNode: NodeDefinition = {
    type: 'automation-kommo',
    label: 'Kommo',
    description: 'Kommo CRM automation',
    category: 'crm-sales',
    Icon: KommoIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(KommoNodeComponent),
};
