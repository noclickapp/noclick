import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const PartnerStackIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/partnerstack.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
PartnerStackIcon.displayName = 'PartnerStackIcon';

// Exact publisher asset; provenance is recorded beside the icon.
export const PartnerStackNode: NodeDefinition = {
    type: 'automation-partnerstack',
    label: 'PartnerStack',
    description: 'Manage partners, customers, leads, deals and transactions',
    category: 'crm-sales',
    Icon: PartnerStackIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={PartnerStackIcon} iconColor="" />),
};
