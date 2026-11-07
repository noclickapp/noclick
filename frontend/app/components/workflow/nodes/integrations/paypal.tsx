import { memo } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';


import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://www.paypal.com/in/home
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/paypal-brand-vector.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as BrandCSSProperties} />
);

const PayPalNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="text-blue-500" />
);

export const PayPalNode: NodeDefinition = {
    type: 'automation-paypal',
    label: 'PayPal',
    category: 'finance-accounting',
    description: 'PayPal orders, payments, subscriptions, invoices, and reporting',
    Icon: OfficialBrandIcon,
    iconColor: 'text-blue-500',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(PayPalNodeComponent),
};
