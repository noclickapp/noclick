// Tentary's self-registering catalog and canvas definition.
// Its official icon identifies account, commerce and course operations.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const TentaryIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/tentary.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const TentaryNode: NodeDefinition = {
    type: 'automation-tentary', category: 'ecommerce', label: 'Tentary',
    description: 'Manage digital products, courses, customers, coupons and product access',
    keywords: ['digital products', 'courses', 'coupons', 'sales', 'access'],
    Icon: TentaryIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={TentaryIcon} iconColor="" />),
};
