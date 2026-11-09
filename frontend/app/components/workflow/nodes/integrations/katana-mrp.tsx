// Katana's catalog and canvas definition uses the provider's official brand asset.
// Backend discovery generates its form and credential metadata separately.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const KatanaIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/katana-mrp.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
KatanaIcon.displayName = 'KatanaIcon';

export const KatanaMRPNode: NodeDefinition = {
    type: 'automation-katana-mrp',
    label: 'Katana',
    description: 'Manage manufacturing, inventory, customers and orders, and react to delivered sales orders',
    category: 'industry',
    keywords: ['katana mrp', 'manufacturing', 'inventory', 'sales orders', 'purchase orders'],
    Icon: KatanaIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={KatanaIcon} iconColor="" />),
};
