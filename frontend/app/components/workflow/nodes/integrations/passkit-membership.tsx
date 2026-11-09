import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const PassKitMembershipIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/passkit-membership.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
PassKitMembershipIcon.displayName = 'PassKitMembershipIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const PassKitMembershipNode: NodeDefinition = {
    type: 'automation-passkit-membership',
    label: 'PassKit Membership',
    description: 'Membership cards, loyalty points, tiers and member check-ins',
    category: 'marketing',
    Icon: PassKitMembershipIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={PassKitMembershipIcon} iconColor="" />),
};
