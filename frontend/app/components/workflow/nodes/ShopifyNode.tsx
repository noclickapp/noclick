// Shopify Admin REST API automation node definition.
// Provides workflow integration for e-commerce operations including products, orders,
// customers, and inventory management.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

// Use SVG icon from /public/icons/shopify.svg
const ShopifyIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img
            ref={ref}
            src="/icons/shopify.svg"
            alt=""
            className={className}
            style={style}
            {...props}
        />
    )
);
ShopifyIcon.displayName = 'ShopifyIcon';

const ShopifyNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={ShopifyIcon} iconColor="" />;
};

export const ShopifyNode: NodeDefinition = {
    type: 'automation-shopify',
    label: 'Shopify',
    description: 'Shopify automation',
    Icon: ShopifyIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(ShopifyNodeComponent),
};
