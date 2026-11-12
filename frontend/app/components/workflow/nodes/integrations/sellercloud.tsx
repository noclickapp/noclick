import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const SellerCloudIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/sellercloud.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
SellerCloudIcon.displayName = 'SellerCloudIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const SellerCloudNode: NodeDefinition = {
    type: 'automation-sellercloud',
    label: 'SellerCloud',
    description: 'Manage SellerCloud orders, inventory, customers and purchase orders',
    category: 'ecommerce',
    Icon: SellerCloudIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SellerCloudIcon} iconColor="" />),
};
