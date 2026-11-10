// Display the self-registering Razorpay integration in the workflow catalog.
// Its schema and credential metadata are generated from the backend node.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const RazorpayIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/razorpay.svg" dark="/icons/razorpay-dark.svg" className={className} style={style} />
);

export const RazorpayNode: NodeDefinition = {
    type: 'automation-razorpay', category: 'finance-accounting', label: 'Razorpay',
    description: 'Automate customers, orders, payments, invoices, items, plans, subscriptions and payment links',
    Icon: RazorpayIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={RazorpayIcon} iconColor="" />),
};
