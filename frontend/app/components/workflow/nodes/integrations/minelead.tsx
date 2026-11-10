import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const MineleadIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <ThemedBrandImg light="/icons/minelead.svg" dark="/icons/minelead-dark.svg" className={className} style={style} {...props} ref={ref} />
    ),
);
MineleadIcon.displayName = 'MineleadIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const MineleadNode: NodeDefinition = {
    type: 'automation-minelead',
    label: 'Minelead',
    description: 'Find and enrich prospects, manage leads and campaign recipient lists',
    category: 'crm-sales',
    Icon: MineleadIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={MineleadIcon} iconColor="" />),
};
