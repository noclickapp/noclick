// SureCart commerce actions use the provider's official icon. This definition
// makes the self-registering integration available in the canvas and catalog.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const SureCartIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/surecart.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
SureCartIcon.displayName = 'SureCartIcon';

export const SureCartNode: NodeDefinition = {
    type: 'automation-surecart',
    label: 'SureCart',
    description: 'Manage customers, products, orders, purchases, coupons and subscriptions',
    category: 'ecommerce',
    keywords: ['store', 'commerce', 'WordPress', 'membership', 'billing'],
    Icon: SureCartIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SureCartIcon} iconColor="" />),
};
