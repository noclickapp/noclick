// Bold Commerce uses the shared automation canvas with its own generated schema.
// The official publisher icon identifies subscription and customer workflows.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const BoldCommerceIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/bold-commerce.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
BoldCommerceIcon.displayName = 'BoldCommerceIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const BoldCommerceNode: NodeDefinition = {
    type: 'automation-bold-commerce',
    label: 'Bold Commerce',
    description: 'Manage Bold subscriptions, customers, orders and signed webhook events',
    category: 'ecommerce',
    Icon: BoldCommerceIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={BoldCommerceIcon} iconColor="" />),
};
