import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const LeadfeederIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => <img ref={ref} src="/icons/leadfeeder.svg" alt="" className={className} style={{ objectFit: 'contain', ...style }} {...props} />,
);
LeadfeederIcon.displayName = 'LeadfeederIcon';

export const LeadfeederNode: NodeDefinition = {
    type: 'automation-leadfeeder',
    label: 'Leadfeeder (Dealfront)',
    description: 'Read accessible accounts, company intelligence and company workflow metadata',
    category: 'crm-sales',
    Icon: LeadfeederIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={LeadfeederIcon} iconColor="" />),
};
