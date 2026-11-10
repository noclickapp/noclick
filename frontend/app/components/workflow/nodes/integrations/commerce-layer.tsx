import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const CommerceLayerIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/commerce-layer.svg" dark="/icons/commerce-layer-dark.svg" className={className} style={style} />
);

export const CommerceLayerNode: NodeDefinition = {
    type: 'automation-commerce-layer', category: 'ecommerce', label: 'Commerce Layer',
    description: 'Manage orders, customers, SKUs, prices, inventory, shipments and line items',
    Icon: CommerceLayerIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={CommerceLayerIcon} iconColor="" />),
};
