// Stripe API automation node definition.
// Provides workflow integration with Stripe for payments, billing, subscriptions, and Connect.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

// Custom SVG logo from /public/icons/stripe.svg
const StripeIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img
            ref={ref}
            src="/icons/stripe.svg"
            alt=""
            className={className}
            style={style}
            {...props}
        />
    )
);
StripeIcon.displayName = 'StripeIcon';

const StripeNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={StripeIcon} iconColor="" />;
};

export const StripeNode: NodeDefinition = {
    type: 'automation-stripe',
    label: 'Stripe',
    description: 'Payments, billing, subscriptions & Connect',
    Icon: StripeIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(StripeNodeComponent),
};
