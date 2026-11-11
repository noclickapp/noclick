import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';

const IncreaseIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/increase.svg" dark="/icons/increase-dark.svg" className={className} style={style} />
);

export const IncreaseNode: NodeDefinition = {
    type: 'automation-increase', category: 'finance-accounting', label: 'Increase',
    description: 'Manage bank accounts, transactions, ACH and wire transfers, cards and banking events',
    Icon: IncreaseIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={IncreaseIcon} iconColor="" />),
};
