import { memo, type CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';

const CloverIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/clover.svg" className={className} style={style} />
);
const CloverNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={CloverIcon} iconColor="" />
);

export const CloverNode: NodeDefinition = {
    type: 'automation-clover',
    label: 'Clover',
    description: 'Manage Clover orders, customers, payments and inventory, and watch for changes',
    category: 'ecommerce',
    Icon: CloverIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(CloverNodeComponent),
};
