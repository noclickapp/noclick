// Registers Whop in the workflow canvas and integration catalog.
// Uses the official provider icon shipped with its provenance review.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const WhopIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/whop.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
WhopIcon.displayName = 'WhopIcon';

// Exact publisher asset; provenance is recorded beside the icon.
export const WhopNode: NodeDefinition = {
    type: 'automation-whop',
    label: 'Whop',
    description: 'Manage Whop products, memberships, payments and promo codes',
    category: 'ecommerce',
    Icon: WhopIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={WhopIcon} iconColor="" />),
};
