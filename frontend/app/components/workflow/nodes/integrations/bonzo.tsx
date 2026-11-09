import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const BonzoIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/bonzo.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
BonzoIcon.displayName = 'BonzoIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const BonzoNode: NodeDefinition = {
    type: 'automation-bonzo',
    label: 'Bonzo',
    description: 'Manage BONZO prospects, campaigns, pipelines, notes and tasks',
    category: 'crm-sales',
    Icon: BonzoIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={BonzoIcon} iconColor="" />),
};
