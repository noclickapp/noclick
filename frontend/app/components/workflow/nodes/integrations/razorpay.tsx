// Display the self-registering Razorpay integration in the workflow catalog.
// Its schema and credential metadata are generated from the backend node.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const RazorpayIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/razorpay.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const RazorpayNode: NodeDefinition = {
    type: 'automation-razorpay', label: 'Razorpay',
    description: 'Automate customers, orders, payments, invoices, items, plans, subscriptions and payment links',
    Icon: RazorpayIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={RazorpayIcon} iconColor="" />),
};
