import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const TidioIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <ThemedBrandImg light="/icons/tidio.svg" dark="/icons/tidio-dark.svg" className={className} style={style} {...props} ref={ref} />
    ),
);
TidioIcon.displayName = 'TidioIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const TidioNode: NodeDefinition = {
    type: 'automation-tidio',
    label: 'Tidio',
    description: 'Manage contacts, chat messages and support tickets',
    category: 'support',
    Icon: TidioIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={TidioIcon} iconColor="" />),
};
