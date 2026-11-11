import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const BitsnapIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <>
            <img ref={ref} src="/icons/bitsnap.svg" alt="" {...props} className={`${className ?? ''} dark:hidden`} style={style} />
            <img src="/icons/bitsnap-dark.svg" alt="" {...props} className={`${className ?? ''} hidden dark:block`} style={style} />
        </>
    ),
);
BitsnapIcon.displayName = 'BitsnapIcon';

export const BitsnapNode: NodeDefinition = {
    type: 'automation-bitsnap',
    label: 'Bitsnap',
    description: 'Manage shop products, orders, coupons, checkout links and leads; react to signed shop events.',
    category: 'ecommerce',
    keywords: ['shop', 'digital products', 'payments', 'coupons', 'orders', 'subscriptions', 'leads', 'webhooks'],
    Icon: BitsnapIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={BitsnapIcon} iconColor="" />),
};
