// Defines the discoverable Lightspeed Retail X-Series workflow node.
// The official developer portal icon identifies it in the canvas and catalog.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const LightspeedIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/lightspeed.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
LightspeedIcon.displayName = 'LightspeedIcon';

// Exact publisher asset; provenance is recorded beside the PNG.
export const LightspeedNode: NodeDefinition = {
    type: 'automation-lightspeed',
    label: 'Lightspeed',
    description: 'Retail X-Series customers, products, inventory, sales and stores',
    category: 'ecommerce',
    keywords: ['retail', 'X-Series', 'Vend', 'POS', 'inventory'],
    Icon: LightspeedIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={LightspeedIcon} iconColor="" />),
};
