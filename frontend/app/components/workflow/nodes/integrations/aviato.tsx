import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const AviatoIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/aviato.webp" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
AviatoIcon.displayName = 'AviatoIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const AviatoNode: NodeDefinition = {
    type: 'automation-aviato',
    label: 'Aviato',
    description: 'Enrich companies and people, search prospects and generate market maps',
    category: 'crm-sales',
    Icon: AviatoIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={AviatoIcon} iconColor="" />),
};
