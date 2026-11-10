import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const BonzoIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <ThemedBrandImg light="/icons/bonzo.svg" dark="/icons/bonzo-dark.svg" className={className} style={style} {...props} ref={ref} />
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
