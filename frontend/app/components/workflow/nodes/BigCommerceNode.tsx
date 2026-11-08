// BigCommerce store automation for orders, products, customers and inventory.
// Uses the official B mark to identify the connected provider.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import type { NodeDefinition } from './types';

const BigCommerceIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/bigcommerce.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);
const BigCommerceNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={BigCommerceIcon} iconColor="" />
);
export const BigCommerceNode: NodeDefinition = {
    type: 'automation-bigcommerce', category: 'ecommerce', label: 'BigCommerce',
    description: 'Automate store orders, products, customers and inventory',
    keywords: ['ecommerce', 'store', 'stock', 'shipping'],
    Icon: BigCommerceIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(BigCommerceNodeComponent),
};
