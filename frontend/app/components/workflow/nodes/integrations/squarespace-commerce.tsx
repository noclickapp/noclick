import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const SquarespaceCommerceIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/squarespace-commerce.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' } as CSSProperties} />
);

export const SquarespaceCommerceNode: NodeDefinition = {
    type: 'automation-squarespace-commerce', category: 'ecommerce', label: 'Squarespace Commerce',
    description: 'Manage store inventory and fulfill orders; read products, transactions and customers',
    keywords: ['squarespace', 'store', 'ecommerce', 'inventory', 'orders'],
    Icon: SquarespaceCommerceIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SquarespaceCommerceIcon} iconColor="" />),
};
