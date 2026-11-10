import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const ManusIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <ThemedBrandImg light="/icons/manus.svg" dark="/icons/manus-dark.svg" className={className} style={style} {...props} ref={ref} />
    ),
);
ManusIcon.displayName = 'ManusIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const ManusNode: NodeDefinition = {
    type: 'automation-manus',
    label: 'Manus',
    description: 'Start workflows from task events and automate tasks, messages, projects and files',
    category: 'ai',
    Icon: ManusIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ManusIcon} iconColor="" />),
};
