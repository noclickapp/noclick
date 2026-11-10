import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const RefersionIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <ThemedBrandImg {...props} light="/icons/refersion.svg" dark="/icons/refersion-dark.svg" className={className} style={style} ref={ref} />
    ),
);
RefersionIcon.displayName = 'RefersionIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const RefersionNode: NodeDefinition = {
    type: 'automation-refersion',
    label: 'Refersion',
    description: 'Manage affiliates, conversions, offers, orders and webhooks',
    category: 'marketing',
    Icon: RefersionIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={RefersionIcon} iconColor="" />),
};
