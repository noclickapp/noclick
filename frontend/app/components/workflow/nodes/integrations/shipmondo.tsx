import { memo, type CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ShipmondoIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/shipmondo.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const ShipmondoNode: NodeDefinition = {
    type: 'automation-shipmondo', category: 'ecommerce', label: 'Shipmondo',
    description: 'Manage shipments, shipping labels, sales orders and items, and receive shipping events',
    keywords: ['shipping', 'labels', 'fulfillment', 'tracking', 'logistics'],
    Icon: ShipmondoIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ShipmondoIcon} iconColor="" />),
};
