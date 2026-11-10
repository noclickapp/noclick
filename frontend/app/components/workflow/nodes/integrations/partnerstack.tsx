import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const PartnerStackIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <ThemedBrandImg {...props} light="/icons/partnerstack.svg" dark="/icons/partnerstack-dark.svg" className={className} style={style} ref={ref} />
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
