import { memo } from 'react';
import type { CSSProperties } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition } from './types';

// Unmodified shorthand from Etsy's official press brand-assets archive.
const EtsyIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/etsy.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const EtsyNode: NodeDefinition = {
    type: 'automation-etsy',
    label: 'Etsy',
    description: 'Manage Etsy listings, inventory, orders and shop settings',
    category: 'ecommerce',
    keywords: ['marketplace', 'handmade', 'receipts', 'shipping', 'stock'],
    Icon: EtsyIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={EtsyIcon} iconColor="" />),
};
