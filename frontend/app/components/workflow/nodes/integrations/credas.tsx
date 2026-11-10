import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const CredasIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/credas.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
CredasIcon.displayName = 'CredasIcon';

// Exact publisher asset; provenance is recorded beside the PNG.
export const CredasNode: NodeDefinition = {
    type: 'automation-credas',
    label: 'Credas',
    description: 'Identity verification, entities, journeys and process results',
    category: 'industry',
    keywords: ['KYC', 'AML', 'IDV', 'identity verification', 'customer due diligence'],
    Icon: CredasIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={CredasIcon} iconColor="" />),
};
