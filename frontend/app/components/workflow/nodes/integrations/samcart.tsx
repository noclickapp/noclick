import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const SamCartIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <img
        src="/icons/samcart.svg"
        alt=""
        aria-hidden="true"
        className={className}
        style={
            {
                ...style,
                '--brand-invert': 0,
                objectFit: 'contain',
            } as CSSProperties
        }
    />
);

export const SamCartNode: NodeDefinition = {
    type: 'automation-samcart',
    category: 'ecommerce',
    label: 'SamCart',
    description:
        'Manage orders, customers, products, charges, refunds and subscriptions',
    Icon: SamCartIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(function SamCartComponent(props: NodeProps) {
        return <AutomationNode {...props} Icon={SamCartIcon} iconColor="" />;
    }),
};
