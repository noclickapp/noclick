import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const PaystackIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <img
        src="/icons/paystack.svg"
        alt=""
        aria-hidden="true"
        className={className}
        style={{ ...style, objectFit: 'contain' }}
    />
);

export const PaystackNode: NodeDefinition = {
    type: 'automation-paystack',
    category: 'finance-accounting',
    label: 'Paystack',
    description:
        'Automate transactions, customers, plans, subscriptions, refunds and balances',
    keywords: ['payments', 'checkout', 'billing', 'recurring', 'refund'],
    Icon: PaystackIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(function PaystackNodeComponent(props: NodeProps) {
        return <AutomationNode {...props} Icon={PaystackIcon} iconColor="" />;
    }),
};
